"""The AI pre-label step on a fictional profile and fictional ads, with the model replaced. No real data, no network."""

import json
import stat
from types import SimpleNamespace

import pytest

from calibration import prelabel as pl
from conftest import select_provider
from llm_client import LlmUnavailable

PROFILE = {
    "basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 123 4567",
                     "preferredLocations": ["Atlantis"], "salaryExpectation": "99999"},
    "resume": {"parsedData": {
        "links": ["https://zorana.example/me"],
        "experienceDetail": [{"title": "Product Manager", "company": "Initech", "start": "2018-01", "end": "2022-06",
                              "bullets": ["Led the billing roadmap for 40 customers", "Ran discovery with finance teams"]}],
        "skills": ["SQL", "Roadmapping"], "education": ["BSc Computer Science"], "certifications": [],
    }},
}
INTELLIGENCE = {"candidateSummary": {"seniorityLevel": "Senior"}, "experienceMap": {"yearsOfExperience": 9},
                "roleStrategy": {"primaryTargetRoles": ["Product Manager"]}, "languages": ["English"]}


def ad(n, **extra):
    return {"jobId": f"job{n}", "title": f"Role {n}", "company": f"Firm {n}", "location": "Remote", "site": "x",
            "jobUrl": f"https://example.test/{n}", "description": f"Own the roadmap number {n}. Contact hr{n}@third-party.test.", **extra}


GOOD = {"function_fit": "yes", "hard_requirements": "unknown", "overall": 2, "reason": "Fits.", "confidence": "high",
        "missing_information": []}


@pytest.fixture
def out(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna")
    folder = tmp_path / "stage-a"
    folder.mkdir()
    (folder / "review-items.json").write_text(json.dumps({"version": 1, "items": [ad(1), ad(2), ad(3)]}))
    monkeypatch.setattr(pl, "preflight", lambda *a, **k: SimpleNamespace(allowed=True, reason=None, row={}))
    return folder


class Model:
    def __init__(self, answers=None):
        self.prompts, self.answers = [], answers or {}

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        answer = self.answers.get(len(self.prompts), GOOD)
        if isinstance(answer, Exception):
            raise answer
        return answer


# --- the prompt ---------------------------------------------------------------------


def test_prompt_never_contains_a_holojob_score_field_even_when_the_row_carries_them():
    row = ad(1, matchScore=7777, matchLabel="SentinelLabel", priority="SentinelP", applyRecommendation="SentinelApply",
             reasons=["Capped: sentinel reason"], scoreBreakdown={"roleMatch": {"raw": 4242}}, confidence={"level": "SentinelLow"},
             llmFacts={"roleTrack": "sentinel_track"}, engineShadow={"fit": 31337}, hardCapped=True, dataStatus="SentinelStatus")
    prompt = pl.build_prompt(pl.candidate_block(PROFILE, INTELLIGENCE), row)
    for sentinel in ("7777", "SentinelLabel", "SentinelP", "SentinelApply", "sentinel reason", "4242", "SentinelLow",
                     "sentinel_track", "31337", "SentinelStatus", "matchScore", "engineShadow", "Capped"):
        assert sentinel not in prompt
    assert "Role 1" in prompt and "Firm 1" in prompt and "roadmap number 1" in prompt


def test_prefix_is_the_same_for_every_ad_and_only_the_tail_differs():
    block = pl.candidate_block(PROFILE, INTELLIGENCE)
    a, b = pl.build_prompt(block, ad(1)), pl.build_prompt(block, ad(2))
    head_a, head_b = a.split("=== BEGIN JOB AD")[0], b.split("=== BEGIN JOB AD")[0]
    assert head_a == head_b and pl.INSTRUCTIONS in head_a and "Initech" in head_a
    assert "Role 1" not in head_a and "Role 2" not in head_b


def test_evidence_sends_work_and_skills_but_no_identity_or_private_preferences():
    block = pl.candidate_block(PROFILE, INTELLIGENCE)
    assert "billing roadmap" in block and "SQL" in block and "Computer Science" in block and "Target roles: Product Manager" in block
    for private in ("Zorana", "Testovic", "example.test", "381", "Atlantis", "99999"):
        assert private not in block
    assert pl.owner_leaks(pl.build_prompt(block, ad(1)), PROFILE) == []


def test_third_party_contacts_in_the_ad_are_removed_before_sending():
    prompt = pl.build_prompt("block", ad(1, description="Write to hr@third-party.test or call +44 20 7946 0958 or see https://acme.test/jobs"))
    assert "third-party.test" not in prompt and "7946" not in prompt and "acme.test" not in prompt


# --- the privacy scan ------------------------------------------------------------------


@pytest.mark.parametrize("text,kind", [
    ("write to Zorana.Testovic@Example.test please", "e-mail"),
    ("call 064/123-4567 tomorrow", "phone"),
    ("call +381641234567", "phone"),
    ("Zorana Testovic led it", "name"),
    ("see zorana.example/me for more", "link"),
])
def test_scan_finds_each_kind_of_owner_identifier_and_never_returns_the_matched_text(text, kind):
    found = pl.owner_leaks(text, PROFILE)
    assert found and any(kind in k for k in found)
    assert not any(secret in " ".join(found) for secret in ("Zorana", "example.test", "4567", "zorana.example"))


def test_scan_also_flags_a_lone_part_of_the_name_anywhere_so_an_ad_that_contains_it_stops_the_run():
    assert pl.owner_leaks("worked with Testovic on it", PROFILE) == ["the owner's name"]
    assert pl.owner_leaks("generic text about roadmaps", PROFILE) == []


def test_one_leaky_prompt_stops_the_whole_run_before_any_call(out, monkeypatch):
    real = pl.build_evidence
    monkeypatch.setattr(pl, "build_evidence", lambda p, i: real(p, i) + [
        {"id": "x", "text": "reach me at zorana.testovic@example.test", "source": "fact", "role": None, "start": None, "end": None}])
    model = Model()
    result = pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=model)
    assert "privacy scan" in result["stopped"] and result["asked"] == 0 and model.prompts == []
    assert not (out / "ai-proposals.json").exists()
    assert "example.test" not in json.dumps(result)


# --- the estimate and the stop ----------------------------------------------------------------


def test_estimate_counts_only_what_is_still_to_ask_and_prices_it(out):
    p = pl.plan(out, PROFILE, INTELLIGENCE)
    assert len(p["pending"]) == 3 and p["costUsd"] > 0 and p["provider"] == "openai" and p["tier"] == "standard"
    expected = (sum(p["perAdTokens"]) * 0.10 + 3 * pl.OUTPUT_TOKENS * 0.50) / 1e6
    assert p["costUsd"] == pytest.approx(expected, abs=1e-4)
    assert any("estimated cost" in line for line in pl.describe(p)) and any("CLEAN" in line for line in pl.describe(p))


def test_an_estimate_over_the_hard_stop_sends_nothing(out, monkeypatch):
    monkeypatch.setattr(pl, "HARD_STOP_USD", 0.0001)
    model = Model()
    result = pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=model)
    assert "hard stop" in result["stopped"] and model.prompts == []


def test_a_gate_refusal_sends_nothing(out, monkeypatch):
    monkeypatch.setattr(pl, "preflight", lambda *a, **k: SimpleNamespace(allowed=False, reason="budget is 0", row={"class": "paid"}))
    monkeypatch.setattr(pl.ai_gate, "record_refused", lambda *a, **k: None)
    model = Model()
    assert "AI gate refused" in pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=model)["stopped"]
    assert model.prompts == []


# --- resuming ----------------------------------------------------------------------------------


def test_a_failed_batch_resumes_without_paying_again_for_finished_ads(out):
    first = Model({2: LlmUnavailable("down")})
    r1 = pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=first)
    assert (r1["ok"], r1["failed"]) == (2, 1) and len(first.prompts) == 3
    stored = json.loads((out / "ai-proposals.json").read_text())["proposals"]
    assert sorted(stored) == ["job1", "job3"] and stat.S_IMODE((out / "ai-proposals.json").stat().st_mode) == 0o600
    second = Model()
    r2 = pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=second)
    assert (r2["asked"], r2["ok"]) == (1, 1) and "Role 2" in second.prompts[0]
    third = Model()
    assert pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=third)["asked"] == 0 and third.prompts == []


def test_a_changed_profile_or_ad_asks_again_and_an_invalid_answer_is_kept_not_repaid(out):
    pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=Model({1: {"function_fit": "maybe"}}))
    stored = json.loads((out / "ai-proposals.json").read_text())["proposals"]
    assert stored["job1"]["status"] == "invalid" and stored["job2"]["status"] == "ok"
    again = Model()
    assert pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=again)["asked"] == 0  # invalid is not re-paid by itself
    retry = Model()
    assert pl.run(out, PROFILE, INTELLIGENCE, workers=1, complete=retry, retry_invalid=True)["asked"] == 1
    changed = json.loads(json.dumps(INTELLIGENCE))
    changed["roleStrategy"]["primaryTargetRoles"] = ["Program Manager"]
    assert pl.run(out, PROFILE, changed, workers=1, complete=Model())["asked"] == 3  # different evidence block


def test_proposals_carry_no_system_field_and_coerce_only_allowed_values():
    assert pl.coerce_proposal({**GOOD, "overall": 4}) is None
    assert pl.coerce_proposal({**GOOD, "overall": True}) is None
    assert pl.coerce_proposal({**GOOD, "hard_requirements": "n/a"}) is None
    kept = pl.coerce_proposal({**GOOD, "confidence": "certain", "missing_information": ["a", "b", "c", "d"], "reason": " two  words "})
    assert kept["confidence"] == "low" and kept["missingInformation"] == ["a", "b", "c"] and kept["reason"] == "two words"
