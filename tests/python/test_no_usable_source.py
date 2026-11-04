"""S8b: a run in which no source gave a usable result imports nothing.

`require_usable` is opt-in (the live path and `import_run.py --import` turn it on). A run that was not cancelled, asked at least one source to
run and got none that is usable (failed, partial, skipped, unfinished, or held as not run) leaves the ledger, the view, the stored dropped
ads and every counter exactly as they were. One usable source makes it an ordinary import. A cancelled run keeps the S6 rules.
"""
import json

import pytest

import filtered_ads
import import_run
import importer
import staging
from providers.base_provider import dropped_ad
from test_filtered_ads import ad
from test_import import canon
from test_stale import GOOD, JOB, KEY, OTHER, counted, day, good_run, ledger_at, staged

NEW = canon(3, provider="jobspy")
UNUSABLE = [{"status": "failed", "complete": False}, {"status": "partial", "complete": False}, {"status": "skipped", "complete": False}, None]
IDS = ["failed", "partial", "skipped", "unfinished"]


def snapshot(root):
    """Every byte the import could write: the job files, the dropped-ads store."""
    files = {p.name: p.read_bytes() for p in (root / "data/jobs").glob("*.json")}
    store = filtered_ads.file_path(root)
    files["filtered"] = store.read_bytes() if store.exists() else b""
    return files


def run_it(root, run_id, *, require_usable=True):
    outcome = importer.import_staged_run(root, run_id, require_usable=require_usable)
    assert outcome.ok, outcome.refused
    return outcome


@pytest.mark.parametrize("footer", UNUSABLE, ids=IDS)
def test_a_run_with_no_usable_source_changes_nothing(tmp_path, monkeypatch, footer):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    before = snapshot(tmp_path)
    ledger = ledger_at(tmp_path)
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([NEW], footer, [dropped_ad({**ad(7), "jobId": "dropped-7", "jobUrl": "https://x.example/7"}, "title_not_matched", "e")])})
    outcome = run_it(tmp_path, "b")
    assert snapshot(tmp_path) == before, "ledger, view, scored-side files and the dropped-ads store are the same bytes"
    after = ledger_at(tmp_path)
    for field in ("generation", "lastImport", "sourceRuns", "partialRuns"):
        assert after.get(field) == ledger.get(field)
    assert NEW["jobId"] not in after["jobs"]
    assert not outcome.committed and outcome.result.report["nothingSaved"] == importer.NO_USABLE_SOURCE
    assert "b" not in filtered_ads.load(tmp_path)["appliedRuns"] and "b" not in filtered_ads.unrecorded(tmp_path)
    assert staging.imported_info(tmp_path, "b")["nothing"] == importer.NO_USABLE_SOURCE
    assert importer.evidence_block(outcome.result.report, outcome.result.stats)["kind"] == "nothing"


def test_importing_it_again_changes_nothing_either(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([], {"status": "skipped", "complete": False}, [])})
    run_it(tmp_path, "b")
    before = snapshot(tmp_path)
    run_it(tmp_path, "b")
    assert snapshot(tmp_path) == before


def test_all_sources_failing_or_skipped_together_are_still_no_usable_source(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    before = snapshot(tmp_path)
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([], {"status": "failed", "complete": False}, []), "workable": ([], {"status": "skipped", "complete": False}, [])})
    assert run_it(tmp_path, "b").result.report["nothingSaved"] == importer.NO_USABLE_SOURCE
    assert snapshot(tmp_path) == before


def test_one_usable_source_makes_it_an_ordinary_import(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], {"status": "failed", "complete": False}, []), "workable": ([canon(5, provider="workable")], GOOD, [])})
    outcome = run_it(tmp_path, "b")
    assert outcome.committed and "nothingSaved" not in outcome.result.report
    assert ledger_at(tmp_path)["lastImport"]["runId"] == "b" and "b" in filtered_ads.load(tmp_path)["appliedRuns"]
    assert "nothing" not in (staging.imported_info(tmp_path, "b") or {})


@pytest.mark.parametrize("footer", UNUSABLE, ids=IDS)
def test_without_the_opt_in_the_importer_behaves_as_before(tmp_path, monkeypatch, footer):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], footer, [])})
    outcome = run_it(tmp_path, "b", require_usable=False)
    assert outcome.committed and ledger_at(tmp_path)["lastImport"]["runId"] == "b"


def test_a_cancelled_run_keeps_the_partial_rules_whatever_require_usable_says(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER, NEW], None, [])})  # unfinished: nothing a usable source would say
    staging.mark_cancelled(tmp_path, "b", {"requestedAt": day(10)})
    outcome = run_it(tmp_path, "b")
    ledger = ledger_at(tmp_path)
    assert outcome.saved == 2 and NEW["jobId"] in ledger["jobs"] and ledger["partialRuns"] == ["b"] and ledger["lastImport"]["runId"] == "a"
    assert "nothingSaved" not in outcome.result.report


def test_the_dropped_ads_of_such_a_run_wait_for_nothing_and_a_backfill_skips_it(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    other = dropped_ad({**ad(7), "jobId": "dropped-7", "jobUrl": "https://x.example/7"}, "title_not_matched", "e")
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([], {"status": "failed", "complete": False}, [other])})
    run_it(tmp_path, "b")
    report = filtered_ads.backfill(tmp_path, lambda run: day(10))
    line = next(item for item in report["runs"] if item["runId"] == "b")
    assert line["state"].startswith("run with no usable source") and report["noUsableSource"] == 1
    assert "dropped-7" not in filtered_ads.load(tmp_path)["ads"] and "b" not in filtered_ads.unrecorded(tmp_path)


def test_the_lifecycle_report_does_not_read_it_as_evidence(tmp_path, monkeypatch):
    import lifecycle_report

    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([], {"status": "skipped", "complete": False}, [])})
    run_it(tmp_path, "b")
    good_run(tmp_path, monkeypatch, "c", day(20), ads=(JOB,))
    seen = []
    real = lifecycle_report.build_report
    monkeypatch.setattr(lifecycle_report, "build_report", lambda start, ledger, runs, **kw: seen.append([r.run_id for r in runs]) or real(start, ledger, runs, **kw))
    lifecycle_report.gather(tmp_path, None, as_of=day(30), measure=False)
    assert seen == [["a", "c"]]


def test_the_import_command_turns_it_on_and_says_so(tmp_path, monkeypatch, capsys):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    before = snapshot(tmp_path)
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], {"status": "failed", "complete": False}, [])})
    assert import_run.main(["--run", "b", "--import"], root=tmp_path) == 0
    assert "nothing was imported, the list was not changed" in capsys.readouterr().out
    assert snapshot(tmp_path) == before


def test_the_live_path_and_the_import_command_are_the_only_callers_that_turn_it_on():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    callers = sorted(f.relative_to(repo).as_posix() for f in (repo / "python").rglob("*.py") if "require_usable=True" in f.read_text(encoding="utf-8"))
    assert callers == ["python/job_discovery/import_run.py", "python/job_discovery/run_discovery.py"]
    assert json.loads('"x"') == "x"
