"""--ids limits an enrichment run to an explicit list of ad ids (the paid top-N extraction)."""
import json
import sys

import pytest

import enrich_jobs
from conftest import select_provider

pytestmark = pytest.mark.usefixtures("open_ai_budget")


def ad(job_id):
    return {"jobId": job_id, "title": f"Product Manager {job_id}", "company": "Acme", "location": "Berlin, Germany",
            "description": "Own the roadmap."}


def dry_run(tmp_path, monkeypatch, capsys, ids_payload):
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [ad("a"), ad("b"), ad("c")]}), encoding="utf-8")
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps(ids_payload), encoding="utf-8")
    intel = tmp_path / "intel.json"
    intel.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs), "--intelligence", str(intel),
                                      "--ledger", str(tmp_path / "ledger.json"), "--ids", str(ids), "--dry-run"])
    select_provider(tmp_path, monkeypatch, "claude-code")
    assert enrich_jobs.main() == 0
    return capsys.readouterr().out


def test_only_the_listed_ads_are_read_and_unknown_ids_are_counted(tmp_path, monkeypatch, capsys):
    out = dry_run(tmp_path, monkeypatch, capsys, {"ids": ["a", "c", "zzz"]})
    assert "--ids: 3 ids, 2 found" in out
    assert "to read now (model calls): 2" in out
    assert "kept as they are: 0 cached" in out


def test_a_bare_list_works_too(tmp_path, monkeypatch, capsys):
    out = dry_run(tmp_path, monkeypatch, capsys, ["b"])
    assert "to read now (model calls): 1" in out
