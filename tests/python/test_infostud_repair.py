"""Repair of stored Infostud ads with a cut-off description (Wave 5): dry run by default, polite, counts only. Offline, temp ledger."""

import json
from datetime import datetime, timezone
import stat
import urllib.error

import pytest

import infostud_repair as rep
import job_history as jh
from test_infostud_description import AD, TEASER, page

SCRIPT_ARGS = ["--limit", "5"]


def entry(job_id, status=None, text=TEASER, source="infostud", closed=None, facts=True):
    job = {"jobId": job_id, "source": source, "provider": source, "title": "PM", "jobUrl": f"https://x/{job_id}", "description": text}
    if status:
        job["descriptionStatus"] = status
    return {"job": job, "closedAt": closed, "llmFacts": {"requirements": [{"text": "a"}]} if facts else None}


@pytest.fixture
def root(tmp_path):
    (tmp_path / "data" / "jobs").mkdir(parents=True)
    ledger = jh.empty_ledger()
    ledger["jobs"] = {
        "legacy": entry("legacy"), "teaser": entry("teaser", "teaser"), "failed": entry("failed", "failed"),
        "done": entry("done", "complete", AD), "cut": entry("cut", "source_truncated"), "closed": entry("closed", closed="2026-01-01"),
        "other": entry("other", source="linkedin"), "long": entry("long", text="word " * 400),
    }
    jh.save(tmp_path / "data" / "jobs" / jh.LEDGER_FILE, ledger)
    return tmp_path


def served(html_by_id):
    calls = []

    def fetch(url):
        calls.append(url)
        value = html_by_id[url.rsplit("/", 1)[1]]
        if isinstance(value, Exception):
            raise value
        return value

    return fetch, calls


def test_candidates_are_teaser_failed_and_legacy_only_and_dry_run_fetches_nothing(root):
    fetch, calls = served({})
    result = rep.repair(root, fetch=fetch)
    assert result["candidates"] == 3 and result["wouldFetch"] == 3 and result["applied"] is False and calls == []
    assert result["byStatus"]["unflagged"] == 3 and "ids" not in result
    assert not (root / "data" / "backups").exists()


def test_apply_stores_full_text_backs_up_and_resets_facts_only_where_text_changed(root):
    fetch, calls = served({"legacy": page(text_ad=AD), "teaser": page(text_ad=AD), "failed": page(body="")})
    sleeps = []
    result = rep.repair(root, apply=True, fetch=fetch, sleep=sleeps.append, delay=2)
    ledger = json.loads((root / "data" / "jobs" / jh.LEDGER_FILE).read_text())
    assert result["complete"] == 2 and result["sourceTruncated"] == 1 and result["factsReset"] == 2 and len(calls) == 3
    assert ledger["jobs"]["legacy"]["job"]["descriptionStatus"] == "complete" and ledger["jobs"]["legacy"]["llmFacts"] is None
    assert ledger["jobs"]["failed"]["job"]["descriptionStatus"] == "source_truncated" and ledger["jobs"]["failed"]["llmFacts"]
    assert ledger["jobs"]["done"]["job"]["description"] == AD and ledger["jobs"]["cut"]["job"]["descriptionStatus"] == "source_truncated"
    assert len(sleeps) == 2 and all(2 <= s <= 3 for s in sleeps)
    backup = next((root / "data" / "backups").glob("infostud-description-*")) / "data" / "jobs" / jh.LEDGER_FILE
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600 and json.loads(backup.read_text())["jobs"]["legacy"]["job"]["description"] == TEASER


def test_limit_caps_requests_and_a_second_run_does_not_refetch_source_truncated(root):
    fetch, calls = served({k: page(body="") for k in ("legacy", "teaser", "failed")})
    assert rep.repair(root, limit=2, apply=True, fetch=fetch, sleep=lambda s: None)["fetched"] == 2 and len(calls) == 2
    fetch, calls = served({k: page(body="") for k in ("legacy", "teaser", "failed")})
    rep.repair(root, limit=20, apply=True, fetch=fetch, sleep=lambda s: None, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert len(calls) == 1  # only the one left; the two read as source_truncated are not fetched again


def http(code):
    error = RuntimeError("Infostud unreachable")
    error.__cause__ = urllib.error.HTTPError("u", code, "m", {}, None)
    return error


def test_429_stops_the_run_and_404_is_counted_gone(root):
    fetch, calls = served({"legacy": http(404), "teaser": http(429), "failed": page(text_ad=AD)})
    result = rep.repair(root, apply=True, fetch=fetch, sleep=lambda s: None)
    assert result["gone"] == 1 and result["stoppedEarly"] == "HTTP 429" and len(calls) == 2


def test_three_failures_in_a_row_stop_the_run(root):
    boom = RuntimeError("down")
    fetch, calls = served({"legacy": boom, "teaser": boom, "failed": boom})
    result = rep.repair(root, apply=True, fetch=fetch, sleep=lambda s: None)
    assert result["failed"] == 3 and result["stoppedEarly"] == "three failures in a row"


def test_script_prints_counts_only_and_defaults_to_dry_run(root, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("repair_script", Path(__file__).resolve().parents[2] / "scripts" / "repair-infostud-descriptions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(SCRIPT_ARGS, root=root) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["applied"] is False and "DRY RUN" in out.err
    assert TEASER not in out.out and "https://" not in out.out
