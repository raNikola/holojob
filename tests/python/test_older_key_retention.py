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


# --- the guarded write ------------------------------------------------------------------------------------------------------


def run_prune(root, apply, days=180, app=frozenset(), protect=frozenset(), store_sha="current"):
    sha = retention.live_store_sha(root) if store_sha == "current" else store_sha
    return retention.prune(root, days=days, now=NOW, application_ids=set(app), protect_ids=set(protect), apply=apply, stamp="t1", store_sha=sha)


def test_a_dry_run_changes_nothing(world):
    root, ids = world
    before = (root / "data/jobs/job_history.json").read_bytes()
    out = run_prune(root, apply=False)
    assert len(out["candidates"]) == 3 and out["applied"] is False
    assert (root / "data/jobs/job_history.json").read_bytes() == before and not (root / "data/backups").exists()


def test_apply_refuses_without_both_id_lists(world):
    root, _ = world
    before = (root / "data/jobs/job_history.json").read_bytes()
    for app, protect in ((None, set()), (set(), None), (None, None)):
        with pytest.raises(SystemExit, match="refusing --apply"):
            retention.prune(root, days=180, now=NOW, application_ids=app, protect_ids=protect, apply=True)
    assert (root / "data/jobs/job_history.json").read_bytes() == before


def test_apply_backs_up_first_removes_only_candidates_and_leaves_the_view_alone(world):
    root, ids = world
    ledger_before = load(root)
    view_before = view_guard.derive_view(ledger_before)
    out = run_prune(root, apply=True, protect={ids["b_old"]})
    after = load(root)
    assert out["applied"] is True and out["removed"] == 2
    assert set(ledger_before["jobs"]) - set(after["jobs"]) == {ids["a_old"], ids["c_old"]}
    assert ids["b_old"] in after["jobs"] and ids["d_mid"] in after["jobs"] and ids["new"] in after["jobs"]
    assert after["lastImport"] == ledger_before["lastImport"] and after["generation"] == ledger_before["generation"]
    assert view_guard.derive_view(after) == view_before
    backup = root / out["backup"]
    assert json.loads((backup / "data/jobs/job_history.json").read_text())["jobs"].keys() == ledger_before["jobs"].keys()
    assert set((backup / "removed-ids.txt").read_text().split()) == {ids["a_old"], ids["c_old"]}
    assert (backup / "manifest.json").exists() and oct(backup.stat().st_mode & 0o777) == "0o700"
    assert oct((backup / "removed-ids.txt").stat().st_mode & 0o777) == "0o600"


def test_a_second_apply_has_nothing_left_to_remove(world):
    root, _ = world
    run_prune(root, apply=True)
    again = run_prune(root, apply=True)
    assert again["candidates"] == [] and again["applied"] is False


def test_a_busy_pipeline_stops_the_prune(world):
    import pipeline_lock
    root, _ = world
    lock = pipeline_lock.acquire(path=root / "data/jobs/.pipeline.lock")
    try:
        with pytest.raises(SystemExit):
            run_prune(root, apply=True)
    finally:
        lock.release()
    assert len(load(root)["jobs"]) == 5


def test_the_cli_requires_days_and_prints_no_titles(world, capsys):
    import importlib.util
    from pathlib import Path
    root, _ = world
    spec = importlib.util.spec_from_file_location("prune_script", Path(__file__).resolve().parents[2] / "scripts/prune-older-key.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit):
        module.main([], root=root)
    assert module.main(["--days", "180"], root=root) == 0
    captured = capsys.readouterr()
    assert "Product Manager" not in captured.out and "DRY RUN" in captured.err and len(load(root)["jobs"]) == 5


# --- the application export must match the live store (Wave 6) -------------------------------------------------------------


def _store(root, text='{"version":1,"applications":{}}'):
    file = root / "data/applications/applications.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return file


def test_apply_refuses_when_the_export_hash_differs_from_the_live_store(world):
    root, _ = world
    _store(root)
    exported = retention.live_store_sha(root)
    _store(root, '{"version":1,"applications":{"app-x":{}}}')  # an application was added after the export
    ledger_before = (root / "data/jobs/job_history.json").read_bytes()
    with pytest.raises(SystemExit, match="different applications.json"):
        run_prune(root, apply=True, store_sha=exported)
    assert (root / "data/jobs/job_history.json").read_bytes() == ledger_before and not (root / "data/backups").exists()


def test_apply_refuses_a_missing_header_a_store_that_appeared_and_one_that_vanished(world):
    root, _ = world
    with pytest.raises(SystemExit, match="no `# store-sha256` header"):
        run_prune(root, apply=True, store_sha=None)
    _store(root)
    with pytest.raises(SystemExit, match="different applications.json"):
        run_prune(root, apply=True, store_sha="none")  # exported when there was no store
    exported = retention.live_store_sha(root)
    (root / "data/applications/applications.json").unlink()
    with pytest.raises(SystemExit, match="different applications.json"):
        run_prune(root, apply=True, store_sha=exported)


def test_apply_with_a_matching_hash_leaves_the_application_store_byte_identical(world):
    root, _ = world
    file = _store(root)
    before = file.read_bytes()
    out = run_prune(root, apply=True)
    assert out["applied"] is True and out["applicationsExportCurrent"] is True
    assert file.read_bytes() == before


def test_the_header_is_read_from_the_ids_file_and_ids_still_parse(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("# store-sha256 " + "a" * 64 + "\njob-1\n")
    assert retention.parse_store_sha(f) == "a" * 64 and retention.parse_ids(f) == {"job-1"}
    f.write_text("job-1\n")
    assert retention.parse_store_sha(f) is None
    f.write_text("# store-sha256 none\n")
    assert retention.parse_store_sha(f) == "none"


def test_no_retention_code_writes_under_data_applications():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for file in (root / "python/job_discovery/older_key_retention.py", root / "scripts/prune-older-key.py", root / "scripts/older-key-report.py"):
        for line in file.read_text().splitlines():
            if "applications" in line and any(w in line for w in ("write_", "unlink", "rmtree", "shutil.", "open(")):
                raise AssertionError(f"{file.name} may write near the application store: {line.strip()}")
