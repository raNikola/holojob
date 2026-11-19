"""The Stage A report on fictional labels and scored files in a temp directory (read-only: it must write nothing)."""

import json

import pytest

from calibration import report as rp


def label(overall, function="yes", hard="unknown", source="confirmed"):
    return {"functionFit": function, "hardRequirements": hard, "overall": overall, "source": source}


def job(job_id, band, score, reasons=None, skill=60, engine=None, title=None):
    row = {"jobId": job_id, "title": title or f"Title {job_id}", "matchLabel": band, "matchScore": score, "reasons": reasons or [],
           "scoreBreakdown": {"skillMatch": {"raw": skill}}}
    if engine:
        row["engineShadow"] = {"label": engine}
    return row


TITLE_CAP = ["Capped: the title matches no target role"]


@pytest.fixture
def stage(tmp_path):
    labels = {"a": label(0, "no"), "b": label(2, "yes"), "c": label(0, "yes", "no"), "d": label(3), "e": label(2, "yes")}
    (tmp_path / "ran-labels.json").write_text(json.dumps({"version": 1, "revision": 5, "labels": labels}))
    (tmp_path / "sample.json").write_text(json.dumps({"jobIds": list("abcdef")}))
    (tmp_path / "rescored").mkdir()
    rows = [job("a", "Weak", 40, TITLE_CAP), job("b", "Weak", 40, TITLE_CAP, skill=20), job("c", "Good", 65),
            job("d", "Strong", 78), job("e", "Good", 60, engine="Incomplete")]
    (tmp_path / "rescored" / "scored_jobs.json").write_text(json.dumps({"jobs": rows}))
    proposals = {"a": {"status": "ok", "functionFit": "no", "hardRequirements": "unknown", "overall": 0, "confidence": "high"},
                 "b": {"status": "ok", "functionFit": "partial", "hardRequirements": "unknown", "overall": 2, "confidence": "low"},
                 "c": {"status": "invalid"}}
    (tmp_path / "ai-proposals.json").write_text(json.dumps({"proposals": proposals}))
    return tmp_path




def test_band_comparison_counts_errors_and_names_the_mechanical_category(stage):
    system = rp.build(stage)["systems"]["matchScore (re-score of the frozen baseline)"]
    c = system["bands"]
    # a: owner 0 / Weak=1 (over, wrong function). b: owner 2 / Weak=1 (under, title cap). c: owner 0 / Good=2 (over, requirements).
    # d: 3/3. e: 2/Good=2.
    assert (c["n"], c["exact"], c["over"], c["under"], c["irrelevantAtGoodOrAbove"], c["relevantAtWeakOrBelow"]) == (5, 2, 2, 1, 1, 1)
    assert c["errors"] == {"over: requirements not met, scored high": ["c"], "over: wrong kind of work scored high": ["a"],
                           "under: unrelated-title cap on a relevant function": ["b"]}
    assert system["views"]["wrong function"] == {"n": 1, "systemBands": {"Weak": 1}, "unrelatedTitleCap": 1}
    assert system["views"]["relevant function, requirements not met"]["systemBands"] == {"Good": 1}






def test_render_prints_ids_and_counts_only_and_the_run_writes_nothing(stage, capsys):
    before = {p.name: p.read_bytes() for p in stage.rglob("*") if p.is_file()}
    assert rp.main(["--out", str(stage)]) == 0
    text = capsys.readouterr().out
    assert "labelled 5 of 6" in text and "holdout: not drawn" in text and "description" not in text.lower()
    assert {p.name: p.read_bytes() for p in stage.rglob("*") if p.is_file()} == before


