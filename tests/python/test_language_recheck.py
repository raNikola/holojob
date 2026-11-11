"""languagesVersion and a language list that changed (ENGINE_CONTRACT.md 6.1); fakes only, no provider call."""

import copy

from match_engine.matcher import match_posting, posting_from_job
from match_engine.shadow import ShadowEngine
from test_version_split import INTELLIGENCE, SKILL, _candidate, _model, _no_call, _req

DE_REQ = {"id": "prov:bbbbbbbbbbbb", "provisional": False, "text": "German", "kind": "language",
          "importance": "preferred", "postingQuote": "German"}
DE_JOB = {"jobId": "d", "title": "PM", "company": "Co", "location": "Remote", "matchScore": 80,
          "description": "SQL. German is a plus.", "llmFacts": {"requirements": [_req("sql", "SQL"), DE_REQ]}}
DE_POSTING = posting_from_job(DE_JOB, {})
DE_PROFILE = {"basicProfile": {}, "resume": {"parsedData": {"skills": [SKILL, "German"]}}}


def _de(languages):
    return _candidate(profile=DE_PROFILE, intelligence={**INTELLIGENCE, "languages": languages})


def _match(candidate, complete, cache):
    return match_posting(DE_POSTING, candidate, confirmed=True, provider="test", complete=complete, cache=cache)


def _german(output):
    return next(r for r in output["requirements"] if r["id"] == DE_REQ["id"])


def _seeded():
    cache = {}
    candidate = _de(["German (C1)"])
    assert _german(_match(candidate, _model(candidate), cache).output)["status"] == "MET"
    return cache


def test_a_language_change_moves_languages_version_and_not_evidence_version():
    a, b = _de(["German (C1)"]), _de(["English (fluent)"])
    assert a["evidenceVersion"] == b["evidenceVersion"]
    assert a["languagesVersion"] != b["languagesVersion"]
    both = _de(["German (C1)", "English (fluent)"])["languagesVersion"]
    assert both == _de(["english (fluent)", "German (C1)"])["languagesVersion"]
    assert _de(["German (C1)"])["languagesVersion"] == a["languagesVersion"]


def test_a_language_the_old_list_settled_and_the_new_one_does_not_is_unknown_and_needs_a_recheck():
    cache = _seeded()
    stored = copy.deepcopy(cache)
    second = _match(_de(["English (fluent)"]), _no_call, cache)
    german = _german(second.output)
    assert german["status"] == "UNKNOWN" and german["needsRecheck"] is True
    assert any("language list that has changed" in w for w in second.warnings)
    assert second.output["staleReason"] == "languages"
    assert cache == stored


def test_an_unchanged_language_list_changes_nothing():
    cache = _seeded()
    again = _match(_de(["German (C1)"]), _no_call, cache)
    assert _german(again.output)["status"] == "MET" and "staleReason" not in again.output
    assert not any("language list" in w for w in again.warnings)


def test_a_language_the_new_list_newly_settles_resolves_locally():
    cache = {}
    old = _de(["English (fluent)"])
    _match(old, _model(old), cache)  # German was asked: the old list did not settle it
    again = _match(_de(["German (C1)"]), _no_call, cache)
    assert _german(again.output)["status"] == "MET" and "staleReason" not in again.output


def _engine(candidate, complete, cache_path, judge):
    return ShadowEngine(candidate, judge=judge, provider="test", model=None, cache_path=cache_path,
                        complete=complete, remap={}, select=None, compact=False)


def test_the_shadow_engine_marks_and_counts_stale_jobs_and_sends_nothing(tmp_path):
    cache_path = tmp_path / "engine.json"
    old = _de(["German (C1)"])
    seeded = _engine(old, _model(old), cache_path, True)
    seeded.apply([DE_JOB])
    seeded.save()
    for judge in (False, True):
        engine = _engine(_de(["English (fluent)"]), _no_call, cache_path, judge)
        shadow = engine.apply([DE_JOB])[0]["engineShadow"]
        assert shadow["staleReason"] == "languages"
        assert engine.preview([DE_JOB])["staleLanguages"] == 1
        assert engine.plan([DE_JOB]) == set()
    assert _engine(old, _no_call, cache_path, False).preview([DE_JOB])["staleLanguages"] == 0
