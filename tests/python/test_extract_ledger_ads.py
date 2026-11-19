"""extract_ledger_ads: only ledger ads without current facts are read, and the ledger is backed up privately first (synthetic data, temp dir only)."""

import stat

import enrich_jobs as ej
import extract_ledger_ads as x


def job(i, **extra):
    return {"jobId": i, "title": f"Role {i}", "description": f"Ad text {i}", **extra}


def test_only_unread_open_ledger_ads_are_selected():
    read = job("read")
    ledger = {"jobs": {
        "new": {"job": job("new")},
        "read": {"job": read, "llmFacts": {"_fingerprint": ej._fingerprint(read)}},
        "closed": {"job": job("closed", isClosed=True)},
        "stale": {"job": job("stale"), "llmFacts": {"_fingerprint": "an older prompt"}},
    }}
    rows, counts = x.pending_of(ledger, {"new", "read", "closed", "stale", "absent"})
    assert [r["jobId"] for r in rows] == ["new", "stale"]
    assert counts == {"wanted": 5, "notInLedger": 1, "alreadyRead": 1, "closedOrNotFound": 1, "toRead": 2}


def test_backup_is_private_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(x, "BACKUP_DIR", tmp_path / "backups")
    ledger = tmp_path / "job_history.json"
    ledger.write_text("{}", encoding="utf-8")
    first, second = x.backup(ledger), x.backup(ledger)
    assert first != second and first.read_text() == "{}"
    assert stat.S_IMODE(first.stat().st_mode) == 0o600 and stat.S_IMODE(first.parent.stat().st_mode) == 0o700
