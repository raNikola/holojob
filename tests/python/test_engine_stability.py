"""The stability metrics (ROADMAP.md Phase 1, Stability), on made-up runs; no model calls."""

from fractions import Fraction

from match_engine.stability import drift, keyed, overall


def req(rid, status, strength=3, text=None):
    return {"id": rid, "status": status, "strength": strength, "text": text or rid}


def run(fit, *reqs):
    return {"fit": fit, "label": "Good", "bucket": "apply", "requirements": list(reqs)}


def test_identical_runs_do_not_drift():
    runs = [run(50, req("a", "MET"), req("b", "MISSING", 0))] * 3
    d = drift(runs)
    assert (d["overlap"], d["flips"], d["spread"]) == (1, 0, 0)
    assert d["flipped"] == [] and d["notInAll"] == []


def test_a_status_flip_on_a_shared_requirement():
    runs = [run(50, req("a", "MET")), run(44, req("a", "PARTIAL", 2)), run(47, req("a", "MET"))]
    d = drift(runs)
    assert d["flips"] == 1 and d["spread"] == 6
    assert d["flipped"] == [{"id": "a", "text": "a", "values": [("MET", 3), ("PARTIAL", 2), ("MET", 3)]}]


def test_a_strength_change_alone_is_not_a_flip():
    runs = [run(50, req("a", "MET", 3)), run(52, req("a", "MET", 4)), run(50, req("a", "MET", 3))]
    assert drift(runs)["flips"] == 0


def test_an_id_missing_from_one_run_lowers_overlap_and_is_not_counted_as_a_flip():
    runs = [run(50, req("a", "MET"), req("b", "MET")), run(50, req("a", "MET")), run(50, req("a", "MET"), req("b", "MISSING"))]
    d = drift(runs)
    assert d["overlap"] == Fraction(1, 2) and d["flips"] == 0
    assert d["notInAll"] == [{"id": "b", "text": "b", "runs": [1, 3]}]


def test_a_repeated_id_in_one_run_is_kept_apart():
    assert list(keyed([req("a", "MET"), req("a", "MISSING")])) == ["a", "a#2"]


def test_overall_pools_requirements_and_takes_the_worst_spread():
    d1 = drift([run(50, req("a", "MET"))] * 3)
    d2 = drift([run(40, req("x", "MET"), req("y", "MET")), run(48, req("x", "UNKNOWN", 0), req("y", "MET")),
                run(40, req("x", "MET"), req("y", "MET"))])
    assert overall([d1, d2]) == {"overlap": 1, "flips": Fraction(1, 3), "spread": 8}
