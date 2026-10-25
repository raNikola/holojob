"""Fit, confidence, label, counts, caps, bucket and questions (contract 5.1, 5.3-5.5)."""

from fractions import Fraction

import pytest

from match_engine import constants as C
from match_engine import fit as fit_module
from match_engine.fit import (
    capped_fit,
    caps_for,
    confidence_value,
    counts_of,
    fit_value,
    label_for,
    questions_for,
    round_half_up,
    score,
)
from match_engine.matcher import GATES

_n = iter(range(1, 10_000))


def req(status, importance="must", strength=None, verified=None, kind="skill", text=None):
    n = next(_n)
    if strength is None:
        strength = {"MET": 4, "PARTIAL": 2}.get(status, 0)
    if verified is None:
        verified = status in ("MET", "PARTIAL")
    return {"id": f"r{n}", "text": text or f"Skill {n}", "kind": kind, "importance": importance,
            "status": status, "quoteVerified": verified, "strength": strength}


def gates(*results, **by_gate):
    """All five gates: positional results in contract order, or pass with overrides by name."""
    if results:
        by_gate = dict(zip(GATES, results))
    return [{"gate": g, "result": by_gate.get(g, "pass"), "quote": None} for g in GATES]


PASS5 = gates()
UNKNOWN5 = gates(*["unknown"] * 5)


# --- constants --------------------------------------------------------------------

def test_constants_are_well_formed():
    # The caps sit under the labels they are meant to rule out (constants.py).
    assert C.ROLE_MISMATCH_FIT_CAP < C.LABEL_GOOD_MIN
    assert C.UNVERIFIED_FIT_CAP < C.LABEL_PARTIAL_MIN
    assert len(C.STRENGTH_CREDIT) == 5
    assert list(C.STRENGTH_CREDIT) == sorted(C.STRENGTH_CREDIT)
    assert C.STRENGTH_CREDIT[0] == 0 and C.STRENGTH_CREDIT[4] == 1
    assert set(C.IMPORTANCE_WEIGHT) == {"must", "preferred", "nice"}
    assert C.IMPORTANCE_WEIGHT["must"] >= C.IMPORTANCE_WEIGHT["preferred"] >= C.IMPORTANCE_WEIGHT["nice"] > 0
    assert 0 <= C.PARTIAL_FACTOR <= 1
    assert 0 <= C.MIN_CONFIDENCE <= 1 and 0 <= C.MAX_UNKNOWN_MUST_RATIO <= 1
    assert 100 >= C.LABEL_STRONG_MIN > C.LABEL_GOOD_MIN > C.LABEL_PARTIAL_MIN > 0


# --- rounding ---------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [("48.5", 49), ("47.5", 48), ("48.4999", 48), ("0", 0), ("100", 100)])
def test_round_half_up(value, expected):
    assert round_half_up(Fraction(value)) == expected


# --- Fit --------------------------------------------------------------------------

def test_fit_all_met_at_full_strength_is_100():
    assert fit_value([req("MET"), req("MET", "preferred"), req("MET", "nice")]) == 100


def test_fit_all_met_at_claim_strength_is_the_claim_credit():
    assert fit_value([req("MET", strength=1), req("MET", "nice", strength=1)]) == 25


def test_fit_all_unknown_is_0():
    assert fit_value([req("UNKNOWN"), req("UNKNOWN", "nice")]) == 0


def test_fit_empty_is_0():
    assert fit_value([]) == 0


def test_fit_all_missing_is_0():
    assert fit_value([req("MISSING"), req("MISSING", "nice")]) == 0


def test_fit_mixed():
    reqs = [
        req("MET", "must", 4),         # 1     x 3 = 3
        req("PARTIAL", "must", 2),     # 0.25  x 3 = 0.75
        req("MISSING", "preferred"),   # 0     x 2 = 0
        req("MET", "nice", 3),         # 0.9   x 1 = 0.9
        req("UNKNOWN", "must"),        # not counted
    ]
    # 4.65 / 9 = 51.67
    assert fit_value(reqs) == 52


def test_unknown_changes_neither_numerator_nor_denominator():
    base = [req("MET", "must", 4), req("MISSING", "must")]
    assert fit_value(base) == fit_value(base + [req("UNKNOWN", "must"), req("UNKNOWN", "nice")]) == 50


def test_fit_rounds_half_up():
    # MET must at strength 4 (3) + MET nice at 1 (0.25) + 6 MISSING nice: 3.25 / 10 = 32.5 -> 33
    reqs = [req("MET", "must", 4), req("MET", "nice", 1)] + [req("MISSING", "nice") for _ in range(6)]
    assert fit_value(reqs) == 33


# --- confidence -------------------------------------------------------------------

def test_confidence_counts_verified_met_partial_and_any_missing():
    reqs = [
        req("MET", "must"),                         # 3 verified
        req("PARTIAL", "preferred", verified=False),  # 2 not verified
        req("MISSING", "nice"),                     # 1 verified, no quote needed
        req("UNKNOWN", "must"),                     # 3 not verified
    ]
    assert confidence_value(reqs, []) == Fraction(4, 9)


def test_confidence_of_nothing_is_0():
    assert confidence_value([], []) == 0


def test_confidence_is_reported_rounded():
    # 3 / (6 + 5 unknown gates x 3) = 1/7
    assert score([req("MET"), req("UNKNOWN", "must")], UNKNOWN5)["confidence"] == 0.1429


# --- label: Incomplete paths ------------------------------------------------------

def test_incomplete_when_nothing_is_settled():
    result = score([req("UNKNOWN"), req("UNKNOWN", "nice")], PASS5)
    assert result["label"] == "Incomplete"
    assert result["labelText"] == "Incomplete - answer 2 questions"


def test_incomplete_when_there_are_no_requirements():
    result = score([], PASS5)
    assert (result["fit"], result["label"], result["labelText"]) == (0, "Incomplete", "Incomplete - answer 0 questions")


def test_incomplete_on_low_confidence_alone():
    # Every PARTIAL is unverified and every gate unknown: confidence 0, while no must is UNKNOWN (ratio 0).
    reqs = [req("PARTIAL", "must", 1, verified=False), req("PARTIAL", "nice", 1, verified=False)]
    assert score(reqs, UNKNOWN5)["label"] == "Incomplete"


def test_incomplete_on_unknown_must_ratio_alone():
    # 2 of 5 musts UNKNOWN (0.4 > 0.3) while confidence is 19/25, well above the minimum.
    reqs = [req("MET") for _ in range(3)] + [req("UNKNOWN"), req("UNKNOWN")] + [req("MET", "nice") for _ in range(10)]
    result = score(reqs, PASS5)
    assert confidence_value(reqs, PASS5) >= C.MIN_CONFIDENCE
    assert result["label"] == "Incomplete"
    assert result["labelText"] == "Incomplete - answer 2 questions"


def test_unknown_must_ratio_at_the_limit_is_not_incomplete():
    # 3 of 9 musts UNKNOWN is exactly the limit: not above it.
    reqs = [req("MET") for _ in range(6)] + [req("UNKNOWN") for _ in range(3)]
    assert Fraction(3, 9) == C.MAX_UNKNOWN_MUST_RATIO
    assert score(reqs, PASS5)["label"] == "Strong"
    assert score(reqs + [req("UNKNOWN")], PASS5)["label"] == "Incomplete"


def test_confidence_at_the_limit_is_not_incomplete():
    # A verified must (3) and two settled gates (6) of 3 + 15 weight: exactly 0.5.
    reqs = [req("MET", "must")]
    two_settled = gates("pass", "fail", "unknown", "unknown", "unknown")
    assert confidence_value(reqs, two_settled) == C.MIN_CONFIDENCE
    assert score(reqs, two_settled)["label"] != "Incomplete"


def test_no_musts_means_no_ratio_trigger():
    reqs = [req("MET", "nice"), req("UNKNOWN", "preferred")]
    assert counts_of(reqs, PASS5)["mustTotal"] == 0
    # Confidence 16/18 is above the minimum and there is no must to take a ratio of.
    assert score(reqs, PASS5)["label"] == "Strong"


def test_n_counts_unknowns_of_every_importance():
    # 1 of 2 musts UNKNOWN triggers it; N also counts the preferred and nice UNKNOWNs.
    reqs = [req("MET"), req("UNKNOWN", "must"), req("UNKNOWN", "preferred"), req("UNKNOWN", "nice")]
    result = score(reqs, PASS5)
    assert result["label"] == "Incomplete"
    assert result["labelText"] == "Incomplete - answer 3 questions"
    assert len(result["questions"]) == result["counts"]["unknown"] == 3


# --- label: thresholds ------------------------------------------------------------

@pytest.mark.parametrize(
    "fit,label",
    [(100, "Strong"), (C.LABEL_STRONG_MIN, "Strong"), (C.LABEL_STRONG_MIN - 1, "Good"),
     (C.LABEL_GOOD_MIN, "Good"), (C.LABEL_GOOD_MIN - 1, "Partial"),
     (C.LABEL_PARTIAL_MIN, "Partial"), (C.LABEL_PARTIAL_MIN - 1, "Weak"), (0, "Weak")],
)
def test_label_thresholds(fit, label):
    assert label_for(fit) == label


def test_threshold_boundaries_follow_the_constants(monkeypatch):
    monkeypatch.setattr(fit_module, "LABEL_STRONG_MIN", 90)
    assert label_for(89) == "Good" and label_for(90) == "Strong"


# --- counts and questions -----------------------------------------------------------

def test_counts():
    reqs = [
        req("MET", "must"), req("PARTIAL", "must"), req("MISSING", "must"), req("MISSING", "must"),
        req("UNKNOWN", "must"),
        req("MET", "preferred"), req("UNKNOWN", "preferred"),
        req("MISSING", "nice"), req("UNKNOWN", "nice"),
    ]
    assert counts_of(reqs, PASS5) == {
        "mustMet": 1, "mustTotal": 5, "preferredMet": 1, "preferredTotal": 2, "unknown": 3, "blockers": 2,
    }


def test_questions_one_per_unknown_in_order_templated_by_kind():
    reqs = [
        req("UNKNOWN", kind="skill", text="Kubernetes"),
        req("MET"),
        req("UNKNOWN", "nice", kind="language", text="German (B2)."),
        req("UNKNOWN", "preferred", kind="experience", text="5+ years in fintech"),
        req("MISSING"),
        req("UNKNOWN", kind="weird", text="A thing"),
    ]
    assert questions_for(reqs, PASS5) == [
        {"competencyId": reqs[0]["id"], "question": "Have you worked with Kubernetes?"},
        {"competencyId": reqs[2]["id"], "question": "Do you speak German (B2)?"},
        {"competencyId": reqs[3]["id"], "question": "Do you have this experience: 5+ years in fintech?"},
        {"competencyId": reqs[5]["id"], "question": "Does this apply to you: A thing?"},
    ]


def test_score_is_deterministic():
    reqs = [req("MET", "must", 3), req("PARTIAL", "nice", 2), req("UNKNOWN", "preferred")]
    mixed = gates("pass", "unknown", "pass", "fail", "pass")
    assert score(reqs, mixed) == score([dict(r) for r in reqs], [dict(g) for g in mixed])


# --- gate weight in confidence (section 5.3) ----------------------------------------

def test_each_gate_weighs_as_a_must_and_counts_when_settled():
    reqs = [req("MET", "must"), req("UNKNOWN", "nice")]  # 3 verified of 4
    must = C.IMPORTANCE_WEIGHT["must"]
    # pass, fail, fail settled; two unknown add weight only.
    mixed = gates("pass", "fail", "unknown", "fail", "unknown")
    assert confidence_value(reqs, mixed) == Fraction(3 + 3 * must, 4 + 5 * must)
    assert confidence_value(reqs, PASS5) == Fraction(3 + 5 * must, 4 + 5 * must)
    assert confidence_value(reqs, UNKNOWN5) == Fraction(3, 4 + 5 * must)


def test_gates_alone_give_confidence():
    assert confidence_value([], gates("pass", "pass", "unknown", "unknown", "unknown")) == Fraction(2, 5)


# --- caps (section 5.5) ---------------------------------------------------------------

STRONG_REQS = [req("MET"), req("MET", "preferred")]  # Fit 100, every quote verified


def test_no_cap_on_a_clean_posting():
    result = score(STRONG_REQS, PASS5)
    assert (result["fit"], result["caps"], result["label"]) == (100, [], "Strong")


def test_role_family_mismatch_caps_fit():
    result = score(STRONG_REQS, gates(role_family="fail"))
    assert result["fit"] == C.ROLE_MISMATCH_FIT_CAP
    assert result["caps"] == ["role_family_mismatch", "gate_blocked"]


def test_unknown_role_family_does_not_cap():
    assert score(STRONG_REQS, gates(role_family="unknown"))["caps"] == []


def test_no_verified_evidence_caps_fit():
    # Fit 50 from unverified PARTIALs at full strength; nothing has quoteVerified.
    reqs = [req("PARTIAL", "must", 4, verified=False), req("PARTIAL", "must", 4, verified=False)]
    assert fit_value(reqs) == 50
    result = score(reqs, PASS5)
    assert result["fit"] == C.UNVERIFIED_FIT_CAP
    assert result["caps"] == ["no_verified_evidence"]


def test_one_verified_quote_lifts_the_unverified_cap():
    reqs = [req("PARTIAL", "must", 4, verified=False), req("MET", "nice", 4)]
    assert "no_verified_evidence" not in score(reqs, PASS5)["caps"]


def test_all_missing_lists_the_unverified_cap():
    # MISSING carries no quote, so nothing is verified; Fit is 0 under the cap anyway.
    result = score([req("MISSING"), req("MISSING")], PASS5)
    assert (result["fit"], result["caps"]) == (0, ["no_verified_evidence"])


def test_both_caps_hold_fit_to_the_lower():
    reqs = [req("PARTIAL", "must", 4, verified=False)]
    result = score(reqs, gates(role_family="fail"))
    assert result["caps"] == ["role_family_mismatch", "gate_blocked", "no_verified_evidence"]
    assert result["fit"] == min(C.ROLE_MISMATCH_FIT_CAP, C.UNVERIFIED_FIT_CAP, fit_value(reqs))


def test_lower_ceiling_wins_whichever_it_is(monkeypatch):
    both = ["role_family_mismatch", "no_verified_evidence"]
    monkeypatch.setitem(fit_module.CAP_CEILINGS, "role_family_mismatch", 20)
    monkeypatch.setitem(fit_module.CAP_CEILINGS, "no_verified_evidence", 30)
    assert capped_fit(90, both) == 20
    monkeypatch.setitem(fit_module.CAP_CEILINGS, "role_family_mismatch", 45)
    assert capped_fit(90, both) == 30


def test_a_cap_never_raises_fit():
    assert capped_fit(12, ["role_family_mismatch", "no_verified_evidence", "gate_blocked"]) == 12


def test_gate_blocked_alone_does_not_move_fit():
    assert caps_for(STRONG_REQS, gates(salary_floor="fail")) == ["gate_blocked"]
    assert score(STRONG_REQS, gates(salary_floor="fail"))["fit"] == 100


def test_cap_applies_before_the_label():
    # Raw Fit 100 is Strong; held to 40 by the mismatch cap, the label follows the capped Fit.
    result = score(STRONG_REQS, gates(role_family="fail"))
    assert result["label"] == label_for(C.ROLE_MISMATCH_FIT_CAP)


# --- bucket, blockers and the blocked label (section 5.4) ------------------------------

@pytest.mark.parametrize(
    "results,bucket",
    [
        (("pass",) * 5, "apply"),
        (("unknown", "pass", "pass", "pass", "pass"), "check_first"),
        (("pass", "pass", "pass", "pass", "unknown"), "check_first"),
        (("unknown",) * 5, "check_first"),
        (("fail", "pass", "pass", "pass", "pass"), "blocked"),
        (("pass", "pass", "pass", "pass", "fail"), "blocked"),
        (("fail", "unknown", "pass", "unknown", "pass"), "blocked"),
        (("fail",) * 5, "blocked"),
    ],
)
def test_bucket_rollup(results, bucket):
    assert score(STRONG_REQS, gates(*results))["bucket"] == bucket


@pytest.mark.parametrize("gate", GATES)
def test_one_fail_on_any_gate_blocks(gate):
    assert score(STRONG_REQS, gates(**{gate: "fail"}))["bucket"] == "blocked"


def test_failed_gates_join_blockers():
    reqs = [req("MET"), req("MISSING")]
    assert counts_of(reqs, gates(location="fail", language="fail"))["blockers"] == 3
    assert counts_of(reqs, gates(location="unknown"))["blockers"] == 1


@pytest.mark.parametrize("fit_reqs,unblocked", [
    (STRONG_REQS, "Strong"),
    ([req("MET", strength=2)], "Good"),                    # Fit 50
])
def test_blocked_strong_or_good_becomes_partial(fit_reqs, unblocked):
    assert score(fit_reqs, PASS5)["label"] == unblocked
    assert score(fit_reqs, gates(salary_floor="fail"))["label"] == "Partial"


def test_blocked_partial_weak_and_incomplete_stay():
    blocked = gates(location="fail")
    partial = [req("MET", strength=2), req("MISSING", "nice")]  # Fit 38
    weak = [req("MET", strength=1), req("MISSING")]          # Fit 13
    incomplete = [req("UNKNOWN"), req("UNKNOWN")]
    assert [score(r, blocked)["label"] for r in (partial, weak, incomplete)] == ["Partial", "Weak", "Incomplete"]


# --- gate questions -------------------------------------------------------------------

def test_unknown_gates_become_questions_after_the_requirements():
    reqs = [req("UNKNOWN", text="SQL")]
    result = score(reqs, gates("pass", "unknown", "fail", "unknown", "pass"))
    assert [q["competencyId"] for q in result["questions"]] == [reqs[0]["id"], "location", "salary_floor"]
    assert all(q["question"] for q in result["questions"])


def test_output_carries_all_five_gates():
    result = score(STRONG_REQS, PASS5)
    assert [g["gate"] for g in result["gates"]] == list(GATES)
