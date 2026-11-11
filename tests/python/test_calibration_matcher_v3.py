"""The experimental matcher's code half on fictional data: quote checks, typed verdicts, levels, two readings, the review queue. No model."""

import json

import pytest

from calibration import aggregation_preview as ap
from calibration import matcher_v3 as v3
from calibration.prelabel import owner_leaks
from match_engine import matcher

GATES = {g: {"quote": None} for g in v3.GATES}
AD = "We need five years of forecasting. Deep expertise in tender audits is required. Mail hr@third-party.test."
EVIDENCE = [{"id": "ev-a", "source": "role", "role": "Analyst", "start": None, "end": None, "text": "Built forecasting models for the finance team", "strength": 3},
            {"id": "ev-b", "source": "fact", "role": None, "start": None, "end": None, "text": "Tender audits", "strength": 1},
            {"id": "ev-c", "source": "role", "role": "Clerk", "start": None, "end": None, "text": "Holds a licence for inland waters only", "strength": 3}]
BY_ID = {e["id"]: e for e in EVIDENCE}
REQ = {"id": "r-1", "text": "Forecasting", "kind": "skill", "importance": "must", "postingQuote": "five years of forecasting"}


def proposal(status="MET", evidence="ev-a", quote="Built forecasting models", strength=3, req_level=None, level_quote=None, cand=None):
    return {"status": status, "evidenceId": evidence, "evidenceQuote": quote, "strength": strength, "requirementLevel": req_level, "requirementLevelQuote": level_quote, "candidateLevel": cand}


def line(status, strength=3, importance="must", req_id="r-1", req_level=None, cand=None, **extra):
    return {"id": req_id, "text": "t", "kind": "skill", "importance": importance, "status": status, "strength": strength, "quoteVerified": status in v3.NEEDS_QUOTE,
            "evidenceId": None, "requirementLevel": req_level, "candidateLevel": cand, **extra}


# --- quote verification and typed absence ---------------------------------------------------------


@pytest.mark.parametrize("status", ["MET", "PARTIAL", "CONTRADICTED"])
def test_a_status_that_needs_a_quote_keeps_it_only_when_the_quote_is_in_that_item(status):
    kept, warning = v3.verify(REQ, proposal(status), BY_ID, AD)
    assert kept["status"] == status and kept["quoteVerified"] is True and warning is None
    paraphrase, warning = v3.verify(REQ, proposal(status, quote="Made forecasts"), BY_ID, AD)
    assert paraphrase["status"] == v3.NOT_EVIDENCED and paraphrase["quoteVerified"] is False and "without a verified quote" in warning
    wrong_item, _ = v3.verify(REQ, proposal(status, evidence="ev-b"), BY_ID, AD)
    assert wrong_item["status"] == v3.NOT_EVIDENCED
    invented, _ = v3.verify(REQ, proposal(status, evidence="ev-zzz"), BY_ID, AD)
    assert invented["status"] == v3.NOT_EVIDENCED and invented["evidenceId"] is None


def test_silence_is_not_evidenced_and_never_contradicted_without_a_quote():
    silent, warning = v3.verify(REQ, proposal("NOT_EVIDENCED", evidence=None, quote=None, strength=0), BY_ID, AD)
    assert silent["status"] == v3.NOT_EVIDENCED and warning is None
    no_quote, _ = v3.verify(REQ, proposal("CONTRADICTED", evidence=None, quote=None, strength=0), BY_ID, AD)
    assert no_quote["status"] == v3.NOT_EVIDENCED


def test_strength_never_exceeds_the_items_own_and_only_a_positive_verdict_earns_one():
    assert v3.verify(REQ, proposal("MET", evidence="ev-b", quote="Tender audits", strength=4), BY_ID, AD)[0]["strength"] == 1
    assert v3.verify(REQ, proposal("CONTRADICTED", evidence="ev-c", quote="inland waters only", strength=4), BY_ID, AD)[0]["strength"] == 0


def test_a_not_evidenced_stays_out_of_fit_and_a_contradicted_counts_against_it():
    met = line("MET")
    assert ap.fit_of([met, line("NOT_EVIDENCED", 0, req_id="x")], {}) == ap.fit_of([met], {})
    assert ap.fit_of([met, line("CONTRADICTED", 0, req_id="x")], {}) < ap.fit_of([met], {})


# --- levels ---------------------------------------------------------------------------------------


def test_the_requirement_level_needs_a_quote_from_the_ad_and_the_candidate_level_a_verified_positive():
    good = v3.verify(REQ, proposal(req_level="expert", level_quote="Deep expertise in tender audits", cand="working"), BY_ID, AD)[0]
    assert (good["requirementLevel"], good["candidateLevel"]) == ("expert", "working")
    assert v3.verify(REQ, proposal(req_level="expert", level_quote="world class", cand="working"), BY_ID, AD)[0]["requirementLevel"] is None
    assert v3.verify(REQ, proposal(quote="not in the item", cand="expert"), BY_ID, AD)[0]["candidateLevel"] is None
    assert v3.verify(REQ, proposal("NOT_EVIDENCED", None, None, 0, cand="expert"), BY_ID, AD)[0]["candidateLevel"] is None
    assert v3.verify(REQ, proposal(req_level="guru", level_quote="Deep expertise", cand="ninja"), BY_ID, AD)[0]["requirementLevel"] is None


@pytest.mark.parametrize("required, shown, status, downgraded, gap", [
    ("expert", "working", "PARTIAL", True, 2), ("working", "working", "MET", False, 0), ("working", "expert", "MET", False, -2),
    (None, "working", "MET", False, None), ("expert", None, "MET", False, None),
])
def test_a_met_below_the_required_level_becomes_partial_and_the_gap_is_computed_in_code(required, shown, status, downgraded, gap):
    out = v3.apply_level(line("MET", req_level=required, cand=shown))
    assert (out["status"], out["levelDowngraded"], out["levelGap"]) == (status, downgraded, gap)


def test_a_partial_is_never_lowered_further_by_the_level():
    assert v3.apply_level(line("PARTIAL", req_level="expert", cand="familiar"))["status"] == "PARTIAL"


# --- two identical readings -------------------------------------------------------------------------


@pytest.mark.parametrize("a, b, final, flagged, reason", [
    ("MET", "MET", "MET", False, None),
    ("PARTIAL", "PARTIAL", "PARTIAL", False, None),
    ("NOT_EVIDENCED", "NOT_EVIDENCED", "NOT_EVIDENCED", False, None),
    ("CONTRADICTED", "CONTRADICTED", "CONTRADICTED", False, None),
    ("MET", "PARTIAL", "PARTIAL", True, "MET against PARTIAL"),
    ("PARTIAL", "MET", "PARTIAL", True, "MET against PARTIAL"),
    ("MET", "NOT_EVIDENCED", "NOT_EVIDENCED", True, "positive against silence"),
    ("NOT_EVIDENCED", "PARTIAL", "NOT_EVIDENCED", True, "positive against silence"),
    ("CONTRADICTED", "NOT_EVIDENCED", "NOT_EVIDENCED", True, "CONTRADICTED in one reading only"),
    ("MET", "CONTRADICTED", "NOT_EVIDENCED", True, "CONTRADICTED in one reading only"),
])
def test_two_readings_follow_the_owners_rule(a, b, final, flagged, reason):
    out = v3.aggregate_two({"r-1": line(a)}, {"r-1": line(b)})["r-1"]
    assert (out["status"], out["flagged"], out["flagReason"]) == (final, flagged, reason)


def test_a_disagreement_stays_out_of_fit_and_a_one_sided_contradiction_cannot_lower_it():
    base = {"m": line("MET", req_id="m")}
    positive_vs_silence = v3.aggregate_two({**base, "r-1": line("MET")}, {**base, "r-1": line("NOT_EVIDENCED", 0)})
    one_sided = v3.aggregate_two({**base, "r-1": line("CONTRADICTED", 0)}, {**base, "r-1": line("NOT_EVIDENCED", 0)})
    reference = ap.fit_of([line("MET", req_id="m")], {})
    assert ap.fit_of(list(positive_vs_silence.values()), {}) == ap.fit_of(list(one_sided.values()), {}) == reference


def test_agreeing_readings_take_the_lower_strength_and_the_partial_of_a_met_partial_pair_keeps_its_own():
    assert v3.aggregate_two({"r-1": line("MET", 4)}, {"r-1": line("MET", 2)})["r-1"]["strength"] == 2
    assert v3.aggregate_two({"r-1": line("MET", 4)}, {"r-1": line("PARTIAL", 1)})["r-1"]["strength"] == 1


def test_levels_must_agree_to_count_and_a_disagreement_flags_the_line():
    agreed = v3.aggregate_two({"r-1": line("MET", req_level="expert", cand="working")}, {"r-1": line("MET", req_level="expert", cand="working")})["r-1"]
    assert agreed["status"] == "PARTIAL" and agreed["levelDowngraded"] and not agreed["flagged"]
    differs = v3.aggregate_two({"r-1": line("MET", req_level="expert", cand="working")}, {"r-1": line("MET", req_level="expert", cand="advanced")})["r-1"]
    assert differs["status"] == "MET" and differs["candidateLevel"] is None and differs["flagged"] and differs["flagReason"] == "levels differ"


def test_a_requirement_missing_from_one_reading_is_silence_and_flagged():
    out = v3.aggregate_two({"r-1": line("MET")}, {})["r-1"]
    assert (out["status"], out["flagged"], out["flagReason"]) == ("NOT_EVIDENCED", True, "missing from one reading")


def test_two_readings_that_agree_and_are_wrong_are_not_flagged():
    assert v3.aggregate_two({"r-1": line("NOT_EVIDENCED", 0)}, {"r-1": line("NOT_EVIDENCED", 0)})["r-1"]["flagged"] is False  # a shared error is invisible here


# --- the review queue --------------------------------------------------------------------------------


def test_the_queue_holds_at_most_three_flagged_lines_musts_first_and_counts_the_rest():
    reqs = {f"n{i}": {**line("NOT_EVIDENCED", 0, "nice", f"n{i}"), "flagged": True} for i in range(2)}
    reqs |= {f"p{i}": {**line("PARTIAL", importance="preferred", req_id=f"p{i}"), "flagged": True} for i in range(1)}
    reqs |= {f"m{i}": {**line("NOT_EVIDENCED", 0, "must", f"m{i}"), "flagged": True} for i in range(2)}
    reqs["calm"] = {**line("MET", req_id="calm"), "flagged": False}
    q = v3.flag_queue(reqs)
    assert [r["id"] for r in q["queue"]] == ["m0", "m1", "p0"] and (q["flagged"], q["overflow"]) == (5, 2)
    assert v3.flag_queue({"calm": reqs["calm"]}) == {"queue": [], "flagged": 0, "overflow": 0}


# --- requests and replies ------------------------------------------------------------------------------


PROFILE = {"basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 123 4567"},
           "resume": {"parsedData": {"links": ["https://zorana.example/me"]}}}
IDENTITY = ("Zorana Testovic", ["https://zorana.example/me"])


def posting(description=AD, requirements=None):
    return {"id": "ad1", "title": "T", "company": "C", "location": "", "description": description, "facts": {"requirements": requirements or [REQ]}}


def candidate(evidence=None, facts=None, languages=None):
    return {"profileVersion": "v", "evidence": evidence or EVIDENCE, "confirmedFacts": facts or [], "gates": {"languages": languages or []}}


def test_the_prompt_defines_the_tighter_partial_asks_for_typed_absence_and_levels_and_holds_no_score():
    text = v3.prepare(posting(), candidate(), IDENTITY)["prompt"]
    for phrase in ("a named part of the requirement", "lower level or a smaller scope", "merely related", "NOT_EVIDENCED", "CONTRADICTED", "requirement_level_quote", "candidate_level"):
        assert phrase in text
    assert "MISSING" not in text and "score, a percentage" in text


def test_the_prompt_names_no_profession_or_tool():
    for word in ("product manager", "engineer", "nurse", "teacher", "developer", "docker", "kubernetes", "aws", "hospitality"):
        assert word not in v3.PROMPT.lower()


def test_owner_identifiers_in_the_evidence_are_redacted_before_the_request_and_the_scan_passes():
    evidence = EVIDENCE + [{"id": "ev-d", "source": "role", "role": None, "start": None, "end": None, "strength": 2,
                            "text": "Reach Zorana Testovic at zorana.testovic@example.test or +381 64 123 4567 or https://zorana.example/me"}]
    prompt = v3.prepare(posting(description="Own forecasting. five years of forecasting"), candidate(evidence), IDENTITY)["prompt"]
    for secret in ("Zorana", "Testovic", "zorana.testovic@example.test", "381 64 123", "zorana.example"):
        assert secret not in prompt
    assert owner_leaks(prompt, PROFILE) == []


def test_the_unchanged_scan_catches_a_name_left_in_the_ad():
    prompt = v3.prepare(posting(description=AD + " Ask Zorana Testovic."), candidate(), IDENTITY)["prompt"]
    assert owner_leaks(prompt, PROFILE)


def test_a_requirement_whose_quote_is_not_in_the_ad_is_dropped_before_the_model_sees_it():
    ghost = {**REQ, "id": "r-2", "postingQuote": "not in this ad"}
    prepared = v3.prepare(posting(requirements=[REQ, ghost]), candidate(), IDENTITY)
    assert [r["id"] for _, r in prepared["asked"]] == ["r-1"] and len(prepared["warnings"]) == 1


def test_confirmed_facts_are_settled_in_code_and_never_asked():
    prepared = v3.prepare(posting(), candidate(facts=[{"competencyId": "r-1", "answer": "no", "qualifier": None, "note": "", "coveredTexts": []}]), IDENTITY)
    assert prepared["asked"] == [] and prepared["resolved"][0]["status"] == v3.CONTRADICTED and prepared["resolved"][0]["ownerConfirmedAbsent"]
    yes = v3.prepare(posting(), candidate(facts=[{"competencyId": "r-1", "answer": "yes", "qualifier": None, "note": "", "coveredTexts": []}]), IDENTITY)
    assert yes["resolved"][0]["status"] == v3.MET


def test_a_language_absent_from_the_closed_list_stays_not_evidenced_and_is_marked():
    req = {"id": "r-l", "text": "German", "kind": "language", "importance": "must", "postingQuote": "German is required"}
    prepared = v3.prepare(posting(description="German is required", requirements=[req]), candidate(languages=["English"]), IDENTITY)
    assert prepared["asked"] == [] and prepared["resolved"][0]["status"] == v3.NOT_EVIDENCED and prepared["resolved"][0]["closedWorldAbsent"] is True


def reply(*matches):
    return {"matches": list(matches), "gates": GATES}


def match(ref, status="MET", evidence="ev-a", quote="Built forecasting models", strength=3):
    return {"ref": ref, "status": status, "evidence_id": evidence, "evidence_quote": quote, "strength": strength,
            "requirement_level": None, "requirement_level_quote": None, "candidate_level": None}


def test_a_reply_is_read_with_every_requirement_accounted_for():
    other = {**REQ, "id": "r-2", "postingQuote": "Deep expertise in tender audits"}
    prepared = v3.prepare(posting(requirements=[REQ, other]), candidate(), IDENTITY)
    out = v3.read_reply(prepared, reply(match("r1")), candidate())
    assert out["r-1"]["status"] == "MET" and out["r-2"]["status"] == v3.NOT_EVIDENCED and out["r-2"]["unanswered"] is True


def test_a_malformed_entry_is_left_out_and_a_wrong_frame_is_refused():
    assert v3.check_reply(reply({"ref": "r1", "status": "MAYBE", "strength": 1}, {**match("r2"), "strength": True}, "x")) == {}
    with pytest.raises(ValueError):
        v3.check_reply({"nope": 1})


def test_the_schema_is_strict_and_the_module_cannot_reach_a_model():
    assert v3.SCHEMA["strict"] is True and json.dumps(v3.SCHEMA)
    source = open(v3.__file__, encoding="utf-8").read()
    assert "complete_json" not in source and "requests.post" not in source and "urlopen" not in source


def test_the_production_prompt_and_schema_are_untouched_by_this_module():
    assert "MISSING" in matcher.PROMPT and "matcher_v3" not in open(matcher.__file__, encoding="utf-8").read()
