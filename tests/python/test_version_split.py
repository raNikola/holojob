"""The version split (ENGINE_CONTRACT.md 6.1): an answer changes the result in code and never asks the model again."""

import copy
import json
import re

import pytest

from evidence_index import build_candidate
from match_engine.gates import GATES
from match_engine.matcher import cache_key, match_posting, overlay_answers, posting_from_job
from match_engine.shadow import ShadowEngine

SKILL = "Roadmap planning"
PROFILE = {"basicProfile": {}, "resume": {"parsedData": {"skills": [SKILL]}}}
INTELLIGENCE = {"languages": ["English (fluent)"], "roleFamily": "product"}
SQL_YES = {"competencyId": "sql", "answer": "yes", "qualifier": None, "note": "private note", "coveredTexts": []}
SQL_NO = {"competencyId": "sql", "answer": "no", "qualifier": None, "note": "private note", "coveredTexts": []}


def _req(rid, text, kind="skill"):
    return {"id": rid, "provisional": False, "text": text, "kind": kind, "importance": "must", "postingQuote": text}


REQS = [_req("sql", "SQL"), _req("prov:aaaaaaaaaaaa", "Fluent English", "language"), _req("roadmap", "Roadmaps")]
JOB = {"jobId": "a", "title": "PM", "company": "Co", "location": "Remote", "matchScore": 80,
       "description": "SQL. Fluent English. Roadmaps.", "llmFacts": {"requirements": REQS}}
POSTING = posting_from_job(JOB, {})


def _candidate(facts=(), profile=PROFILE, intelligence=INTELLIGENCE):
    return build_candidate(profile, intelligence, list(facts))


def _no_call(prompt, schema=None, model=None, provider=None):
    raise AssertionError("the provider was called")


class Model:
    """Answers every ref in the prompt, PARTIAL on the one evidence item; `skip` refs get no answer."""

    def __init__(self, evidence_id, skip=()):
        self.evidence_id, self.skip, self.prompts = evidence_id, skip, []

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        block = prompt.split("=== BEGIN REQUIREMENTS ===")[1].split("=== END REQUIREMENTS ===")[0]
        return {"matches": [{"ref": ref, "status": "PARTIAL", "evidence_id": self.evidence_id,
                             "evidence_quote": SKILL, "strength": 1}
                            for ref in re.findall(r'"ref": "(r\d+)"', block) if ref not in self.skip],
                "gates": {g: {"quote": None} for g in GATES}}


def _match(candidate, complete, cache):
    return match_posting(POSTING, candidate, confirmed=True, provider="test", complete=complete, cache=cache)


def _model(candidate, skip=()):
    return Model(candidate["evidence"][0]["id"], skip)


def _status(output, rid):
    return next(r["status"] for r in output["requirements"] if r["id"] == rid)


def _engine(tmp_path, candidate, complete, judge=False, memory=None):
    return ShadowEngine(candidate, judge=judge, provider="test", model="m", cache_path=tmp_path / "engine.json",
                        complete=complete, workers=1, select=False, compact=False, remap={}, memory=memory)


@pytest.fixture
def seeded(tmp_path):
    """An engine.json holding the raw verdicts for JOB, made with no confirmed facts."""
    candidate = _candidate()
    engine = _engine(tmp_path, candidate, _model(candidate), judge=True)
    engine.apply([JOB])
    engine.save()
    return tmp_path


# --- the versions ------------------------------------------------------------------

@pytest.mark.parametrize("changed", [
    _candidate([SQL_YES]),
    _candidate(intelligence={**INTELLIGENCE, "jobFitPreferences": {"minSalaryEur": 5000}}),
], ids=["fact", "gate"])
def test_a_fact_or_a_gate_moves_only_the_answers_version_and_not_the_key(changed):
    base = _candidate()
    assert changed["evidenceVersion"] == base["evidenceVersion"]
    assert changed["answersVersion"] != base["answersVersion"]
    assert changed["profileVersion"] != base["profileVersion"]
    assert (cache_key("ad", changed["evidenceVersion"], None, REQS)
            == cache_key("ad", base["evidenceVersion"], None, REQS))


def test_evidence_and_role_family_move_the_evidence_version():
    base = _candidate()
    other = {"basicProfile": {}, "resume": {"parsedData": {"skills": [SKILL, "SQL"]}}}
    assert _candidate(profile=other)["evidenceVersion"] != base["evidenceVersion"]
    assert _candidate(profile=other)["answersVersion"] == base["answersVersion"]
    assert _candidate(intelligence={**INTELLIGENCE, "roleFamily": "x"})["evidenceVersion"] != base["evidenceVersion"]


# --- what is asked and what is cached --------------------------------------------------

def test_a_fact_does_not_stop_its_requirement_being_asked_but_a_settled_language_is_not_sent():
    candidate = _candidate([SQL_YES])
    model = _model(candidate)
    _match(candidate, model, {})
    asked = model.prompts[0].split("=== BEGIN REQUIREMENTS ===")[1]
    assert '"SQL"' in asked and '"Fluent English"' not in asked
    assert "private note" not in model.prompts[0] and "English (fluent)" not in model.prompts[0]


def test_the_cached_entry_holds_the_raw_verdicts_only():
    candidate = _candidate([SQL_YES])
    cache = {}
    outcome = _match(candidate, _model(candidate), cache)
    assert (_status(outcome.output, "sql"), _status(outcome.output, "prov:aaaaaaaaaaaa")) == ("MET", "MET")
    raw = cache[outcome.output["cacheKey"]]
    assert [r["status"] for r in raw["requirements"]] == ["PARTIAL", None, "PARTIAL"]
    assert "gates.languages" not in json.dumps(raw) and "answersVersion" not in raw


def test_the_shadow_cache_file_holds_the_raw_verdicts_only(seeded):
    candidate = _candidate([SQL_YES])
    engine = _engine(seeded, candidate, _no_call)
    assert engine.apply([JOB])[0]["engineShadow"]["requirements"][0]["status"] == "MET"
    raw = next(iter(json.loads((seeded / "engine.json").read_text()).values()))
    assert [r["status"] for r in raw["requirements"]] == ["PARTIAL", None, "PARTIAL"]


# --- a re-score after an answer ---------------------------------------------------------

def test_a_changed_fact_through_match_posting_makes_no_call():
    before = _candidate()
    cache = {}
    first = _match(before, _model(before), cache)
    assert _status(first.output, "sql") == "PARTIAL"
    stored = copy.deepcopy(cache)
    after = _candidate([SQL_NO])
    second = _match(after, _no_call, cache)
    assert second.output["cacheKey"] == first.output["cacheKey"]
    assert _status(second.output, "sql") == "MISSING"
    assert second.output["answersVersion"] == after["answersVersion"] != first.output["answersVersion"]
    assert second.output["profileVersion"] == after["profileVersion"]
    assert second.output["evidenceVersion"] == first.output["evidenceVersion"] == after["evidenceVersion"]
    assert cache == stored


@pytest.mark.parametrize("judge", [False, True])
def test_a_changed_fact_through_the_shadow_engine_makes_no_call(seeded, judge):
    after = _candidate([SQL_NO])
    engine = _engine(seeded, after, _no_call, judge=judge)
    shadow = engine.apply([JOB])[0]["engineShadow"]
    assert shadow["fromCache"] is True and _status(shadow, "sql") == "MISSING"
    assert (shadow["evidenceVersion"], shadow["answersVersion"]) == (after["evidenceVersion"], after["answersVersion"])
    assert engine.plan([JOB]) == set()


def test_a_revoked_fact_falls_back_to_the_model_verdict():
    with_fact = _candidate([SQL_YES])
    cache = {}
    assert _status(_match(with_fact, _model(with_fact), cache).output, "sql") == "MET"
    assert _status(_match(_candidate(), _no_call, cache).output, "sql") == "PARTIAL"


def test_the_overlay_returns_a_copy():
    candidate = _candidate()
    cache = {}
    output = _match(candidate, _model(candidate), cache).output
    raw = cache[output["cacheKey"]]
    stored = copy.deepcopy(raw)
    copied = overlay_answers(raw, candidate)
    copied["requirements"][2]["status"] = "changed"
    copied["warnings"].append("changed")
    assert raw == stored


def test_the_language_conflict_warning_is_kept_on_every_use():
    profile = {"basicProfile": {}, "resume": {"parsedData": {"skills": [SKILL, "English"]}}}
    candidate = _candidate(profile=profile, intelligence={**INTELLIGENCE, "languages": ["German (C1)"]})
    cache = {}
    first = _match(candidate, _model(candidate), cache)
    second = _match(candidate, _no_call, cache)
    assert any("must-have" in w for w in first.warnings) and second.warnings == first.warnings


def test_an_answer_settles_a_requirement_the_model_left_unanswered():
    candidate = _candidate([SQL_YES])
    cache = {}
    output = _match(candidate, _model(candidate, skip=("r1", "r3")), cache).output
    assert _status(output, "sql") == "MET"
    assert [r["id"] for r in output["requirements"]] == ["sql", "prov:aaaaaaaaaaaa"]
    assert sum("no usable answer" in w for w in output["warnings"]) == 1
    revoked = _match(_candidate(), _no_call, cache).output
    assert [r["id"] for r in revoked["requirements"]] == ["prov:aaaaaaaaaaaa"]


# --- the memory hook ---------------------------------------------------------------

class Memory:
    def __init__(self):
        self.observed, self.saved = [], 0

    def observe(self, posting, output):
        self.observed.append((posting["id"], _status(output, "sql")))

    def save(self):
        self.saved += 1


def test_memory_sees_the_overlaid_output_and_saves_even_without_a_judge(seeded):
    memory = Memory()
    engine = _engine(seeded, _candidate([SQL_YES]), _no_call, memory=memory)
    engine.apply([JOB])
    engine.save()
    assert memory.observed == [("a", "MET")] and memory.saved == 1


def test_memory_sees_a_fresh_match_too(tmp_path):
    memory = Memory()
    candidate = _candidate([SQL_NO])
    _engine(tmp_path, candidate, _model(candidate), judge=True, memory=memory).apply([JOB])
    assert memory.observed == [("a", "MISSING")]
