"""Holdout extraction and comparison scripts (scripts/measure_holdout_*.py). Every test builds a temp data dir; none touches
/srv/holojob/data, and no test calls a provider."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure_common as mc  # noqa: E402
import measure_holdout_compare as hc  # noqa: E402
import measure_holdout_extract as he  # noqa: E402

IDS = [f"{n:016x}" for n in range(1, 21)]


def ledger_doc(descriptions):
    jobs = {}
    for i, desc in zip(IDS, descriptions):
        jobs[i] = {"job": {"jobId": i, "title": "Technical Program Manager", "company": "Acme", "location": "Remote", "description": desc,
                           "jobUrl": f"https://jobs.example/{i}", "provider": "jobspy"}}
    return {"generation": 1, "jobs": jobs}


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "jobs").mkdir(parents=True)
    (d / "jobs" / "discovered_jobs.json").write_text(json.dumps({"generation": 1, "jobs": []}))
    (d / "jobs" / "job_history.json").write_text(json.dumps(ledger_doc(["Run delivery. " * 20] * 20)))
    return d


@pytest.fixture
def ids_file(tmp_path):
    p = tmp_path / "ids.json"
    p.write_text(json.dumps({"ids": IDS}))
    return p


def snapshot(root):
    return {str(p): p.stat().st_mtime_ns for p in Path(root).rglob("*") if p.is_file()}


# --- extract ---------------------------------------------------------------------------------------------------------

PRICED = {"priceKnown": True, "provider": "p", "model": "m", "ads": 20, "runsPerAd": 1, "calls": 20, "inputOnlyUsd": 0.01, "worstCaseUsd": 0.1}


def test_extract_without_confirm_writes_nothing_and_calls_nothing(data_dir, ids_file, tmp_path, monkeypatch, capsys):
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(he.mv, "estimate", lambda *a, **k: PRICED)
    monkeypatch.setattr(he.mv, "run_extractions", lambda *a, **k: pytest.fail("a provider call was made"))
    before = snapshot(data_dir)
    code = he.main(["--ids", str(ids_file), "--scratch", str(scratch), "--data-dir", str(data_dir), "--max-usd", "0.15"])
    assert code == 0
    assert not scratch.exists()
    assert snapshot(data_dir) == before
    assert "Nothing was called" in capsys.readouterr().out


def test_extract_requires_max_usd(data_dir, ids_file, tmp_path):
    with pytest.raises(SystemExit):
        he.main(["--ids", str(ids_file), "--scratch", str(tmp_path / "s"), "--data-dir", str(data_dir)])


def test_extract_refuses_when_an_ad_has_no_text(data_dir, ids_file, tmp_path, monkeypatch, capsys):
    (data_dir / "jobs" / "job_history.json").write_text(json.dumps(ledger_doc(["text " * 20] * 19 + [""])))
    monkeypatch.setattr(he.mv, "estimate", lambda *a, **k: pytest.fail("priced although a text is missing"))
    code = he.main(["--ids", str(ids_file), "--scratch", str(tmp_path / "s"), "--data-dir", str(data_dir), "--max-usd", "0.15", "--confirm"])
    assert code == 1
    assert IDS[-1] in capsys.readouterr().err
    assert not (tmp_path / "s").exists()


def test_extract_refuses_an_unknown_price(data_dir, ids_file, tmp_path, monkeypatch):
    monkeypatch.setattr(he.mv, "estimate", lambda *a, **k: {"priceKnown": False})
    monkeypatch.setattr(he.mv, "run_extractions", lambda *a, **k: pytest.fail("called"))
    code = he.main(["--ids", str(ids_file), "--scratch", str(tmp_path / "s"), "--data-dir", str(data_dir), "--max-usd", "0.15", "--confirm"])
    assert code == 1
    assert not (tmp_path / "s").exists()


def test_extract_refuses_a_worst_case_above_the_cap(data_dir, ids_file, tmp_path, monkeypatch):
    monkeypatch.setattr(he.mv, "estimate", lambda *a, **k: {**PRICED, "worstCaseUsd": 0.5})
    monkeypatch.setattr(he.mv, "run_extractions", lambda *a, **k: pytest.fail("called"))
    code = he.main(["--ids", str(ids_file), "--scratch", str(tmp_path / "s"), "--data-dir", str(data_dir), "--max-usd", "0.15", "--confirm"])
    assert code == 1
    assert not (tmp_path / "s").exists()


def test_scratch_inside_or_equal_to_the_real_data_dir_is_refused(data_dir):
    for bad in (data_dir, data_dir / "holdout", data_dir.parent):
        with pytest.raises(SystemExit):
            he.check_scratch(bad, data_dir)


def test_store_facts_writes_only_in_the_scratch_ledger(data_dir, tmp_path):
    scratch = tmp_path / "scratch"
    he.prepare_scratch(scratch, data_dir)
    assert (scratch.stat().st_mode & 0o777) == 0o700
    real = snapshot(data_dir)
    assert he.store_facts(scratch, {IDS[0]: [{"_fingerprint": "x", "workMode": "remote"}], IDS[1]: []}) == 1
    led = json.loads((scratch / "jobs" / "job_history.json").read_text())
    assert led["jobs"][IDS[0]]["llmFacts"]["workMode"] == "remote"
    assert led["jobs"][IDS[0]]["job"]["llmFacts"]["workMode"] == "remote"
    assert "llmFacts" not in led["jobs"][IDS[1]]
    assert led["generation"] == 1
    assert snapshot(data_dir) == real


# --- compare ---------------------------------------------------------------------------------------------------------

RATINGS = """| rank | verdict | id | company / title | primary driver | reason |
|---|---|---|---|---|---|
| 1 | apply | {a1} | Alpha, TPM | FIT | good |
| 2 | apply | {a2} | Beta, PM | FIT | good |
| 3 | maybe | {m1} | Gamma, PM | ELIG | German mandatory |
| 4 | skip | {s1} | Nebius, Engineer | FIT | not PM |
| 5 | skip | {s2} | Parker Hannifin, Technical PM | FIT | no |
| 6 | skip | {s3} | Qualcomm, PM | ELIG | sponsorship excluded |
| 7 | skip | {s4} | Zebra, TPM | ELIG | Spanish likely required |

## Success criterion

PROPOSAL, not yet approved by the owner.

1. At least 1 of the APPLY ads is in the top 6.
2. No SKIP ad with primary driver FIT (Nebius, Parker TPM) ranks above any APPLY ad.
3. Stated ELIG barrier must not show as eligible.
4. Report counts out of 20.
"""


def ratings_text():
    return RATINGS.format(a1=IDS[0], a2=IDS[1], m1=IDS[2], s1=IDS[3], s2=IDS[4], s3=IDS[5], s4=IDS[6])






def ratings20():
    head, tail = ratings_text().split("\n\n## Success criterion", 1)
    rows = head.splitlines()[:2] + [f"| {n + 1} | skip | {IDS[n]} | Co{n}, PM | FIT | no |" for n in range(20)]
    return "\n".join(rows) + "\n\n## Success criterion" + tail.replace("(Nebius, Parker TPM)", "(Co1, Co2)")




def test_compare_refuses_the_real_data_dir(monkeypatch, tmp_path, ids_file):
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr(mc, "default_data_dir", lambda: real)
    ratings = tmp_path / "r.md"
    ratings.write_text(ratings20())
    before = snapshot(real)
    assert hc.main(["--data-dir", str(real), "--ratings", str(ratings), "--ids", str(ids_file), "--out", str(tmp_path / "o.md")]) == 2
    assert not (tmp_path / "o.md").exists()
    assert snapshot(real) == before


