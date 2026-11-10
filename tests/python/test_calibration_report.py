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


def test_spearman_handles_ties_and_degenerate_input():
    assert rp.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert rp.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert rp.spearman([1, 1, 1], [1, 2, 3]) is None and rp.spearman([1, 2], [1, 2]) is None


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


def test_engine_is_compared_only_when_the_file_has_engine_output(stage):
    system = rp.build(stage)["systems"]["matchScore (re-score of the frozen baseline)"]
    assert system["engine"]["n"] == 0 and system["engineIncomplete"] == 1  # the one engine answer is Incomplete: left out
    assert any("left out" in line for line in rp.render(rp.build(stage)))
    other = stage / "engine.json"
    other.write_text(json.dumps({"jobs": [job("a", "Weak", 40, engine="Weak"), job("d", "Strong", 78, engine="Strong")]}))
    both = rp.build(stage, {"with engine": other})["systems"]["with engine"]
    assert both["engine"]["n"] == 2 and both["engine"]["exact"] == 2


def test_ai_agreement_is_per_judgment_and_ignores_invalid_answers(stage):
    ai = rp.build(stage)["ai"]
    assert ai["n"] == 2 and ai["invalid"] == 1
    assert (ai["function"], ai["requirements"], ai["overall"]) == (0.5, 1.0, 1.0)
    assert ai["overallAgreementByConfidence"] == {"high": [1, 1], "low": [1, 1]}


def test_render_prints_ids_and_counts_only_and_the_run_writes_nothing(stage, capsys):
    before = {p.name: p.read_bytes() for p in stage.rglob("*") if p.is_file()}
    assert rp.main(["--out", str(stage)]) == 0
    text = capsys.readouterr().out
    assert "labelled 5 of 6" in text and "holdout: not drawn" in text and "description" not in text.lower()
    assert {p.name: p.read_bytes() for p in stage.rglob("*") if p.is_file()} == before


def test_no_labels_yet_says_so(tmp_path):
    (tmp_path / "sample.json").write_text(json.dumps({"jobIds": ["a"]}))
    assert rp.render(rp.build(tmp_path))[-1] == "no confirmed labels yet: nothing to compare"
