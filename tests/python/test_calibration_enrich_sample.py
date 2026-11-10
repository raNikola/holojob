"""The calibration enrichment runner on fictional ads, with the model replaced. No real data, no network, no production file."""

import json
import stat
from types import SimpleNamespace

import pytest

from calibration import enrich_sample as es
from conftest import select_provider
from llm_client import LlmUnavailable

PROFILE = {"basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test",
                            "phone": "+381 64 123 4567", "preferredLocations": ["Atlantis"]},
           "resume": {"parsedData": {"links": ["https://zorana.example/me"]}}}
INTELLIGENCE = {}  # no role family: no competency list, no mapper


def ad(n, **extra):
    base = {"jobId": f"job{n}", "title": f"Role {n}", "company": f"Firm {n}", "location": "Remote", "site": "x",
            "jobUrl": f"https://example.test/{n}",
            "description": f"Own the roadmap number {n}. Write to hr{n}@third-party.test or call +49 30 9876 5432 "
                           f"or see https://third-party.test/jobs/{n}."}
    return {**base, **extra}


def facts_for(job):
    return {"requirements": [{"id": "sql", "text": "SQL", "kind": "skill", "importance": "must"}],
            "_fingerprint": es.job_fingerprint(job)}


class Model:
    def __init__(self, fail_on=None):
        self.jobs, self.fail_on = [], fail_on or set()

    def __call__(self, job, model, provider, previous=None, mapper=None):
        self.jobs.append(job)
        if job["jobId"] in self.fail_on:
            raise LlmUnavailable("down")
        return facts_for(job)


@pytest.fixture
def out(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna")
    folder = tmp_path / "stage-a"
    folder.mkdir()
    write_items(folder, [ad(1), ad(2), ad(3)])
    monkeypatch.setattr(es, "preflight", lambda *a, **k: SimpleNamespace(allowed=True, reason=None, row={}))
    return folder


def write_items(folder, items):
    (folder / "review-items.json").write_text(json.dumps({"version": 1, "items": items}))


# --- redaction before the scan ----------------------------------------------------------


def test_third_party_contacts_are_replaced_before_the_scan_and_the_prompt_is_clean(out):
    p = es.plan(out, PROFILE, INTELLIGENCE)
    assert p["leaks"] == {}
    for prompt in p["prompts"].values():
        for raw in ("third-party.test", "+49 30 9876 5432", "9876"):
            assert raw not in prompt
        assert "roadmap number" in prompt  # the rest of the ad is untouched


def test_the_unredacted_ad_would_have_tripped_the_scan(out):
    from calibration.prelabel import owner_leaks
    assert owner_leaks(ad(1)["description"], PROFILE)  # why the redaction is needed


@pytest.mark.parametrize("field, value, kind", [
    ("title", "Role for Zorana Testovic", "name"),
    ("company", "Firm zorana.testovic@example.test", "e-mail"),
    ("location", "call +381 64 123 4567", "phone"),
    ("title", "see https://zorana.example/me", "link"),
])
def test_owner_identifiers_in_a_field_still_stop_the_whole_run_before_any_call(out, field, value, kind):
    write_items(out, [ad(1), ad(2, **{field: value}), ad(3)])
    model = Model()
    result = es.run(out, PROFILE, INTELLIGENCE, extract=model)
    assert "privacy scan" in result["stopped"] and result["asked"] == 0
    assert model.jobs == []
    assert not (out / es.FACTS_NAME).exists()


def test_the_owners_name_in_a_description_still_stops_the_run(out):
    # The generic redaction knows no name, so the scan is what protects it.
    write_items(out, [ad(1, description="Contact Zorana Testovic for details.")])
    model = Model()
    assert "privacy scan" in es.run(out, PROFILE, INTELLIGENCE, extract=model)["stopped"]
    assert model.jobs == []


def test_the_scan_result_names_kinds_never_the_matched_text(out):
    write_items(out, [ad(1, title="Zorana Testovic zorana.testovic@example.test")])
    leaks = es.plan(out, PROFILE, INTELLIGENCE)["leaks"]
    assert leaks and "zorana" not in json.dumps(leaks).lower()


# --- what is sent, stored and skipped -----------------------------------------------------


def test_the_model_gets_the_redacted_ad_and_the_facts_are_stored_in_the_calibration_folder_only(out):
    model = Model()
    result = es.run(out, PROFILE, INTELLIGENCE, extract=model)
    assert result == {"stopped": None, "asked": 3, "ok": 3, "failed": 0, "refused": 0}
    assert all("third-party.test" not in j["description"] for j in model.jobs)
    stored = json.loads((out / es.FACTS_NAME).read_text())
    assert set(stored["facts"]) == {"job1", "job2", "job3"}
    assert stat.S_IMODE((out / es.FACTS_NAME).stat().st_mode) == 0o600
    assert sorted(f.name for f in out.iterdir()) == sorted(["review-items.json", es.FACTS_NAME])


def test_a_second_run_skips_ads_with_valid_facts_and_asks_only_for_the_missing_ones(out):
    es.run(out, PROFILE, INTELLIGENCE, extract=Model(fail_on={"job2"}))
    again = Model()
    result = es.run(out, PROFILE, INTELLIGENCE, extract=again)
    assert result["asked"] == 1 and [j["jobId"] for j in again.jobs] == ["job2"]
    assert es.run(out, PROFILE, INTELLIGENCE, extract=Model())["asked"] == 0


def test_a_changed_ad_text_makes_stored_facts_stale(out):
    es.run(out, PROFILE, INTELLIGENCE, extract=Model())
    write_items(out, [ad(1, description="A different ad text."), ad(2), ad(3)])
    again = Model()
    assert es.run(out, PROFILE, INTELLIGENCE, extract=again)["asked"] == 1


def test_a_failed_call_is_counted_and_not_retried_inside_the_run(out):
    model = Model(fail_on={"job1"})
    result = es.run(out, PROFILE, INTELLIGENCE, extract=model)
    assert (result["ok"], result["failed"]) == (2, 1)
    assert [j["jobId"] for j in model.jobs].count("job1") == 1


def test_an_estimate_over_the_hard_stop_sends_nothing(out, monkeypatch):
    monkeypatch.setattr(es, "HARD_STOP_USD", 0.0000001)
    model = Model()
    assert "hard stop" in es.run(out, PROFILE, INTELLIGENCE, extract=model)["stopped"]
    assert model.jobs == []


def test_a_gate_refusal_sends_nothing(out, monkeypatch):
    monkeypatch.setattr(es, "preflight", lambda *a, **k: SimpleNamespace(allowed=False, reason="daily budget", row={}))
    monkeypatch.setattr(es.ai_gate, "record_refused", lambda *a, **k: None)
    model = Model()
    assert "AI gate refused" in es.run(out, PROFILE, INTELLIGENCE, extract=model)["stopped"]
    assert model.jobs == []


def test_the_runner_reads_and_writes_no_production_state(out, tmp_path):
    p = es.plan(out, PROFILE, INTELLIGENCE)
    assert p["store"].path.parent == out
    src = (es.ROOT / "python" / "calibration" / "enrich_sample.py").read_text()
    for production in ("usage-ledger", "scored_jobs", "discovered_jobs", "job_history", "requirement-frames"):
        assert production not in src
