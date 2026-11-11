"""Applying a confirmed answer to a requirement: table 4.4 and which requirements an answer reaches (A3). Fictional data, no model."""

import json

import pytest

from calibration import matcher_v3 as v3
from competency_mapping import Mapper
from match_engine import fact_links, verify
from match_engine.verify import CONFIRMED_FACT_STRENGTH as STRENGTH

REQ = {"id": "forecasting", "text": "Writing forecasts", "kind": "skill", "importance": "must", "postingQuote": "forecasts"}
LEVELLED = {**REQ, "qualifier": {"kind": "years", "value": 10}}


def fact(answer, years=None, covered=(), competency="forecasting"):
    return {
        "competencyId": competency, "answer": answer, "qualifier": {"kind": "years", "value": years} if years is not None else None,
        "note": "owner only", "answeredAt": None, "overrules": [], "coveredTexts": list(covered), "history": [],
    }


def apply(req, f, vocabulary="production"):
    return verify.apply_confirmed_fact(req, f, {}, vocabulary=vocabulary)


class Links:
    """A mapper that gives one link status, for the statuses the seed files do not produce."""

    def __init__(self, status):
        self.status = status

    def mapping_status(self, requirement):
        return self.status


def with_links(monkeypatch, status):
    monkeypatch.setattr(fact_links, "_cached_mapper", lambda family: Links(status))


def candidate(*facts, family="product"):
    return {"roleFamily": family, "confirmedFacts": list(facts), "evidence": [], "gates": {}}


# --- table 4.4: a requirement with no level ------------------------------------------


@pytest.mark.parametrize("answer,years,status", [
    ("yes", None, "MET"),
    ("yes", 3, "MET"),
    ("partly", None, "PARTIAL"),
    ("partly", 3, "PARTIAL"),
])
def test_no_level_answers(answer, years, status):
    out = apply(REQ, fact(answer, years))
    assert (out["status"], out["strength"], out["quoteVerified"]) == (status, STRENGTH, True)
    assert "levelReason" not in out


# --- table 4.4: a requirement with years -------------------------------------------


@pytest.mark.parametrize("answer", ["yes", "partly"])
def test_an_answer_without_years_leaves_a_levelled_requirement_to_the_matcher(answer):
    assert apply(LEVELLED, fact(answer)) is None


@pytest.mark.parametrize("years", [10, 11])
def test_yes_at_or_above_the_level_is_met(years):
    out = apply(LEVELLED, fact("yes", years))
    assert (out["status"], out["strength"]) == ("MET", STRENGTH)
    assert "levelReason" not in out


def test_yes_below_the_level_is_partial_with_its_reason():
    out = apply(LEVELLED, fact("yes", 7))
    assert (out["status"], out["strength"], out["levelReason"]) == ("PARTIAL", STRENGTH, "7 years confirmed, ad asks 10+")


def test_the_comparison_is_exact():
    assert apply(LEVELLED, fact("yes", 9))["status"] == "PARTIAL"
    assert apply(LEVELLED, fact("yes", 10))["status"] == "MET"


def test_zero_years_is_a_stated_value():
    assert apply(LEVELLED, fact("yes", 0))["levelReason"] == "0 years confirmed, ad asks 10+"
    assert apply(LEVELLED, fact("partly", 0))["status"] == "PARTIAL"


@pytest.mark.parametrize("years", [3, 10, 12])
def test_partly_with_years_stays_partial(years):
    out = apply(LEVELLED, fact("partly", years))
    assert (out["status"], out["strength"]) == ("PARTIAL", STRENGTH)
    assert "levelReason" not in out


def test_a_qualifier_of_another_kind_is_no_level():
    assert apply({**REQ, "qualifier": {"kind": "seniority", "value": 2}}, fact("yes"))["status"] == "MET"


# --- no, unknown, the output shape -------------------------------------------------


@pytest.mark.parametrize("req", [REQ, LEVELLED])
@pytest.mark.parametrize("vocabulary,status", [("production", "MISSING"), ("stage_b", "CONTRADICTED")])
def test_no_goes_through_the_vocabulary(req, vocabulary, status):
    out = apply(req, fact("no"), vocabulary)
    assert (out["status"], out["strength"], out["quoteVerified"]) == (status, 0, True)


def test_no_is_production_vocabulary_by_default():
    assert verify.apply_confirmed_fact(REQ, fact("no"), {})["status"] == "MISSING"


def test_the_translation_table_and_the_reply_statuses():
    assert verify.VOCABULARY["production"] == {"contradicted": "MISSING", "not_evidenced": "UNKNOWN"}
    assert verify.VOCABULARY["stage_b"] == {"contradicted": "CONTRADICTED", "not_evidenced": "NOT_EVIDENCED"}
    assert verify.STATUSES == ("MET", "PARTIAL", "MISSING", "UNKNOWN")


@pytest.mark.parametrize("req", [REQ, LEVELLED])
def test_unknown_leaves_the_matcher_verdict(req):
    assert apply(req, fact("unknown")) is None


def test_output_keeps_the_requirement_and_the_resolved_shape():
    out = apply(REQ, fact("yes"))
    assert {k: out[k] for k in REQ} == REQ
    assert (out["evidenceId"], out["evidenceQuote"]) == (None, None)
    assert "note" not in out


def test_a_known_evidence_id_is_kept_and_an_unknown_one_is_not():
    f = {**fact("yes"), "evidenceId": "ev-a"}
    assert verify.apply_confirmed_fact(REQ, f, {"ev-a": {"id": "ev-a"}})["evidenceId"] == "ev-a"
    assert verify.apply_confirmed_fact(REQ, f, {})["evidenceId"] is None


# --- which requirements an answer reaches -------------------------------------------


@pytest.mark.parametrize("status", ["pending", "auto", "demoted"])
def test_an_unreviewed_link_does_not_carry_by_itself(monkeypatch, status):
    with_links(monkeypatch, status)
    assert verify.resolve_fact(REQ, candidate(fact("yes")), {}) is None


@pytest.mark.parametrize("status", ["pending", "auto", "demoted"])
def test_an_unreviewed_link_carries_when_the_answer_covered_its_text(monkeypatch, status):
    with_links(monkeypatch, status)
    assert verify.resolve_fact(REQ, candidate(fact("yes", covered=["Writing forecasts"])), {})["status"] == "MET"


def test_coverage_compares_normalized_texts_on_both_sides(monkeypatch):
    with_links(monkeypatch, "auto")
    assert verify.resolve_fact({**REQ, "text": "  WRITING   forecasts."}, candidate(fact("yes", covered=["writing forecasts"])), {})["status"] == "MET"


def test_an_answer_covers_exactly_the_listed_texts(monkeypatch):
    with_links(monkeypatch, "auto")
    f = fact("yes", covered=["Writing forecasts", "Building forecasts"])
    assert verify.resolve_fact(REQ, candidate(f), {})["status"] == "MET"
    assert verify.resolve_fact({**REQ, "text": "Defining forecasts"}, candidate(f), {}) is None


@pytest.mark.parametrize("status", ["reviewed", None])
def test_reviewed_and_no_link_carry(monkeypatch, status):
    with_links(monkeypatch, status)
    assert verify.resolve_fact(REQ, candidate(fact("yes")), {})["status"] == "MET"


def test_an_unrecognised_status_carries_nothing_by_itself():
    assert fact_links.carries(REQ, fact("yes"), Links("something-new")) is False


def test_no_mapper_for_the_family_carries():
    assert fact_links.fact_for(REQ, candidate(fact("yes"), family=None), lambda family: None) is not None


def test_no_fact_for_the_requirement_never_asks_for_a_mapper():
    def fail(family):
        raise AssertionError("no mapper is needed")
    assert fact_links.fact_for(REQ, candidate(fact("yes", competency="other")), fail) is None
    assert verify.resolve_fact(REQ, candidate(), {}) is None


def test_an_unknown_fact_returns_none_through_resolve_fact(monkeypatch):
    with_links(monkeypatch, "reviewed")
    assert verify.resolve_fact(REQ, candidate(fact("unknown")), {}) is None


def test_the_seed_and_a_reviewed_learned_alias_carry_on_a_real_mapper(tmp_path):
    comps = [{"id": "forecasting", "kind": "skill", "aliases": ["Writing forecasts"]}]
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({
        "building forecasts": {"competencyId": "forecasting", "status": "reviewed"},
        "defining forecasts": {"competencyId": "forecasting", "status": "pending"},
    }))
    mapper = Mapper(comps, aliases_path=aliases, remap_path=tmp_path / "remap.json")
    assert fact_links.carries(REQ, fact("yes"), mapper)  # seed
    assert fact_links.carries({**REQ, "text": "Building forecasts"}, fact("yes"), mapper)  # reviewed
    assert not fact_links.carries({**REQ, "text": "Defining forecasts"}, fact("yes"), mapper)  # pending
    assert fact_links.carries({**REQ, "text": "A dictionary term"}, fact("yes"), mapper)  # no alias: the id match is the identity


# --- the matcher_v3 path -------------------------------------------------------------

AD = "Writing forecasts for ten years"
V3_REQ = {**REQ, "postingQuote": "Writing forecasts"}


def prepared(req, f, family=None):
    return v3.prepare({"description": AD, "facts": {"requirements": [req]}}, {**candidate(f, family=family), "profileVersion": "v"}, {})


def test_v3_no_is_contradicted_and_marked():
    out = prepared(V3_REQ, fact("no"))
    assert out["asked"] == []
    assert (out["resolved"][0]["status"], out["resolved"][0]["strength"], out["resolved"][0]["ownerConfirmedAbsent"]) == (v3.CONTRADICTED, 0, True)
    assert (out["resolved"][0]["requirementLevel"], out["resolved"][0]["candidateLevel"]) == (None, None)


def test_v3_yes_below_level_is_partial_with_its_reason():
    out = prepared({**V3_REQ, "qualifier": {"kind": "years", "value": 10}}, fact("yes", 7))
    assert out["resolved"][0]["status"] == v3.PARTIAL
    assert out["resolved"][0]["levelReason"] == "7 years confirmed, ad asks 10+"
    assert "ownerConfirmedAbsent" not in out["resolved"][0]


@pytest.mark.parametrize("f", [fact("unknown"), fact("yes")])
def test_v3_an_answer_that_settles_nothing_is_asked_as_usual(f):
    out = prepared({**V3_REQ, "qualifier": {"kind": "years", "value": 10}}, f)
    assert out["resolved"] == {} and [ref for ref, _ in out["asked"]] == ["r1"]


def test_v3_an_uncovered_auto_link_is_asked(monkeypatch):
    with_links(monkeypatch, "auto")
    out = prepared(V3_REQ, fact("yes"), family="product")
    assert out["resolved"] == {} and [ref for ref, _ in out["asked"]] == ["r1"]
