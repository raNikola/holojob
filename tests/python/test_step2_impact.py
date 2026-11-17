"""measure_step2_impact: every changed ad is classified from the frozen baseline's capsFired; anything else stops the package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import measure_step2_impact as impact  # noqa: E402


def row(score, caps=(), band="Weak", status="sufficient"):
    return {"score": score, "scoreBeforeCaps": score, "band": band, "dataStatus": status, "capsFired": list(caps)}


def test_changed_ads_are_classified_by_the_baselines_caps_and_other_is_reported():
    base = {"a": row(45, ["visa:needs_visa_silent"]), "b": row(25, ["language"], "Reject"), "c": row(5, ["insufficient_data"], "Insufficient data", "insufficient"),
            "d": row(60, [], "Good"), "e": row(60, [], "Good")}
    cur = {"a": row(70, [], "Strong"), "b": row(60, [], "Good"), "c": row(55, [], "Good"), "d": row(58, [], "Good"), "e": row(60, [], "Good")}
    result = impact.run(base, cur)
    assert result["changed"] == 4
    assert result["classes"] == {"visa_or_language": 2, "insufficient_data": 1, "other": 1}
    assert result["otherIds"] == ["d"]  # a change outside the intended classes: the tool exits 1 on it
    assert impact.classify(base["e"]) == "other"


def srow(score, before, caps=(), band="Weak", **extra):
    return {"score": score, "scoreBeforeCaps": before, "band": band, "dataStatus": "sufficient", "capsFired": list(caps), **extra}


def test_explain_accepts_only_a_removed_cap_and_names_the_rest():
    base = {"a": srow(45, 70, ["visa:needs_visa_silent"]), "b": srow(40, 70, ["visa:needs_visa_silent", "unrelated_title"]),
            "c": srow(45, 70, ["visa:needs_visa_silent"]), "d": srow(45, 70, ["visa:needs_visa_silent"]),
            "e": srow(45, 70, ["visa:needs_visa_silent"]), "old": srow(5, 5, ["insufficient_data"], "Insufficient data") | {"dataStatus": "insufficient"}}
    cur = {"a": srow(70, 70, [], "Strong"),                                  # cap removed: explained
           "b": srow(40, 70, ["unrelated_title"]),                             # still held by the title cap: unchanged
           "c": srow(60, 70, [], "Good"),                                      # lifted less than the cap removal allows: unexplained
           "d": srow(78, 78, [], "Strong", judgeAdjustment=8),                 # a cached judgement lifted it: judge, its pre-cap moves with it
           "e": srow(70, 71, [], "Strong"),                                    # the pre-cap score itself changed: a stop
           "old": srow(60, 60, [], "Good")}
    out = impact.explain(base, cur)
    assert out["explainedByCaps"] == 2 and out["oldInsufficientSkipped"] == 1  # a, and e (whose pre-cap move is flagged separately)
    assert out["unexplained"] == ["c"] and out["judgeExplained"] == ["d"] and out["sbcChanged"] == ["e"]
