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
    result = enhancer(Stub(reply("strong"))).enhance(JOB, base(72), intelligence)
    assert result["matchScore"] == 77
    assert result["matchLabel"] == "Strong"
    assert result["applyRecommendation"] == "Apply"
    assert result["priority"] == "P1"
    # A raise into Apply that stays under the P1 line is P2.
    raised = enhancer(Stub(reply("strong"))).enhance(JOB, base(66), intelligence)
    assert (raised["matchScore"], raised["applyRecommendation"], raised["priority"]) == (71, "Apply", "P2")
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
        "jobFitPreferences": {**intelligence.get("jobFitPreferences", {}), "minSalaryEur": 7777, "desiredSalaryEur": {"min": 8888, "max": 9999}},
        "candidateSummary": {"careerNarrative": "Shipped things."},
    }
    prompt = build_prompt(JOB, intel)
    assert "=== BEGIN JOB AD (untrusted content) ===" in prompt
    assert "=== END JOB AD ===" in prompt
    assert "Shipped things." in prompt
    assert "SECRET-SALARY" not in prompt
    assert not any(n in prompt for n in ("7777", "8888", "9999"))


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


# --- cache-only re-application (local re-score) -------------------------------------------------


def test_cache_only_reapplies_a_stored_judgement_without_calling(intelligence, tmp_path):
    cache = tmp_path / "fit.json"
    first = enhancer(Stub(reply("partial")), cache_path=cache)
    first.enhance(JOB, base(80), intelligence)
    first.save()

    never = Stub(AssertionError("called the model"))
    local = enhancer(never, cache_path=cache, cache_only=True)
    result = local.enhance(JOB, base(80), intelligence)
    assert never.calls == []
    assert result["matchScore"] == 72 and result["llmFit"]["fromCache"] is True
    assert local.counts["cached"] == 1


def test_cache_only_leaves_an_unjudged_job_at_its_local_score(intelligence, tmp_path):
    never = Stub(AssertionError("called the model"))
    local = enhancer(never, cache_path=tmp_path / "missing.json", cache_only=True)
    result = local.enhance(JOB, base(80), intelligence)
    assert never.calls == [] and result == base(80) and local.counts["uncached"] == 1


def test_cache_only_never_writes_the_cache(intelligence, tmp_path):
    cache = tmp_path / "fit.json"
    enhancer(Stub(None), cache_path=cache, cache_only=True).save()
    assert not cache.exists()


def test_a_fresh_judgement_is_not_marked_from_cache(intelligence):
    result = enhancer(Stub(reply("good"))).enhance(JOB, base(80), intelligence)
    assert result["llmFit"]["fromCache"] is False


# --- what the UI shows before a judged run ------------------------------------------------------


def test_the_listed_digest_fields_are_exactly_what_the_digest_writes(intelligence):
    from llm_enhancer import DIGEST_FIELDS, _candidate_digest

    labels = []
    for line in _candidate_digest(intelligence).splitlines():
        if line.startswith("- "):
            continue
        for part in line.split(". "):
            if ":" in part:
                labels.append(part.split(":", 1)[0].strip())
    assert labels == DIGEST_FIELDS


def test_preview_reports_counts_and_writes_nothing(intelligence, tmp_path, monkeypatch, capsys):
    import run_scoring

    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [JOB]}), encoding="utf-8")
    intel = tmp_path / "intel.json"
    intel.write_text(json.dumps(intelligence), encoding="utf-8")
    out = tmp_path / "scored.json"
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "fit.json")
    monkeypatch.setattr(run_scoring, "score_jobs", lambda j, i, e, workers: [e.enhance(j[0], base(80), i)])
    monkeypatch.setattr("sys.argv", ["run_scoring.py", "--judge-preview", "--judge-provider", "openai",
                                     "--jobs", str(jobs), "--intelligence", str(intel), "--output", str(out)])
    assert run_scoring.main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["provider"] == "openai" and preview["leavesServer"] is True
    assert (preview["eligible"], preview["cached"], preview["toSend"]) == (1, 0, 1)
    assert "Name" in preview["neverSent"] and not out.exists()


# --- the per-run judge cap -----------------------------------------------------------------------


def scored(scores):
    return [base(s, jobId=f"j{i}") for i, s in enumerate(scores)]


def job_of(result):
    return {**JOB, "jobId": result["jobId"], "title": f"Role {result['jobId']}"}


def run_all(enh, results, intelligence):
    enh.select(results)
    return [enh.enhance(job_of(r), r, intelligence) for r in results]


def test_only_the_top_scoring_jobs_up_to_the_limit_are_sent(intelligence):
    stub = Stub(reply("good"))
    results = scored([70, 90, 66, 80, 75, 60])  # 60 is below the threshold
    out = run_all(enhancer(stub, limit=3), results, intelligence)
    judged = [r["jobId"] for r in out if "llmFit" in r]
    assert sorted(judged) == ["j1", "j3", "j4"]  # 90, 80, 75
    assert len(stub.calls) == 3
    # The rest keep their local score and are counted as beyond the limit.
    assert [r["matchScore"] for r in out if "llmFit" not in r] == [70, 66, 60]


def test_equal_scores_at_the_cutoff_keep_input_order(intelligence):
    stub = Stub(reply("good"))
    results = scored([80, 80, 80, 80])
    out = run_all(enhancer(stub, limit=2), results, intelligence)
    assert [r["jobId"] for r in out if "llmFit" in r] == ["j0", "j1"]


def test_no_limit_judges_everything_at_or_above_the_threshold(intelligence):
    stub = Stub(reply("good"))
    out = run_all(enhancer(stub), scored([70, 90, 66, 60]), intelligence)
    assert sum("llmFit" in r for r in out) == 3 and len(stub.calls) == 3


def test_a_cached_judgement_outside_the_top_is_still_applied_for_free(intelligence, tmp_path):
    cache = tmp_path / "fit.json"
    results = scored([90, 70])
    first = enhancer(Stub(reply("partial")), cache_path=cache)  # judges both, saves both
    run_all(first, results, intelligence)
    first.save()

    stub = Stub(AssertionError("called the model"))
    again = enhancer(stub, cache_path=cache, limit=1)  # only j0 may be sent
    out = run_all(again, results, intelligence)
    assert stub.calls == []
    assert all("llmFit" in r and r["llmFit"]["fromCache"] for r in out)
    assert again.counts["cached"] == 2 and again.counts["beyond_limit"] == 0


def test_counts_separate_new_calls_cache_and_beyond_the_limit(intelligence):
    enh = enhancer(Stub(reply("good")), limit=2)
    run_all(enh, scored([95, 90, 85, 70, 50]), intelligence)
    assert enh.counts["judged"] == 2 and enh.counts["beyond_limit"] == 2 and enh.counts["skipped"] == 1


def test_the_cap_never_stops_a_job_from_being_scored(intelligence, monkeypatch):
    import scorer

    jobs = [{"jobId": f"j{i}", "title": "PM", "description": f"Own roadmap {i}. " * 5, "s": s}
            for i, s in enumerate([95, 90, 85, 80, 75, 70])]
    monkeypatch.setattr(scorer, "score_job", lambda j, i, e=None, idf=None: base(j["s"], jobId=j["jobId"]))
    stub = Stub(reply("good"))
    out = scorer.score_jobs(jobs, intelligence, enhancer(stub, limit=2))
    assert len(out) == 6 and len(stub.calls) == 2
    assert [r["jobId"] for r in out] == [j["jobId"] for j in jobs]


def test_run_summary_reports_scored_versus_judged(intelligence, tmp_path, monkeypatch, capsys):
    import run_scoring

    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [JOB]}), encoding="utf-8")
    intel = tmp_path / "intel.json"
    intel.write_text(json.dumps(intelligence), encoding="utf-8")
    out = tmp_path / "scored.json"
    stub = Stub(reply("good"))
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "fit.json")
    monkeypatch.setattr(run_scoring, "ROOT", tmp_path)
    monkeypatch.setattr(
        run_scoring, "LlmFitEnhancer",
        lambda *a, **kw: LlmFitEnhancer(*a, **{**kw, "complete": stub}),
    )
    only = {**JOB, "jobId": "a"}
    monkeypatch.setattr(run_scoring, "score_jobs", lambda j, i, e, workers: (e.select([base(80, jobId="a")]), [e.enhance(only, base(80, jobId="a"), i)])[1])
    monkeypatch.setattr("sys.argv", ["run_scoring.py", "--judge", "--judge-provider", "openai", "--judge-limit", "7",
                                     "--jobs", str(jobs), "--intelligence", str(intel), "--output", str(out)])
    assert run_scoring.main() == 0
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("judge: scored")][0]
    assert "scored 1 jobs, judged 1 (1 new calls, 0 from cache)" in line and "top 7" in line
    meta = json.loads(out.read_text())["meta"]["judge"]
    assert (meta["scored"], meta["judged"], meta["limit"]) == (1, 1, 7)


def test_preview_counts_only_what_the_cap_would_send(intelligence, tmp_path, monkeypatch, capsys):
    import run_scoring

    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [JOB]}), encoding="utf-8")
    intel = tmp_path / "intel.json"
    intel.write_text(json.dumps(intelligence), encoding="utf-8")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "fit.json")
    results = [base(s, jobId=f"p{i}") for i, s in enumerate([90, 85, 80, 70, 30])]
    monkeypatch.setattr(run_scoring, "score_jobs", lambda j, i, e, workers: (e.select(results), [e.enhance(job_of(r), r, i) for r in results])[1])
    monkeypatch.setattr("sys.argv", ["run_scoring.py", "--judge-preview", "--judge-provider", "openai", "--judge-limit", "2",
                                     "--jobs", str(jobs), "--intelligence", str(intel), "--output", str(tmp_path / "o.json")])
    assert run_scoring.main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert (preview["limit"], preview["eligible"], preview["toSend"], preview["beyondLimit"], preview["cached"]) == (2, 4, 2, 2, 0)


def test_a_closed_job_is_never_sent_to_the_judge(intelligence):
    stub = Stub(reply("strong"))
    results = [base(90, jobId="open"), base(95, jobId="gone", isClosed=True)]
    out = run_all(enhancer(stub, limit=1), results, intelligence)
    assert [r["jobId"] for r in out if "llmFit" in r] == ["open"] and len(stub.calls) == 1
    unlimited = enhancer(Stub(reply("strong")))
    run_all(unlimited, results, intelligence)
    assert unlimited.counts["closed"] == 1 and unlimited.counts["judged"] == 1
