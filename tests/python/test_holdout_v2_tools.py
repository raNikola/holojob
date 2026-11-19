"""holdout-v2 selection, the unit keys kept by the variance script, and the requirement-stability tool.

Synthetic data only: every file lives in tmp_path; nothing reads or writes /srv/holojob/data; no provider is called.
"""

import json
import stat
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure_extraction_variance as mv  # noqa: E402
import measure_requirement_stability as ms  # noqa: E402
import select_holdout_v2 as sel  # noqa: E402


# --- selection --------------------------------------------------------------------------------------------------------

def make_rows(n_product=30, n_delivery=20, n_other=10):
    rows = []
    titles = ([("Senior Product Manager", n_product), ("Technical Program Manager", n_delivery), ("Software Engineer", n_other)])
    n = 0
    for title, count in titles:
        for _ in range(count):
            n += 1
            rows.append({"jobId": f"{n:016x}", "title": title, "company": "Acme", "jobUrl": f"https://jobs.example/{n}",
                         "description": "Body. " * 20})
    return rows


def write_inputs(tmp_path, rows, labelled=(), v1=(), ex1=()):
    data = tmp_path / "data"
    (data / "jobs").mkdir(parents=True)
    (data / "calibration" / "stage-a").mkdir(parents=True)
    (data / "jobs" / "discovered_jobs.json").write_text(json.dumps({"jobs": rows}))
    (data / "calibration" / "stage-a" / "eval-set.json").write_text(json.dumps({"ads": {i: {} for i in labelled}}))
    (tmp_path / "v1.json").write_text(json.dumps({"ids": list(v1)}))
    (tmp_path / "ex1.json").write_text(json.dumps({"ids": list(ex1)}))
    return data


def run(tmp_path, data, seed=7):
    out, sheet = tmp_path / "sel.json", tmp_path / "sheet.md"
    code = sel.main(["--data-dir", str(data), "--seed", str(seed), "--selection", str(out), "--sheet", str(sheet),
                     "--holdout-v1", str(tmp_path / "v1.json"), "--extract-selection", str(tmp_path / "ex1.json")])
    return code, out, sheet








def test_a_short_stratum_stops_and_writes_nothing(tmp_path, capsys):
    data = write_inputs(tmp_path, make_rows(n_other=5))
    code, out, sheet = run(tmp_path, data)
    assert code == 1
    assert not out.exists() and not sheet.exists()
    assert "other" in capsys.readouterr().err


def test_the_draw_does_not_depend_on_score_rank_cap_or_band(tmp_path):
    rows = make_rows()
    data = write_inputs(tmp_path, rows)
    _, out, _ = run(tmp_path, data)
    plain = json.loads(out.read_text())["ids"]
    for i, r in enumerate(rows):
        r.update({"matchScore": (i * 37) % 100, "matchLabel": "Strong", "scoreBeforeCaps": 99 - i, "llmFacts": {"roleTrack": "x"}})
    (data / "jobs" / "discovered_jobs.json").write_text(json.dumps({"jobs": rows}))
    _, out, _ = run(tmp_path, data)
    assert json.loads(out.read_text())["ids"] == plain






# --- unit keys ---------------------------------------------------------------------------------------------------------

def req(quote, importance="must", kind="skill", id_=None, provisional=True):
    return {"text": "paraphrase", "postingQuote": quote, "importance": importance, "kind": kind,
            "id": id_ or "prov-x", "provisional": provisional}


def test_unit_keys_are_text_free_and_stable_across_case_and_punctuation():
    a = mv.unit_keys({"requirements": [req("Own the Roadmap, end-to-end!")]})
    b = mv.unit_keys({"requirements": [req("own the roadmap end to end")]})
    assert a[0]["key"] == b[0]["key"] and a[0]["key"].startswith("q:") and len(a[0]["key"]) == 14
    assert "roadmap" not in json.dumps(a).lower()






# --- stability -----------------------------------------------------------------------------------------------------------

def unit(key, importance="must", kind="skill", canonical=False):
    return {"key": key, "canonical": canonical, "kind": kind, "importance": importance}












def test_matcher_prepare_reads_facts_from_the_scratch_ledger(tmp_path):
    import measure_holdout_matcher as hm
    scratch = tmp_path / "scratch"
    (scratch / "jobs").mkdir(parents=True)
    (scratch / "jobs" / "discovered_jobs.json").write_text(json.dumps({"generation": 1, "jobs": []}))
    job = lambda i: {"jobId": i, "title": "Technical Program Manager", "company": "Acme", "description": "Run delivery. " * 10}  # noqa: E731
    reqs = [{"id": "agile", "text": "t", "kind": "skill", "importance": "must", "postingQuote": "q"}]
    ledger = {"generation": 1, "jobs": {
        "a": {"job": job("a"), "llmFacts": {"requirements": reqs}},
        "b": {"job": job("b"), "llmFacts": {"requirements": []}},
        "c": {"job": job("c")},
    }}
    (scratch / "jobs" / "job_history.json").write_text(json.dumps(ledger))
    items, facts, counts = hm.facts_from_scratch(scratch, ["a", "b", "c", "missing"])
    assert [i["jobId"] for i in items] == ["a"] and list(facts) == ["a"] and "llmFacts" not in items[0]
    assert counts == {"ids": 4, "found": 3, "noFacts": 1, "noRequirements": 1, "prepared": 1}


def test_matcher_wrapper_refuses_a_scratch_dir_inside_the_real_data_dir(tmp_path, capsys):
    import measure_holdout_matcher as hm
    real = tmp_path / "data"
    (real / "scratch").mkdir(parents=True)
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({"ids": []}))
    code = hm.main(["--ids", str(ids), "--scratch", str(real / "scratch"), "--data-dir", str(real), "--max-usd", "0.1"])
    assert code == 2 and "refused" in capsys.readouterr().err
    assert hm.main(["--ids", str(ids), "--scratch", str(tmp_path / "s"), "--data-dir", str(real), "--max-usd", "0"]) == 2


def test_main_prints_a_report_without_writing(tmp_path, capsys):
    f = tmp_path / "v.json"
    f.write_text(json.dumps({"unitKeysVersion": 1, "unitKeys": {"a": [[unit("x")], [unit("x")]], "b": [[unit("x")], [unit("y")]]}}))
    before = sorted(p.name for p in tmp_path.iterdir())
    assert ms.main([str(f)]) == 0
    out = capsys.readouterr().out
    assert "allUnits" in out and "specificMustUnits" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert ms.main([str(tmp_path / "missing.json")]) == 2
