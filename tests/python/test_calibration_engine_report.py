"""The step 7 report on fictional results in a temp folder: the two modes are never pooled."""

import json

from calibration import engine_report as er


def entry(mode, label, fit, statuses, gates=()):
    reqs = [{"id": f"r{i}", "importance": "must", "kind": "skill", "status": s} for i, s in enumerate(statuses)]
    return {"mode": mode, "excludedBy": list(gates), "label": label, "fit": fit, "output": {"requirements": reqs}}


def folder(tmp_path):
    labels = {j: {"jobId": j, "overall": o, "hardRequirements": h} for j, o, h in (
        ("a", 3, "yes"), ("b", 2, "partial"), ("c", 0, "no"), ("d", 1, "no"))}
    ads = {"a": entry("production_like", "Good", 80, ["MET", "MET"]), "b": entry("production_like", "Partial", 40, ["MET", "MISSING"]),
           "c": entry("diagnostic", "Weak", 10, ["MISSING", "MISSING"], ["role_family"]),
           "d": entry("diagnostic", "Incomplete", 0, ["UNKNOWN"], ["language"])}
    rows = {"jobs": [{"jobId": j, "matchLabel": band, "matchScore": s} for j, band, s in (
        ("a", "Strong", 80), ("b", "Good", 66), ("c", "Weak", 40), ("d", "Weak", 40))]}
    (tmp_path / "ran-labels.json").write_text(json.dumps({"version": 1, "labels": labels}))
    (tmp_path / "engine-shadow.json").write_text(json.dumps({"version": 1, "ads": ads}))
    (tmp_path / "rescored").mkdir()
    (tmp_path / "rescored" / "scored_jobs.json").write_text(json.dumps(rows))
    return tmp_path


def test_each_mode_is_counted_on_its_own_and_never_pooled(tmp_path):
    report = er.build(folder(tmp_path))
    prod, diag = report["modes"]["production_like"], report["modes"]["diagnostic"]
    assert (prod["ads"], diag["ads"]) == (2, 2)
    assert prod["labels"] == {"Good": 1, "Partial": 1} and diag["labels"] == {"Weak": 1, "Incomplete": 1}
    assert diag["excludedBy"] == {"role_family": 1, "language": 1} and prod["excludedBy"] == {}
    assert diag["levels"]["engineIncomplete"] == 1 and diag["levels"]["ads"] == 1  # Incomplete is left out, not counted wrong
    assert "pooled" not in json.dumps(report).lower()


def test_requirement_verdicts_are_grouped_by_the_owners_hard_requirements_label(tmp_path):
    prod = er.build(folder(tmp_path))["modes"]["production_like"]["requirements"]
    assert prod["yes"]["metShare"] == 1.0 and prod["partial"]["metShare"] == 0.5 and prod["partial"]["missingShare"] == 0.5
    assert "no" not in prod  # that label belongs to the diagnostic ads only


def test_the_report_labels_diagnostic_numbers_and_prints_no_text(tmp_path):
    text = "\n".join(er.render(er.build(folder(tmp_path))))
    assert "DIAGNOSTIC ONLY" in text and "what production would show" in text
    assert "description" not in text.lower()


def test_the_report_writes_nothing(tmp_path):
    folder(tmp_path)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    er.build(tmp_path)
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
