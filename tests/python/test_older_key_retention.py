"""Retention of older_key rows (Wave 4, h): the report, the plan, and the one guarded write. Offline; every path is under tmp_path."""

import json
from datetime import datetime, timedelta, timezone

import pytest

import job_history as jh
import older_key_retention as retention
import view_guard
from dedupe_jobs import _crosspost_key
from providers.base_provider import build_canonical_job

NOW = datetime(2027, 6, 1, 12, 0, tzinfo=timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def ad(n, provider="jobspy"):
    return build_canonical_job(provider=provider, source=provider, title=f"Product Manager {n}", company=f"Co{n}", location="Remote",
                               job_url=f"https://{provider}.example/{n}", description="Own the roadmap. " * 30, is_remote=True, scraped_at=iso(0))


def apply(ledger, jobs, days_ago, key, run_id):
    return jh.apply_run(ledger, jobs, now=iso(days_ago), providers_returned={"jobspy": len(jobs)}, key=key, role_key=_crosspost_key,
                        run_id=run_id, prune=False)


def meta():
    return {"searchTerms": [], "locations": [], "remoteFilters": [], "country": "Serbia", "providers": ["jobspy"], "providerCounts": {"jobspy": 1},
            "rawCount": 1, "dedupedCount": 1, "history": {}, "sourceRunId": "r2"}


@pytest.fixture
def world(tmp_path):
    """Four ads seen under an old search key at different ages, one found by the current search. Returns (root, ids)."""
    old = {name: ad(i) for i, name in enumerate(("a_old", "b_old", "c_old", "d_mid"), start=1)}
    new = ad(9)
    ledger = jh.empty_ledger()
    apply(ledger, [old["a_old"], old["b_old"], old["c_old"]], 400, "K1", "r0")   # 400 days ago
    apply(ledger, [old["d_mid"]], 100, "K1", "r1")                               # 100 days ago
    apply(ledger, [new], 1, "K2", "r2")
    ledger["lastImport"] = {"runId": "r2", "at": iso(1), "startedAt": iso(1), "meta": meta(), "marksNotFound": True}
    ledger["generation"] = 3
    path = tmp_path / "data/jobs/job_history.json"
    path.parent.mkdir(parents=True)
    jh.save(path, ledger)
    ids = {name: job["jobId"] for name, job in {**old, "new": new}.items()}
    return tmp_path, ids


def load(root):
    return jh.load(root / "data/jobs/job_history.json", read_only=True)


def test_only_older_key_rows_are_counted_and_by_age(world):
    root, ids = world
    out = retention.report(load(root), root, now=NOW)
    assert out["olderKey"] == 4 and out["ledgerRows"] == 5
    assert out["byAge"]["366d+"] == 3 and out["byAge"]["91-180d"] == 1
    assert out["byProvider"] == {"jobspy": 4}
    assert out["wouldRemove"] == {"90": 4, "180": 3, "365": 3}
    assert out["applicationsJoined"] is False and out["protectIdsGiven"] is False


def test_the_window_decides_and_a_row_without_a_date_is_never_a_candidate(world):
    root, ids = world
    ledger = load(root)
    assert set(retention.plan(ledger, root, days=180, now=NOW)["candidates"]) == {ids["a_old"], ids["b_old"], ids["c_old"]}
    assert retention.plan(ledger, root, days=500, now=NOW)["candidates"] == []
    for field in ("lastSeen", "firstSeen"):
        ledger["jobs"][ids["a_old"]].pop(field)
    out = retention.plan(ledger, root, days=180, now=NOW)
    assert ids["a_old"] not in out["candidates"] and out["ageUnknown"] == 1


def test_a_row_the_current_search_found_is_never_a_candidate(world):
    root, ids = world
    assert ids["new"] not in retention.plan(load(root), root, days=0, now=NOW)["candidates"]


def test_each_kind_of_protection_keeps_the_row(world):
    root, ids = world
    (root / "data/resumes" / ids["a_old"]).mkdir(parents=True)                     # tailored documents
    (root / "data/jobs/rescored_kept.json").write_text(json.dumps({"version": 1, "ids": {ids["b_old"]: {}}}))   # Keep re-score
    out = retention.plan(load(root), root, days=180, now=NOW, application_ids={ids["c_old"]}, protect_ids=set())
    assert out["candidates"] == [] and out["protected"] == 3
    assert out["protectedBy"] == {"application": 1, "protect_ids_file": 0, "kept_rescore": 1, "backend_user_data": 1}
    out = retention.plan(load(root), root, days=180, now=NOW, application_ids=set(), protect_ids={ids["c_old"]})
    assert out["protectedBy"]["protect_ids_file"] == 1


def test_parse_ids_reads_one_per_line_and_ignores_comments(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("a1\n\n# note\nb2  # trailing\n  c3  \n")
    assert retention.parse_ids(f) == {"a1", "b2", "c3"} and retention.parse_ids(None) is None


def test_the_report_prints_no_title(world, capsys):
    import importlib.util
    from pathlib import Path
    root, _ = world
    spec = importlib.util.spec_from_file_location("report_script", Path(__file__).resolve().parents[2] / "scripts/older-key-report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--root", str(root)]) == 0
    captured = capsys.readouterr()
    assert "Product Manager" not in captured.out + captured.err and "INVISIBLE" in captured.err
