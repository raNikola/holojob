"""Matcher cache key, remap on read, the top-N order and planning on the local score (all data fictional)."""

import json
from pathlib import Path

from job_fingerprint import job_fingerprint
from match_engine import shadow
from match_engine.matcher import GATES, KEY_VERSION, cache_key, posting_from_job, requirements_hash
from match_engine.shadow import ShadowEngine, local_score
from requirement_frames import apply_remap, remap_facts, remap_requirements

NO_CACHE = Path("/nonexistent/engine.json")
BODY = "Product Manager.\nRequirements:\n* Hands-on SQL for analytics\n* Roadmaps\n"
EVIDENCE = [{"id": "ev-b", "text": "Wrote SQL daily", "source": "role", "role": "PM", "start": "2020", "end": None,
             "strength": 3}]
CANDIDATE = {"profileVersion": "pv1", "roleFamily": "product", "evidence": EVIDENCE, "confirmedFacts": [], "gates": {}}
LOC_CANDIDATE = {**CANDIDATE, "gates": {"allowedLocations": ["REMOTE", "EU", "RS"], "relocation": "abroad",
                                        "country": "Serbia", "workAuthorization": {"holds": [{"jurisdiction": "RS"}]}}}
SQL = {"id": "sql", "provisional": False, "text": "SQL", "kind": "skill", "importance": "must",
       "postingQuote": "Hands-on SQL"}
ROADMAP = {"id": "roadmapping", "provisional": False, "text": "Roadmaps", "kind": "skill", "importance": "must",
           "postingQuote": "Roadmaps"}
PROV = {"id": "prov:0123456789ab", "provisional": True, "text": "Roadmaps", "kind": "skill", "importance": "must",
        "postingQuote": "Roadmaps"}


def job(job_id, score, requirements=(SQL,), description=BODY, **extra):
    return {"jobId": job_id, "title": f"PM {job_id}", "company": "Acme", "location": "", "description": description,
            "llmFacts": {"requirements": list(requirements), "roleTrack": "product_management"},
            "matchScore": score, "matchLabel": "Good", "priority": "P2", **extra}


class Fake:
    def __init__(self, fail=None):
        self.calls, self.fail = 0, fail

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.calls += 1
        if self.fail:
            raise self.fail
        return {"matches": [{"ref": f"r{i}", "status": "MET", "evidence_id": "ev-b",
                             "evidence_quote": "Wrote SQL daily", "strength": 3} for i in (1, 2)
                            if f"r{i}" in prompt],
                "gates": {g: {"quote": None} for g in GATES}}


def engine(tmp_path, *, candidate=CANDIDATE, limit=50, fake=None, remap=None, judge=True):
    return ShadowEngine(candidate, judge=judge, provider="test", model="m", cache_path=tmp_path / "engine.json",
                        limit=limit, complete=fake or Fake(), workers=1, remap={} if remap is None else remap)


# --- 1. the cache key covers the requirement set ----------------------------------------

def test_the_requirement_hash_ignores_order_and_whitespace_and_sees_every_asked_field():
    base = requirements_hash([SQL, ROADMAP])
    assert base == requirements_hash([ROADMAP, SQL])
    assert requirements_hash([SQL]) == requirements_hash([{**SQL, "text": "  SQL  "}])
    for change in ({"id": "postgres"}, {"text": "SQL for analytics"}, {"importance": "nice"}, {"kind": "domain"},
                   {"postingQuote": "SQL"}):
        assert requirements_hash([{**SQL, **change}]) != requirements_hash([SQL]), change
    assert requirements_hash([SQL]) != requirements_hash([SQL, SQL]) != requirements_hash([])
    assert requirements_hash(None) == requirements_hash([])


def test_the_key_carries_the_requirement_hash_and_a_version_old_keys_lack():
    key = cache_key("ad", "pv", None, [SQL])
    assert key == f"ad:pv:{key.split(':')[2]}:{KEY_VERSION}-{requirements_hash([SQL])}"
    assert key != cache_key("ad", "pv", None, [SQL, ROADMAP]) != cache_key("ad", "pv")
    assert cache_key("ad", "pv", None, [SQL, ROADMAP]) == cache_key("ad", "pv", None, [ROADMAP, SQL])
    assert f":{KEY_VERSION}-" not in "ad:pv:extract-4.match-2"


def test_a_result_is_never_returned_for_a_changed_requirement_set(tmp_path):
    fake = Fake()
    first = engine(tmp_path, fake=fake)
    [out] = first.apply([job("a", 70)])
    first.save()
    assert fake.calls == 1 and [r["id"] for r in out["engineShadow"]["requirements"]] == ["sql"]

    same = Fake(fail=AssertionError("same requirements: no call"))
    [again] = engine(tmp_path, fake=same).apply([job("a", 70)])
    assert same.calls == 0 and again["engineShadow"]["fromCache"] is True

    changed = Fake()
    eng = engine(tmp_path, fake=changed)
    [new] = eng.apply([job("a", 70, requirements=(SQL, ROADMAP))])
    assert changed.calls == 1 and new["engineShadow"]["fromCache"] is False
    assert [r["id"] for r in new["engineShadow"]["requirements"]] == ["sql", "roadmapping"]
    retext = Fake()
    [fresh] = engine(tmp_path, fake=retext).apply([job("a", 70, requirements=({**SQL, "text": "SQL and BI"},))])
    assert retext.calls == 1 and fresh["engineShadow"]["requirements"][0]["text"] == "SQL and BI"


def test_an_entry_under_the_old_key_format_is_a_miss(tmp_path):
    eng = engine(tmp_path)
    posting = posting_from_job(job("a", 70))
    old_key = f"{job_fingerprint(posting)}:pv1:{eng._cache_key(posting).split(':')[2]}"
    (tmp_path / "engine.json").write_text(json.dumps({old_key: {"requirements": [{"id": "stale"}], "gates": []}}))
    fake = Fake()
    [out] = engine(tmp_path, fake=fake).apply([job("a", 70)])
    assert fake.calls == 1 and [r["id"] for r in out["engineShadow"]["requirements"]] == ["sql"]


# --- 2. remap on read ---------------------------------------------------------------------

REMAP = {PROV["id"]: "roadmapping"}


def test_remap_replaces_a_provisional_id_once_and_is_idempotent():
    original = [SQL, PROV]
    snapshot = json.loads(json.dumps(original))
    out = remap_requirements(original, REMAP)
    assert [r["id"] for r in out] == ["sql", "roadmapping"] and out[1]["provisional"] is False
    assert out[1]["text"] == PROV["text"] and out[0] is SQL
    assert original == snapshot, "the input is not changed"
    assert remap_requirements(out, REMAP) == out
    assert remap_requirements(original, None) == original and remap_requirements(original, {}) == original


def test_remap_agrees_with_the_frames():
    frames = {"k": [{"id": PROV["id"], "text": "Roadmaps", "kind": "skill", "importance": "must"}]}
    apply_remap(frames, REMAP)
    facts = remap_facts({"requirements": [PROV], "roleTrack": "x"}, REMAP)
    assert [r["id"] for r in facts["requirements"]] == [f["id"] for f in frames["k"]] == ["roadmapping"]
    assert facts["roleTrack"] == "x"
    assert remap_facts({}, REMAP) == {}


def test_the_posting_is_read_through_the_remap_and_the_job_is_untouched():
    j = job("a", 70, requirements=(SQL, PROV))
    before = json.loads(json.dumps(j))
    assert [r["id"] for r in posting_from_job(j, REMAP)["facts"]["requirements"]] == ["sql", "roadmapping"]
    assert [r["id"] for r in posting_from_job(j)["facts"]["requirements"]] == ["sql", PROV["id"]]
    assert j == before


def test_a_remapped_ad_has_the_key_and_result_of_the_canonical_ad(tmp_path):
    fake = Fake()
    eng = engine(tmp_path, fake=fake, remap=REMAP)
    [out] = eng.apply([job("a", 70, requirements=(SQL, PROV))])
    eng.save()
    assert [r["id"] for r in out["engineShadow"]["requirements"]] == ["sql", "roadmapping"]
    [canonical] = engine(tmp_path, fake=Fake(fail=AssertionError("no call")), remap={}).apply(
        [job("a", 70, requirements=(SQL, ROADMAP))])
    assert canonical["engineShadow"]["fromCache"] is True
    assert canonical["engineShadow"]["cacheKey"] == out["engineShadow"]["cacheKey"]


def test_the_engine_loads_the_remap_table_when_none_is_given(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, "load_remap", lambda: REMAP)
    eng = ShadowEngine(CANDIDATE, judge=False, provider="t", model="m", cache_path=tmp_path / "e.json")
    assert eng.remap == REMAP
    assert not (tmp_path / "e.json").exists()


# --- 4. the order of the top N ------------------------------------------------------------

def shuffled(jobs):
    return [jobs[i] for i in (2, 0, 3, 1) if i < len(jobs)]


def test_equal_scores_prefer_a_passed_location_gate():
    # Serbia stated: pass; "Remote." alone: unknown.
    passed = job("pass", 70, description=BODY + "Remote. Open to candidates in Serbia.", isRemote=True)
    unknown = job("unknown", 70, description=BODY + "Remote.", isRemote=True)
    for jobs in ([unknown, passed], [passed, unknown]):
        assert engine_plan(LOC_CANDIDATE, jobs, limit=1) == {"pass"}


def engine_plan(candidate, jobs, limit):
    # A cache path that does not exist: plan() only reads it, and nothing is saved.
    return ShadowEngine(candidate, judge=True, provider="t", model="m", cache_path=NO_CACHE, limit=limit,
                        complete=Fake(), workers=1, remap={}).plan(jobs)


def test_then_fewer_provisional_requirements():
    many = job("many", 70, requirements=(SQL, PROV, {**PROV, "id": "prov:111111111111", "text": "Roadmaps 2"}))
    few = job("few", 70, requirements=(SQL, PROV), description=BODY + " ")
    for jobs in ([many, few], [few, many]):
        assert engine_plan(CANDIDATE, jobs, limit=1) == {"few"}


def test_then_the_newer_posting_and_an_unreadable_date_is_oldest():
    new = job("new", 70, datePosted="2026-10-24", description=BODY + "a")
    old = job("old", 70, datePosted="2026-10-01T10:00:00+00:00", description=BODY + "b")
    none = job("none", 70, description=BODY + "c")
    junk = job("junk", 70, datePosted="soon", description=BODY + "d")
    for jobs in ([none, junk, old, new], [new, old, junk, none]):
        assert engine_plan(CANDIDATE, jobs, limit=1) == {"new"}
        assert engine_plan(CANDIDATE, jobs, limit=2) == {"new", "old"}


def test_then_the_fingerprint_so_the_order_of_the_list_never_matters():
    jobs = [job(c, 70, description=BODY + c) for c in "abcd"]
    expected = sorted(jobs, key=lambda j: job_fingerprint(posting_from_job(j)))[0]["jobId"]
    for order in (jobs, list(reversed(jobs)), shuffled(jobs)):
        assert engine_plan(CANDIDATE, order, limit=1) == {expected}


def test_the_score_still_comes_first():
    better = job("better", 71, description=BODY + "x")
    pass_loc = job("pass", 70, description=BODY + "Remote. Open to candidates in Serbia.", isRemote=True,
                   datePosted="2026-10-24")
    assert engine_plan(LOC_CANDIDATE, [pass_loc, better], limit=1) == {"better"}


# --- 5. planning on the local score ---------------------------------------------------------

def test_local_score_is_the_score_before_the_judge():
    assert local_score({"matchScore": 90, "llmFit": {"localScore": 60, "adjustment": 30}}) == 60
    assert local_score({"matchScore": 70}) == 70
    assert local_score({"matchScore": 70, "llmFit": {"error": "timeout"}}) == 70
    assert local_score({"matchScore": 70, "llmFit": {"localScore": True}}) == 70
    assert local_score({}) == 0


def test_a_judge_verdict_does_not_move_an_ad_in_or_out_of_the_top_n():
    raised = job("raised", 90, llmFit={"fit": "strong", "localScore": 60, "adjustment": 30}, description=BODY + "r")
    lowered = job("lowered", 55, llmFit={"fit": "poor", "localScore": 80, "adjustment": -25}, description=BODY + "l")
    plain = job("plain", 70, description=BODY + "p")
    for jobs in ([raised, lowered, plain], [plain, lowered, raised]):
        assert engine_plan(CANDIDATE, jobs, limit=2) == {"lowered", "plain"}
        assert engine_plan(CANDIDATE, jobs, limit=1) == {"lowered"}


def test_planning_on_the_local_score_makes_no_call(tmp_path):
    fake = Fake(fail=AssertionError("planning must not call"))
    eng = engine(tmp_path, fake=fake, limit=1)
    jobs = [job("a", 90, llmFit={"localScore": 50}), job("b", 60, description=BODY + "b")]
    assert eng.plan(jobs) == {"b"} and fake.calls == 0
    assert not (tmp_path / "engine.json").exists()
