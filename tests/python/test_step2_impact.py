"""measure_step2_impact: every changed ad is classified from the frozen baseline's capsFired; anything else stops the package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import measure_step2_impact as impact  # noqa: E402


def row(score, caps=(), band="Weak", status="sufficient"):
    return {"score": score, "band": band, "dataStatus": status, "capsFired": list(caps)}


def test_changed_ads_are_classified_by_the_baselines_caps_and_other_is_reported():
    base = {"a": row(45, ["visa:needs_visa_silent"]), "b": row(25, ["language"], "Reject"), "c": row(5, ["insufficient_data"], "Insufficient data", "insufficient"),
            "d": row(60, [], "Good"), "e": row(60, [], "Good")}
    cur = {"a": row(70, [], "Strong"), "b": row(60, [], "Good"), "c": row(55, [], "Good"), "d": row(58, [], "Good"), "e": row(60, [], "Good")}
    result = impact.run(base, cur)
    assert result["changed"] == 4
    assert result["classes"] == {"visa_or_language": 2, "insufficient_data": 1, "other": 1}
    assert result["otherIds"] == ["d"]  # a change outside the intended classes: the tool exits 1 on it
    assert impact.classify(base["e"]) == "other"
