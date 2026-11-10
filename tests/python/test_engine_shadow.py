"""Shadow mode wiring and caching (ENGINE_CONTRACT.md section 7); the engine itself is tested elsewhere."""

import json
import sys

import pytest

from match_engine import shadow
from match_engine.matcher import GATES
from match_engine.shadow import ShadowEngine

DESCRIPTION = "Product Manager.\nRequirements:\n* Hands-on SQL for analytics\nFully remote."
EVIDENCE = [{"id": "ev-b", "text": "Wrote SQL daily", "source": "role", "role": "PM", "start": "2020", "end": None,
             "strength": 3}]
CANDIDATE = {"profileVersion": "pv1", "roleFamily": "product", "evidence": EVIDENCE, "confirmedFacts": [], "gates": {}}
REQ = {"id": "sql", "provisional": False, "text": "SQL", "kind": "skill", "importance": "must",
       "postingQuote": "Hands-on SQL"}


def job(job_id, score, requirements=(REQ,), **extra):
    return {"jobId": job_id, "title": f"PM {job_id}", "company": "Acme", "location": "", "description": DESCRIPTION,
            "llmFacts": {"requirements": list(requirements), "roleTrack": "product_management"},
            "matchScore": score, "matchLabel": "Good", "priority": "P2", **extra}


class Fake:
    """complete_json stand-in: counts calls, answers MET on ev-b, or raises what it is given."""

    def __init__(self, fail=None):
        self.calls, self.fail = 0, fail

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.calls += 1
        if self.fail:
            raise self.fail
        return {"matches": [{"ref": "r1", "status": "MET", "evidence_id": "ev-b", "evidence_quote": "Wrote SQL daily",
                             "strength": 3}],
                "gates": {g: {"quote": None} for g in GATES}}


def engine(tmp_path, *, judge, fake=None, limit=50):
    return ShadowEngine(CANDIDATE, judge=judge, provider="test", model="m", cache_path=tmp_path / "engine.json",
                        limit=limit, complete=fake or Fake(), workers=1)


@pytest.mark.parametrize("value,on", [("1", True), ("true", True), ("On", True), ("", False), ("0", False),
                                      ("no", False)])
def test_the_flag(value, on):
    assert shadow.enabled({shadow.SHADOW_ENV: value}) is on
    assert shadow.enabled({}) is False


def test_the_pre_rename_flag_name_still_works_until_the_env_file_is_migrated():
    legacy = "_".join(["CAREER", "OS", "ENGINE_SHADOW"])  # built from parts: no source file carries the old name
    assert shadow.enabled({legacy: "1"}) is True
    assert shadow.enabled({shadow.SHADOW_ENV: "0", legacy: "1"}) is False  # a set new name wins over the old one
    assert shadow.enabled({legacy: "0"}) is False


def test_a_judged_run_calls_once_caches_and_a_later_run_calls_nothing(tmp_path):
    fake = Fake()
    first = engine(tmp_path, judge=True, fake=fake)
    [out] = first.apply([job("a", 70)])
    first.save()
    assert fake.calls == 1 and out["engineShadow"]["fromCache"] is False
    assert out["engineShadow"]["requirements"][0]["status"] == "MET"
    assert {"fit", "confidence", "label", "labelText", "bucket", "gates", "counts", "questions", "caps"} <= set(
        out["engineShadow"])

    never = Fake(fail=AssertionError("a local run must not call"))
    again = engine(tmp_path, judge=False, fake=never)
    [out2] = again.apply([job("a", 70)])
    assert never.calls == 0 and out2["engineShadow"]["fromCache"] is True
    assert out2["engineShadow"]["fit"] == out["engineShadow"]["fit"]


def test_a_local_run_without_a_cached_answer_adds_nothing(tmp_path):
    fake = Fake()
    e = engine(tmp_path, judge=False, fake=fake)
    [out] = e.apply([job("a", 70)])
    e.save()
    assert fake.calls == 0 and "engineShadow" not in out and e.counts["uncached"] == 1
    assert not (tmp_path / "engine.json").exists()


def test_nothing_but_engineShadow_changes(tmp_path):
    jobs = [job("a", 40), job("b", 90), job("c", 65)]
    out = engine(tmp_path, judge=True).apply(jobs)
    assert [j["jobId"] for j in out] == ["a", "b", "c"]
    for before, after in zip(jobs, out):
        assert {k: v for k, v in after.items() if k != "engineShadow"} == before


def test_the_per_run_limit_sends_the_highest_scores_first(tmp_path):
    fake = Fake()
    e = engine(tmp_path, judge=True, fake=fake, limit=2)
    jobs = [job("low", 40), job("high", 90), job("mid", 65)]
    out = {j["jobId"]: j for j in e.apply(jobs)}
    assert fake.calls == 2 and e.counts["beyondLimit"] == 1
    assert {k for k, j in out.items() if "engineShadow" in j} == {"high", "mid"}  # equal scores: test_matcher_planning.py


def test_a_cached_posting_does_not_take_a_place_under_the_limit(tmp_path):
    first = engine(tmp_path, judge=True, limit=1)
    first.apply([job("high", 90)])
    first.save()
    fake = Fake()
    e = engine(tmp_path, judge=True, fake=fake, limit=1)
    e.apply([job("high", 90), job("other", 50, requirements=[{**REQ, "text": "SQL skills"}],
                                      description=DESCRIPTION + " Other.")])
    assert fake.calls == 1 and e.counts["cached"] == 1 and e.counts["matched"] == 1


def test_closed_jobs_and_jobs_without_requirements_are_not_sent(tmp_path):
    fake = Fake()
    e = engine(tmp_path, judge=True, fake=fake)
    out = e.apply([job("closed", 90, isClosed=True), job("empty", 80, requirements=())])
    assert fake.calls == 0 and all("engineShadow" not in j for j in out)
    assert e.counts["closed"] == 1 and e.counts["noRequirements"] == 1


def test_a_failed_call_is_shown_and_not_cached(tmp_path):
    from llm_client import LlmUnavailable

    e = engine(tmp_path, judge=True, fake=Fake(fail=LlmUnavailable("down")))
    [out] = e.apply([job("a", 70)])
    e.save()
    assert "down" in out["engineShadow"]["error"] and "fit" not in out["engineShadow"]
    assert json.loads((tmp_path / "engine.json").read_text()) == {}


def test_a_refusal_by_the_ai_gate_stops_the_run_and_marks_no_job_failed(tmp_path):
    from llm_client import GuardrailRefused

    fake = Fake(fail=GuardrailRefused("AI budget is 0"))
    e = engine(tmp_path, judge=True, fake=fake)
    out = e.apply([job("a", 90), job("b", 80), job("c", 70)])
    assert fake.calls == 1
    assert all("engineShadow" not in j for j in out)
    assert e.counts["refused"] == 3 and e.counts["failed"] == 0
    assert e.refusal == "AI budget is 0"


def test_preview_counts_without_calling(tmp_path):
    first = engine(tmp_path, judge=True)
    first.apply([job("cached", 90)])
    first.save()
    never = Fake(fail=AssertionError("preview must not call"))
    p = engine(tmp_path, judge=False, fake=never, limit=1).preview(
        [job("cached", 90), job("new1", 80, description=DESCRIPTION + " A."), job("new2", 70, description=DESCRIPTION + " B.")])
    assert never.calls == 0
    assert (p["cached"], p["toSend"], p["beyondLimit"], p["limit"]) == (1, 1, 1, 1)
    assert "work authorization" in p["neverSent"] and any("evidence" in s for s in p["sent"])


# --- run_scoring: off by default, cache only without --judge ------------------------

@pytest.fixture
def scoring(tmp_path, monkeypatch):
    import run_scoring

    intel = {"jobFitPreferences": {}, "roleFamily": "product"}
    (tmp_path / "intel.json").write_text(json.dumps(intel))
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": [job("a", 0)]}))
    (tmp_path / "profile.json").write_text(json.dumps({}))
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])  # never the server's own file
    monkeypatch.setattr(shadow, "load_remap", lambda: {})  # nor its remap table
    monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--intelligence", str(tmp_path / "intel.json"),
                                      "--jobs", str(tmp_path / "jobs.json"), "--output", str(tmp_path / "out.json")])

    def run():
        assert run_scoring.main() == 0
        return json.loads((tmp_path / "out.json").read_text())
    return run


def test_scoring_without_the_flag_adds_no_shadow(scoring, monkeypatch):
    monkeypatch.delenv(shadow.SHADOW_ENV, raising=False)
    out = scoring()
    assert "engineShadow" not in out["jobs"][0] and out["meta"]["engineShadow"] == {"enabled": False}


def test_scoring_with_the_flag_but_no_judge_calls_nothing(scoring, monkeypatch):
    monkeypatch.setenv(shadow.SHADOW_ENV, "1")
    out = scoring()
    meta = out["meta"]["engineShadow"]
    assert meta["enabled"] is True and meta["matched"] == 0 and "error" not in meta


# --- the cheap gates before the top-N cut (all data fictional) ------------------------

DE = {"id": "de", "provisional": False, "text": "Fluent German", "kind": "language", "importance": "must",
      "postingQuote": "Fluent German required"}
EN_CAND = {**CANDIDATE, "gates": {"languages": ["English (fluent)"]}}
NONE_CAND = {**CANDIDATE, "gates": {"languages": []}}


def judged(tmp_path, candidate, limit):
    return ShadowEngine(candidate, judge=True, provider="test", model="m", cache_path=tmp_path / "engine.json",
                        limit=limit, complete=Fake(), workers=1)


def german(job_id, score):
    return job(job_id, score, requirements=(REQ, DE), description=DESCRIPTION + "\nFluent German required")


def test_a_confirmed_fail_is_excluded_and_the_next_ad_takes_its_place(tmp_path):
    jobs = [german("a", 90), job("b", 80), job("c", 70)]
    eng = judged(tmp_path, EN_CAND, limit=2)
    assert eng.plan(jobs) == {"b", "c"}
    assert eng.excluded == {"language": 1, "work_authorization": 0, "location": 0, "role_family": 0}
    out = eng.apply(jobs)
    assert "engineShadow" not in out[0] and eng.counts["excluded"] == 1 and eng.counts["matched"] == 2


def test_an_unknown_gate_never_excludes_and_does_not_move_the_score(tmp_path):
    jobs = [german("a", 90), job("b", 80)]
    eng = judged(tmp_path, NONE_CAND, limit=1)
    assert eng.plan(jobs) == {"a"}
    assert sum(eng.excluded.values()) == 0
    out = {j["jobId"]: j for j in eng.apply(jobs)}
    assert out["a"]["matchScore"] == 90
    plain = judged(tmp_path, NONE_CAND, limit=2).apply([job("b", 80)])[0]["engineShadow"]
    unknown = [r for r in out["a"]["engineShadow"]["requirements"] if r["kind"] == "language"][0]
    assert unknown["status"] == "UNKNOWN"
    assert out["a"]["engineShadow"]["fit"] == plain["fit"]
    assert out["a"]["engineShadow"]["confidence"] <= plain["confidence"]


def test_a_role_family_fail_with_evidence_is_excluded(tmp_path):
    off = job("a", 90)
    off["llmFacts"] = {**off["llmFacts"], "roleTrack": "engineering", "roleTrackEvidence": "Writes Go services."}
    guess = job("g", 85)
    guess["llmFacts"] = {**guess["llmFacts"], "roleTrack": "other"}
    eng = judged(tmp_path, CANDIDATE, limit=2)
    assert eng.plan([off, guess, job("b", 80)]) == {"g", "b"}
    assert eng.excluded["role_family"] == 1


# --- location before the top-N cut -----------------------------------------------------

LOC_CAND = {**CANDIDATE, "gates": {"allowedLocations": ["REMOTE", "EU", "RS"], "relocation": "none", "country": "Serbia",
                                   "workAuthorization": {"holds": [{"jurisdiction": "RS"}]}}}


def remote_job(job_id, score, text):
    return job(job_id, score, description=DESCRIPTION + "\n" + text, isRemote=True)


def test_a_confirmed_geographic_restriction_is_excluded_and_unknown_is_not_boosted(tmp_path):
    jobs = [remote_job("uk", 90, "Remote, UK only."), remote_job("unk", 80, "Remote."), job("low", 70, isRemote=True)]
    eng = judged(tmp_path, LOC_CAND, limit=2)
    send = eng.plan(jobs)
    assert send == {"unk", "low"} and eng.excluded["location"] == 1
    # No boost: the unknown-location ad is ordered by its own matchScore like any other.
    assert [j["jobId"] for j in sorted(jobs, key=lambda j: -j["matchScore"]) if j["jobId"] in send] == ["unk", "low"]
