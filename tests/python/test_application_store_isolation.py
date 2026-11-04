"""The application store is independent of discovery (TRACKER_PLAN 6a, Python side)."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import job_history as jh
from dedupe_jobs import _crosspost_key

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_no_python_code_names_the_application_store():
    hits = [str(p.relative_to(REPO)) for p in (REPO / "python").rglob("*.py")
            if "data/applications" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == []


def test_an_application_survives_the_ledger_pruning_its_job(tmp_path):
    store = tmp_path / "data/applications/applications.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"version": 1, "applications": {"app-0123456789abcdef": {
        "id": "app-0123456789abcdef", "posting": {"jobId": "g1", "title": "Product Manager"},
        "events": [{"id": "app-0123456789abcdef:1", "seq": 1, "type": "applied"}]}}}), encoding="utf-8")
    before = hashlib.sha256(store.read_bytes()).hexdigest()

    ledger_file = tmp_path / "data/jobs/job_history.json"
    ledger_file.parent.mkdir(parents=True)
    ledger = jh.empty_ledger()
    job = {"jobId": "g1", "provider": "greenhouse", "title": "Product Manager", "company": "Acme",
           "location": "Berlin", "description": "Own the roadmap.", "jobUrl": "https://x/g1"}
    providers = {"greenhouse": 1}
    for days, jobs in ((0, [job]), (1, []), (2, []), (2 + jh.PRUNE_AFTER_DAYS + 1, [])):
        jh.apply_run(ledger, jobs, now=(T0 + timedelta(days=days)).isoformat(), providers_returned=providers,
                     key="search-a", role_key=_crosspost_key, board_evidence={"greenhouse": {None: {"complete": True, "listed": set()}}})
        jh.save(ledger_file, ledger)

    assert "g1" not in jh.load(ledger_file)["jobs"]
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before
