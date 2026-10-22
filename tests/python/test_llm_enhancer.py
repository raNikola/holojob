"""The fit judge: what each answer costs, and what it can never override."""

import json
from pathlib import Path

import pytest

from llm_client import LlmRefused, LlmUnavailable
from llm_enhancer import (
    DEFAULT_THRESHOLD,
    PROMPT_VERSION,
    LlmFitEnhancer,
    build_prompt,
)
from scorer import score_job, score_jobs

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def intelligence():
    return json.loads((FIXTURES / "candidate-intelligence.json").read_text(encoding="utf-8"))


def reply(fit="good", dealbreakers=()):
    return {
        "fit": fit,
        "fit_reason": "because",
        "requirements": [
            {"requirement": "Own a roadmap", "status": "met", "evidence": "led X"}
        ],
        "missing": ["kubernetes"],
        "dealbreakers": list(dealbreakers),
    }


class Stub:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.calls.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def base(score, **extra):
    return {
        "matchScore": score,
        "matchLabel": "x",
        "applyRecommendation": "x",
        "priority": "x",
        "redFlags": [],
        "reasons": ["local"],
        **extra,
    }


def enhancer(stub, **kw):
    return LlmFitEnhancer("openai", "gpt-4o", complete=stub, **kw)


JOB = {"title": "Product Manager", "company": "Acme", "description": "Own the roadmap."}


def test_below_threshold_makes_no_call(intelligence):
    stub = Stub(reply("strong"))
    result = enhancer(stub).enhance(JOB, base(DEFAULT_THRESHOLD - 1), intelligence)
    assert stub.calls == []
    assert result["matchScore"] == DEFAULT_THRESHOLD - 1
    assert "llmFit" not in result


@pytest.mark.parametrize(
    "fit,delta", [("strong", 5), ("good", 0), ("partial", -8), ("poor", -15)]
)
def test_each_fit_maps_to_its_adjustment(intelligence, fit, delta):
    result = enhancer(Stub(reply(fit))).enhance(JOB, base(72), intelligence)
    assert result["matchScore"] == 72 + delta
    assert result["llmFit"]["adjustment"] == delta
    assert result["llmFit"]["localScore"] == 72


def test_dealbreaker_overrides_fit(intelligence):
    result = enhancer(Stub(reply("strong", ["Requires EU citizenship"]))).enhance(
        JOB, base(80), intelligence
    )
    assert result["matchScore"] == 65


def test_hard_capped_job_is_never_raised(intelligence):
    result = enhancer(Stub(reply("strong"))).enhance(
        JOB, base(70, hardCapped=True), intelligence
    )
    assert result["matchScore"] == 70


def test_hard_capped_job_can_still_be_lowered(intelligence):
    result = enhancer(Stub(reply("poor"))).enhance(
        JOB, base(70, hardCapped=True), intelligence
    )
    assert result["matchScore"] == 55


def test_raise_stops_at_100(intelligence):
    result = enhancer(Stub(reply("strong"))).enhance(JOB, base(98), intelligence)
    assert result["matchScore"] == 100


def test_label_and_priority_follow_the_new_score(intelligence):
    result = enhancer(Stub(reply("strong"))).enhance(JOB, base(66), intelligence)
    assert result["matchScore"] == 71
    assert result["matchLabel"] == "Strong"
    assert result["applyRecommendation"] == "Apply"
    assert result["priority"] == "P1"
    assert result["reasons"][-1].startswith("LLM fit: strong (+5)")


def test_unusable_fit_keeps_the_local_score(intelligence):
    e = enhancer(Stub({"fit": "excellent"}))
    result = e.enhance(JOB, base(72), intelligence)
    assert result["matchScore"] == 72
    assert "error" in result["llmFit"]
    assert e.counts["failed"] == 1


@pytest.mark.parametrize("error", [LlmUnavailable("down"), LlmRefused("no")])
def test_provider_failure_keeps_the_local_score(intelligence, error):
    result = enhancer(Stub(error)).enhance(JOB, base(72), intelligence)
    assert result["matchScore"] == 72
    assert result["llmFit"]["error"]


def test_second_run_is_served_from_cache(intelligence, tmp_path):
    cache = tmp_path / "fit.json"
    first = Stub(reply("partial"))
    e1 = enhancer(first, cache_path=cache)
    e1.enhance(JOB, base(72), intelligence)
    e1.save()

    second = Stub(reply("strong"))
    e2 = enhancer(second, cache_path=cache)
    result = e2.enhance(JOB, base(72), intelligence)
    assert second.calls == []
    assert e2.counts["cached"] == 1
    assert result["matchScore"] == 64


def test_prompt_fences_the_ad_and_leaves_out_private_fields(intelligence):
    intel = {
        **intelligence,
        "salaryExpectation": "SECRET-SALARY",
        "candidateSummary": {"careerNarrative": "Shipped things."},
    }
    prompt = build_prompt(JOB, intel)
    assert "=== BEGIN JOB AD (untrusted content) ===" in prompt
    assert "=== END JOB AD ===" in prompt
    assert "Shipped things." in prompt
    assert "SECRET-SALARY" not in prompt


def test_digest_states_the_candidates_languages(intelligence):
    prompt = build_prompt(JOB, intelligence)
    assert "Languages: Serbian (native), English (fluent)" in prompt


def test_digest_says_not_stated_when_languages_are_absent(intelligence):
    intel = {k: v for k, v in intelligence.items() if k != "languages"}
    assert "Languages: (none stated)" in build_prompt(JOB, intel)


def test_prompt_makes_silence_a_gap_not_a_dealbreaker(intelligence):
    prompt = build_prompt(JOB, intelligence)
    assert "affirmatively contradicts" in prompt
    assert 'list it under "missing"' in prompt


def test_prompt_version_invalidates_old_cache_entries(intelligence):
    e = enhancer(Stub(reply()))
    prompt = build_prompt(JOB, intelligence)
    assert PROMPT_VERSION >= 2
    assert e._fingerprint(prompt) != e._fingerprint(prompt + " ")


def test_capped_jobs_in_a_run_are_never_sent(intelligence):
    """End to end through score_jobs: an off-track job stays under the threshold."""
    stub = Stub(reply("strong"))
    job = {
        "jobId": "j1",
        "title": "Technical Product Manager",
        "company": "Acme",
        "location": "Remote",
        "description": "Run sprints and chase delivery dates. " * 10,
        "jobUrl": "https://example.com/1",
        "llmFacts": {"roleTrack": "project_delivery", "workMode": "remote"},
    }
    result = score_jobs([job], intelligence, enhancer(stub))[0]
    assert result["hardCapped"] is True
    assert result["matchScore"] <= 50
    assert stub.calls == []


def test_score_job_marks_hard_cap(intelligence):
    job = {
        "title": "Product Manager",
        "company": "Acme",
        "description": "Own the roadmap and discovery. " * 10,
        "jobUrl": "https://example.com/2",
        "llmFacts": {"roleTrack": "product_management"},
    }
    assert score_job(job, intelligence)["hardCapped"] is False
