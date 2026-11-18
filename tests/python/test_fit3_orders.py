"""Shadow order variants of Fit 3 (match_engine/fit3_orders.py): synthetic blocks only, no stored data."""

from fractions import Fraction

import pytest

from match_engine import fit3, fit3_orders


def unit(ask, status="MET", strength=4):
    return {"id": "x", "ask": ask, "adQuote": "q", "demotedFromCore": False, "status": status, "strength": strength, "quoteVerified": True, "answered": True}


def block(units, role="target", domain="unknown", insufficient=False):
    core = [u for u in units if u["ask"] == "core"]
    done = [u for u in core if fit3.resolved(u)]
    return {"scoringVersion": fit3.SCORING_VERSION, "role": {"class": role}, "domain": domain, "insufficientEvidence": insufficient,
            "requirements": {"units": units, "coreCounts": {"core": len(core), "resolvedCore": len(done)},
                             "coreCoverage": str(fit3._coverage(core)) if fit3._coverage(core) is not None else None,
                             "secondaryCoverage": str(fit3._coverage([u for u in units if u["ask"] == "secondary"])) if any(u["ask"] == "secondary" for u in units) and fit3._coverage([u for u in units if u["ask"] == "secondary"]) is not None else None}}


def test_round_half_up_is_math_round():
    assert [fit3_orders.round_half_up(Fraction(n, 2)) for n in (1, 2, 3, 5)] == [1, 1, 2, 3]


def test_blend_weights_core_three_to_secondary_two():
    b, core_credit, n_core = fit3_orders.blend(block([unit("core"), unit("secondary", "CONTRADICTED")]))
    assert (b, core_credit, n_core) == (Fraction(3, 5), Fraction(1), 1)


def test_unresolved_units_are_out_of_the_denominator():
    b, _, n = fit3_orders.blend(block([unit("core"), unit("core", "UNKNOWN"), unit("secondary", fit3.NOT_EVIDENCED)]))
    assert (b, n) == (Fraction(1), 1)


def test_c1_caps_a_core_with_no_credit_at_30():
    key = fit3_orders.order_key(block([unit("core", "CONTRADICTED"), unit("secondary")]), "c1")
    assert key[2] == -30  # blend 2/5 -> 40, capped


def test_c1_confidence_band_tie_break():
    full = block([unit("core"), unit("core")])
    half = block([unit("core"), unit("core", "UNKNOWN")])
    assert fit3_orders.order_key(full, "c1")[3] == 0 and fit3_orders.order_key(half, "c1")[3] == 1


@pytest.mark.parametrize("x,expected", [(Fraction(9, 10), 0), (Fraction(89, 100), 0), (Fraction(4, 5), 1), (Fraction(79, 100), 1), (Fraction(3, 5), 2),
                                        (Fraction(59, 100), 2), (Fraction(29, 100), 3), (Fraction(0), 3)])
def test_c3_bands_follow_the_career_ops_scale(x, expected):
    assert fit3_orders.band(x) == expected


def test_tier_and_domain_come_before_coverage_in_every_order():
    best_other = block([unit("core")], role="other")
    weak_target = block([unit("core", "CONTRADICTED")], role="target")
    different = block([unit("core")], domain="different")
    for order in fit3_orders.ORDERS:
        assert fit3_orders.order_key(weak_target, order) < fit3_orders.order_key(best_other, order)
        assert fit3_orders.order_key(block([unit("core", "CONTRADICTED")]), order) < fit3_orders.order_key(different, order)


def test_rank_keeps_insufficient_apart_and_refuses_other_versions():
    rows = [{"id": "b", "fit3": block([unit("core")])}, {"id": "a", "fit3": block([unit("core")], insufficient=True)}]
    out = fit3_orders.rank(rows, "c2")
    assert [r["id"] for r in out["ranked"]] == ["b"] and [r["id"] for r in out["insufficient"]] == ["a"]
    rows[0]["fit3"] = {**rows[0]["fit3"], "scoringVersion": "2.1"}
    with pytest.raises(fit3.MixedScoringVersions):
        fit3_orders.rank(rows, "c2")


def test_unknown_order_is_refused():
    with pytest.raises(ValueError):
        fit3_orders.order_key(block([unit("core")]), "c9")
