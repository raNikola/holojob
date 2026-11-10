"""The eval report on fictional results in a temp folder: modes never pooled, split respected, no text printed."""

import json

from calibration import eval_report as er
from calibration import eval_set as es

SECTIONS = {"education": 1, "certification": 1, "language": 1}
GATES = [{"gate": g, "result": "pass"} for g in ("work_authorization", "location", "language", "salary_floor", "role_family")]


def req(n, status, kind="skill", importance="must"):
    return {"id": f"r{n}", "text": "SECRET REQUIREMENT TEXT", "kind": kind, "importance": importance, "status": status, "strength": 3, "quoteVerified": True}


def make(tmp_path):
    ads, labels, rows, items, line_labels, k = {}, {}, [], [], {}, 0
    for i in range(12):
        job = f"ad{i}"
        mode = "production_like" if i % 2 == 0 else "diagnostic"
        statuses = ["MET", "PARTIAL", "MISSING", "UNKNOWN"] if i % 3 else ["MET", "MET", "MISSING", "MISSING"]
        reqs = [req(n, s, "certification" if n == 2 else "skill") for n, s in enumerate(statuses)]
        ads[job] = {"mode": mode, "label": "Partial", "fit": 20 + i, "bucket": "apply", "gates": GATES, "output": {"requirements": reqs}}
        labels[job] = {"jobId": job, "overall": i % 4, "functionFit": "yes", "hardRequirements": "partial"}
        rows.append({"jobId": job, "matchLabel": "Good", "matchScore": 60 + i})
        for r in reqs[:2]:
            k += 1
            items.append({"itemId": f"i{k:02d}", "jobId": job, "kind": r["kind"], "mode": mode, "probe": False, "importance": "must",
                          "class": "neutral", "text": "SECRET", "verdict": {"status": r["status"], "strength": 3, "evidenceQuote": "x"}})
            line_labels[f"i{k:02d}"] = {"first": {"isMust": "yes", "meets": "yes"}, "final": {"isMust": "yes", "meets": "yes"}}
    (tmp_path / "ran-labels.json").write_text(json.dumps({"labels": labels}))
    (tmp_path / "ran-must-labels.json").write_text(json.dumps({"labels": line_labels}))
    (tmp_path / "must-sample.json").write_text(json.dumps({"items": items, "strata": []}))
    (tmp_path / "engine-shadow.json").write_text(json.dumps({"ads": ads}))
    (tmp_path / "rescored").mkdir()
    (tmp_path / "rescored" / "scored_jobs.json").write_text(json.dumps({"jobs": rows}))
    es.freeze(tmp_path)
    return tmp_path


def test_each_mode_is_reported_on_its_own_and_the_split_filters_the_ads(tmp_path):
    out = make(tmp_path)
    everything = er.build(out, "all", SECTIONS)
    assert everything["ads"]["production_like"]["ads"] == 6 and everything["ads"]["diagnostic"]["ads"] == 6
    dev, test = er.build(out, "dev", SECTIONS), er.build(out, "test", SECTIONS)
    for mode in er.MODES:
        assert dev["ads"][mode]["ads"] + test["ads"][mode]["ads"] == 6
    assert "pooled" not in json.dumps(everything).lower()


def test_three_systems_are_compared_on_the_same_ads(tmp_path):
    a = er.build(make(tmp_path), "all", SECTIONS)["ads"]["production_like"]
    assert set(a["systems"]) == {"matchScore", "engine", "preview"} and all(s["n"] == 6 for s in a["systems"].values())
    assert a["previewDetail"]["adsWithUnconfirmedMusts"] == 6


def test_the_line_view_types_the_verdicts_and_counts_the_fit_lowering_errors(tmp_path):
    lines = er.build(make(tmp_path), "all", SECTIONS)["lines"]["production_like"]
    typing = lines["newTyping"]
    assert typing["realMusts"] == lines["mustLines"] and lines["precision"]["precision"] == 1.0
    assert typing["contradictedButOwnerMeetsIt (fit-lowering error)"] == 0  # the fixture lines are MET or PARTIAL only


def test_a_changed_label_file_is_warned_about_and_the_report_prints_no_text(tmp_path, capsys):
    out = make(tmp_path)
    doc = json.loads((out / "ran-labels.json").read_text())
    doc["labels"]["ad0"]["overall"] = 3
    (out / "ran-labels.json").write_text(json.dumps(doc))
    text = "\n".join(er.render(er.build(out, "all", SECTIONS)))
    assert "WARNING: live label files changed" in text and "CAVEAT" in text and "not proof of reliability" in text.lower()
    assert "SECRET" not in text


def test_the_report_writes_nothing(tmp_path):
    out = make(tmp_path)
    before = sorted(p.name for p in out.rglob("*"))
    er.build(out, "all", SECTIONS)
    assert sorted(p.name for p in out.rglob("*")) == before
