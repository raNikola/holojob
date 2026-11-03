"""GET /api/jobs/all, the Python half (slice S5e2): every ad known, one class each. Offline; every path is under tmp_path.

The Node half (the route, its 503, the check before it) is tests/js/jobsAllRoute.test.js.
"""

import copy
import json
import re
import shutil
from pathlib import Path

import pytest

import all_ads
import job_history as jh
import run_scoring
import view_guard
from test_filtered_ads import T, ad, imported, stage_run
from test_import import OK, canon, hand_run
from test_readers_not_found import INTEL, enrich


KEY = "current-key"
RUN = "r2"
NOW = "2026-11-03T10:00:00+00:00"


def entry(n, **fields):
    return {"firstSeen": "2026-10-01T10:00:00+00:00", "lastSeen": "2026-10-20T10:00:00+00:00", "closedAt": None, "llmFacts": {"workMode": "remote"},
            "provider": "greenhouse", "roleKey": f"role-{n}", "seenUnder": KEY,
            "job": {"jobId": f"j{n}", "title": f"Ad {n}", "company": "Acme", "location": "Remote", "description": f"THE AD TEXT {n}", "jobUrl": f"https://x.example/{n}",
                    "provider": "greenhouse", "site": "greenhouse", "isRemote": True, "datePosted": "2026-10-01", "salary": "1000"},
            **fields}


def ledger_of(*entries, **top):
    return {"generation": 5, "version": 1, "updatedAt": NOW,
            "lastImport": {"runId": RUN, "at": NOW, "startedAt": NOW, "meta": {"providers": ["greenhouse"]}, "marksNotFound": True},
            "jobs": {e["job"]["jobId"]: e for e in entries}, **top}


FOUND = entry(1, lastRunId=RUN, lastRunPos=0)
HELD = entry(2, lastRunId="r1", heldRunId=RUN)
PROVEN = entry(3, lastRunId="r1", heldRunId=RUN, absentSince=NOW, absentRuns=1, lastAbsentRunId=RUN)
NOT_RETURNED = entry(4, lastRunId="r1")
OLDER = entry(5, seenUnder="older-key")
CLOSED = entry(6, closedAt="2026-10-30T10:00:00+00:00", absentRuns=2)
STALE = entry(7, staleSince=NOW)
ALL_KINDS = [FOUND, HELD, PROVEN, NOT_RETURNED, OLDER, CLOSED, STALE]
EXPECTED = {"j1": "found", "j2": "held", "j3": "absent", "j4": "absent", "j5": "older_key", "j6": "closed", "j7": "stale"}


def classes(answer):
    return {row["jobId"]: row["class"] for row in answer["rows"]}


def record(n, reason="title_not_matched", **fields):
    return {"source": "infostud", "title": f"Dropped {n}", "company": "Beta", "location": "Niš", "url": f"https://y.example/{n}", "externalId": f"e{n}",
            "reason": reason, "firstSeen": T[0], "lastSeen": T[1], "lastRunId": "r2", "timesSeen": 2, "searchKey": KEY, "inLedger": False, **fields}


def store_of(**ads):
    return {"version": 1, "appliedRuns": ["r2"], "ads": ads}


# --- one class for each row ------------------------------------------------------------------------------------------------


def test_every_kind_of_entry_gets_its_class():
    answer = all_ads.build(ledger_of(*ALL_KINDS), None)
    assert classes(answer) == EXPECTED
    assert answer["meta"]["counts"] == {"found": 1, "held": 1, "absent": 2, "closed": 1, "older_key": 1, "stale": 1, "filtered": 0, "filtered_incomplete": 0, "unclassified": 0}
    assert answer["meta"]["total"] == 7 and answer["meta"]["currentSearchKey"] == KEY and answer["meta"]["lastImportRunId"] == RUN


def test_a_cross_post_still_listed_under_another_copy_says_so():
    copy_of_found = entry(8, lastRunId="r1", roleKey=FOUND["roleKey"])
    answer = all_ads.build(ledger_of(FOUND, copy_of_found, NOT_RETURNED), None)
    by_id = {row["jobId"]: row for row in answer["rows"]}
    assert by_id["j8"]["class"] == "absent" and by_id["j8"]["reason"].startswith("Still listed under another copy of this ad")
    assert by_id["j4"]["reason"].startswith("Not returned by the latest search")
    assert answer["meta"]["diagnostics"]["absentListedElsewhere"] == 1


def test_a_found_ad_is_found_whatever_older_marks_it_still_has():
    assert all_ads.classify(entry(1, lastRunId=RUN, closedAt=NOW, absentSince=NOW, heldRunId=RUN, staleSince=NOW, seenUnder="older-key"), RUN, KEY, {"greenhouse"}) == "found"


@pytest.mark.parametrize("fields, expected", [
    ({"closedAt": NOW, "absentSince": NOW, "staleSince": NOW, "heldRunId": RUN}, "closed"),
    ({"staleSince": NOW, "absentSince": NOW, "heldRunId": RUN}, "stale"),
    ({"absentSince": NOW, "heldRunId": RUN, "seenUnder": "older-key"}, "absent"),
    ({"heldRunId": RUN, "seenUnder": "older-key"}, "held"),
    ({"heldRunId": "r1"}, "absent"),
    ({"heldRunId": "r1", "seenUnder": "older-key"}, "older_key"),
])
def test_the_order_of_the_marks(fields, expected):
    assert all_ads.classify(entry(9, **fields), RUN, KEY, {"greenhouse"}) == expected


def test_reasons_say_what_happened_in_plain_words():
    by_id = {row["jobId"]: row["reason"] for row in all_ads.build(ledger_of(*ALL_KINDS), None)["rows"]}
    assert by_id["j1"] == "Found by the latest run"
    assert "could not say" in by_id["j2"] and "2026-10-20" in by_id["j2"]
    assert by_id["j3"].startswith("Not on the company's board in a complete check on 2026-11-03")
    assert by_id["j4"] == "Not returned by the latest search. Last seen 2026-10-20"
    assert by_id["j5"].startswith("From an earlier search")
    assert by_id["j6"] == "Not on the company's board in 2 complete checks, closed 2026-10-30"
    assert all_ads.ledger_reason("closed", {"closedAt": "2026-10-30"}) == "No longer listed since 2026-10-30"
    assert all_ads.ledger_reason("unclassified", {}) == "Not enough information to say. Last seen unknown"


# --- no time and no view decides a class -----------------------------------------------------------------------------------


def test_no_time_moves_a_class():
    ledger = ledger_of(*ALL_KINDS)
    base = classes(all_ads.build(ledger, None))
    moved = copy.deepcopy(ledger)
    moved["lastImport"]["at"] = "2030-01-01T00:00:00+00:00"
    moved["lastImport"]["startedAt"] = "2000-01-01T00:00:00+00:00"
    moved["updatedAt"] = "2030-01-01T00:00:00+00:00"
    moved["lastImport"]["meta"]["generatedAt"] = "2000-01-01T00:00:00+00:00"
    for one in moved["jobs"].values():
        one["lastSeen"] = moved["lastImport"]["at"]
        one["firstSeen"] = "2000-01-01T00:00:00+00:00"
    assert classes(all_ads.build(moved, None)) == base


def test_the_code_reads_neither_the_view_nor_a_time_to_decide_a_class():
    source = Path(all_ads.__file__).read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]
    assert "discovered_jobs" not in code and "generatedAt" not in code and "datetime" not in code and 'get("at")' not in code
    classify_code = code[code.index("def classify("):code.index("def classify_filtered(")]
    assert "lastSeen" not in classify_code and "firstSeen" not in classify_code and "marksNotFound" not in classify_code


def real_import(root, monkeypatch, keys=("k", "k")):
    """Through the real importer: run a finds 1, 2 and 3; run b finds only 1. Each drops one ad. All are jobspy, a search-based source."""
    first, second, third = (canon(n, provider="jobspy") for n in (1, 2, 3))
    stage_run(root, monkeypatch, "a", T[0], kept=[first, second, third], dropped=[ad(7)], key=keys[0], source="jobspy")
    imported(root, "a")
    stage_run(root, monkeypatch, "b", T[1], kept=[first], dropped=[ad(8)], key=keys[1], source="jobspy")
    imported(root, "b")
    return first, second, third


def answer_at(root):
    jobs = root / "data/jobs"
    store, state = all_ads.read_filtered(jobs / "filtered_ads.json")
    return all_ads.build(all_ads.read_ledger(jobs / "job_history.json"), store, state)


def test_a_real_import_gives_the_classes_and_the_rows_the_view_holds_are_found_held_or_proven(tmp_path, monkeypatch):
    first, second, _ = real_import(tmp_path, monkeypatch)
    answer = answer_at(tmp_path)
    assert classes(answer)[first["jobId"]] == "found" and classes(answer)[second["jobId"]] == "absent"
    assert answer["meta"]["counts"]["found"] == 1 and answer["meta"]["counts"]["absent"] == 2 and answer["meta"]["counts"]["filtered"] == 2
    view = json.loads((tmp_path / "data/jobs/discovered_jobs.json").read_text())
    assert {j["jobId"] for j in view["jobs"]} == {r["jobId"] for r in answer["rows"] if r["class"] == "found"}


def test_a_changed_search_makes_the_earlier_rows_older_key(tmp_path, monkeypatch):
    first, second, _ = real_import(tmp_path, monkeypatch, keys=("old", "new"))
    answer = answer_at(tmp_path)
    assert answer["meta"]["currentSearchKey"] == "new"
    assert classes(answer)[first["jobId"]] == "found" and classes(answer)[second["jobId"]] == "older_key"
    assert answer["meta"]["counts"]["older_key"] == 2 and answer["meta"]["counts"]["absent"] == 0


def test_classes_do_not_change_when_the_view_is_regenerated(tmp_path, monkeypatch):
    real_import(tmp_path, monkeypatch)
    before = answer_at(tmp_path)
    jobs, ledger = tmp_path / "data/jobs/discovered_jobs.json", tmp_path / "data/jobs/job_history.json"
    shutil.copy(jobs, tmp_path / "view.bak")
    jobs.unlink()
    assert view_guard.ensure(jobs, ledger)["regenerated"] is True and jobs.exists()
    assert answer_at(tmp_path) == before


def test_classes_do_not_change_with_a_view_gone_or_rewritten(tmp_path, monkeypatch):
    real_import(tmp_path, monkeypatch)
    before = answer_at(tmp_path)
    jobs = tmp_path / "data/jobs/discovered_jobs.json"
    view = json.loads(jobs.read_text())
    view["meta"]["generatedAt"] = "2000-01-01T00:00:00+00:00"
    view["jobs"] = []
    jobs.write_text(json.dumps(view))
    assert answer_at(tmp_path) == before
    jobs.unlink()
    assert answer_at(tmp_path) == before


def test_classes_do_not_change_when_enrichment_rewrites_the_view(tmp_path, monkeypatch, open_ai_budget):
    asked, jobs_file = enrich(tmp_path, monkeypatch, facts_on="x2")
    assert asked == ["a1"], "the real enrichment ran"
    ledger = json.loads(jh.ledger_path(jobs_file).read_text())
    assert classes(all_ads.build(ledger, None)) == {"a1": "found", "x1": "absent", "x2": "held", "x3": "held"}
    assert ledger["jobs"]["a1"]["llmFacts"], "and it wrote into the ledger too"


def test_a_ledger_from_before_the_flag_gives_the_same_classes():
    flagged = ledger_of(*ALL_KINDS)
    before = copy.deepcopy(flagged)
    del before["lastImport"]["marksNotFound"]
    assert classes(all_ads.build(before, None)) == classes(all_ads.build(flagged, None)) == EXPECTED


def test_a_real_pre_flag_ledger_gives_the_same_classes(tmp_path, monkeypatch, open_ai_budget):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, flagged = enrich(tmp_path / "a", monkeypatch)
    _, plain = enrich(tmp_path / "b", monkeypatch, flagged=False)
    one = classes(all_ads.build(json.loads(jh.ledger_path(flagged).read_text()), None))
    assert one == classes(all_ads.build(json.loads(jh.ledger_path(plain).read_text()), None))
    assert set(one.values()) == {"found", "absent", "held"}


# --- the documented fallback: never a guess ---------------------------------------------------------------------------------


def test_with_no_last_import_only_an_entrys_own_mark_gives_a_class():
    ledger = ledger_of(*ALL_KINDS)
    del ledger["lastImport"]
    assert classes(all_ads.build(ledger, None)) == {"j1": "unclassified", "j2": "unclassified", "j3": "absent", "j4": "unclassified", "j5": "unclassified", "j6": "closed", "j7": "stale"}


@pytest.mark.parametrize("last", [{}, {"runId": ""}, {"runId": None}, None])
def test_a_last_import_with_no_run_id_counts_as_none(last):
    ledger = {**ledger_of(FOUND, NOT_RETURNED), "lastImport": last}
    answer = all_ads.build(ledger, None)
    assert set(classes(answer).values()) == {"unclassified"} and answer["meta"]["lastImportRunId"] is None and answer["meta"]["currentSearchKey"] is None


def test_a_last_import_that_found_nothing_cannot_say_absent_from_older():
    answer = all_ads.build(ledger_of(HELD, NOT_RETURNED, OLDER, CLOSED), None)
    assert answer["meta"]["currentSearchKey"] is None
    assert classes(answer) == {"j2": "held", "j4": "unclassified", "j5": "unclassified", "j6": "closed"}, "held needs no key; the two that do are not guessed"


def test_found_rows_under_two_keys_cannot_say_which_search_ran():
    answer = all_ads.build(ledger_of(FOUND, entry(8, lastRunId=RUN, seenUnder="other"), NOT_RETURNED), None)
    assert answer["meta"]["currentSearchKey"] is None and classes(answer)["j4"] == "unclassified"


def test_found_rows_under_an_empty_key_give_no_current_search():
    answer = all_ads.build(ledger_of(entry(1, lastRunId=RUN, seenUnder="")), None)
    assert answer["meta"]["currentSearchKey"] is None


@pytest.mark.parametrize("value", [None, ""])
def test_an_entry_with_no_search_key_is_not_guessed(value):
    answer = all_ads.build(ledger_of(FOUND, entry(4, seenUnder=value)), None)
    assert classes(answer)["j4"] == "unclassified"
    missing = entry(4)
    del missing["seenUnder"]
    assert classes(all_ads.build(ledger_of(FOUND, missing), None))["j4"] == "unclassified"


# --- a source that was not part of the latest run ---------------------------------------------------------------------------------


LEFT_OUT = entry(10, lastRunId="r1", provider="workable")


def test_a_row_whose_source_was_left_out_is_not_absent_and_says_why():
    answer = all_ads.build(ledger_of(FOUND, NOT_RETURNED, LEFT_OUT), None)
    row = next(r for r in answer["rows"] if r["jobId"] == "j10")
    assert row["class"] == "unclassified" and row["reason"] == "Its source was not part of the latest run"
    assert classes(answer)["j4"] == "absent", "a row of a source that did run stays absent"
    assert answer["meta"]["diagnostics"]["sourceNotInLatestRun"] == 1 and answer["meta"]["counts"]["unclassified"] == 1


@pytest.mark.parametrize("fields, expected", [
    ({"heldRunId": RUN}, "held"), ({"absentSince": NOW}, "absent"), ({"closedAt": NOW}, "closed"), ({"staleSince": NOW}, "stale"),
    ({"seenUnder": "older-key"}, "older_key"), ({"lastRunId": RUN, "seenUnder": KEY}, "found"),
])
def test_a_left_out_source_changes_no_class_a_mark_or_key_already_proves(fields, expected):
    assert all_ads.classify({**LEFT_OUT, **fields}, RUN, KEY, {"greenhouse"}) == expected


@pytest.mark.parametrize("meta", [{}, {"providers": None}, {"providers": "greenhouse"}])
def test_a_ledger_that_does_not_list_its_sources_gives_no_absent_and_no_invented_reason(meta):
    ledger = ledger_of(FOUND, NOT_RETURNED, OLDER, HELD, PROVEN)
    ledger["lastImport"]["meta"] = meta
    answer = all_ads.build(ledger, None)
    assert classes(answer) == {"j1": "found", "j4": "unclassified", "j5": "older_key", "j2": "held", "j3": "absent"}
    assert next(r for r in answer["rows"] if r["jobId"] == "j4")["reason"].startswith("Not enough information to say")
    assert answer["meta"]["diagnostics"]["sourceNotInLatestRun"] == 0


def test_only_a_row_it_decided_counts_as_left_out():
    answer = all_ads.build(ledger_of(FOUND, {**LEFT_OUT, "seenUnder": "older-key"}, {**LEFT_OUT, "closedAt": NOW}), None)
    assert answer["meta"]["diagnostics"]["sourceNotInLatestRun"] == 0
    assert all("not part of the latest run" not in row["reason"] for row in answer["rows"])


def test_a_cross_post_of_a_left_out_source_gives_the_source_reason():
    answer = all_ads.build(ledger_of(FOUND, entry(11, lastRunId="r1", provider="workable", roleKey=FOUND["roleKey"])), None)
    row = next(r for r in answer["rows"] if r["jobId"] == "j11")
    assert row["reason"] == "Its source was not part of the latest run" and answer["meta"]["diagnostics"]["absentListedElsewhere"] == 0


def two_sources(root, later_sources):
    """Through the real importer: jobspy and workable both run, then a second run with `later_sources`, under the same search."""
    found, gone = canon(1, provider="jobspy"), canon(2, provider="workable")
    hand_run(root, "first", {"jobspy": ([found], OK), "workable": ([gone], OK)})
    imported(root, "first")
    hand_run(root, "second", later_sources(found))
    imported(root, "second")
    return gone


def test_a_disabled_source_through_the_real_import(tmp_path):
    gone = two_sources(tmp_path, lambda found: {"jobspy": ([found], OK)})
    answer = answer_at(tmp_path)
    assert classes(answer)[gone["jobId"]] == "unclassified"
    assert next(r for r in answer["rows"] if r["jobId"] == gone["jobId"])["reason"] == "Its source was not part of the latest run"
    assert answer["meta"]["currentSearchKey"] == "k", "the search key is the same: only the sources tell this apart"


@pytest.mark.parametrize("footer", [{"status": "failed", "complete": False}, {"status": "skipped", "complete": False}], ids=["failed", "skipped"])
def test_a_failed_or_skipped_source_stays_held_through_the_real_import(tmp_path, footer):
    gone = two_sources(tmp_path, lambda found: {"jobspy": ([found], OK), "workable": ([], footer)})
    assert classes(answer_at(tmp_path))[gone["jobId"]] == "held"


def test_a_source_that_ran_and_did_not_return_the_ad_is_absent_through_the_real_import(tmp_path):
    gone = two_sources(tmp_path, lambda found: {"jobspy": ([found], OK), "workable": ([], OK)})
    assert classes(answer_at(tmp_path))[gone["jobId"]] == "absent"


# --- filtered ads --------------------------------------------------------------------------------------------------------------


def test_filtered_rows_with_their_reasons():
    answer = all_ads.build(ledger_of(FOUND), store_of(
        a=record(1), b=record(2, "title_excluded:project manager"), c=record(3, "search_terms_not_matched"), d=record(4, "location_not_matched"), e=record(5, "some_new_code"),
    ))
    by_id = {r["jobId"]: r for r in answer["rows"]}
    assert by_id["a"]["reason"] == "Filtered out: Title didn't match" and by_id["a"]["reasonCode"] == "title_not_matched"
    assert by_id["b"]["reason"] == "Filtered out: Excluded title: project manager"
    assert by_id["c"]["reason"] == "Filtered out: Search terms didn't match"
    assert by_id["d"]["reason"] == "Filtered out: Location didn't match"
    assert by_id["e"]["reason"] == "Filtered out: some_new_code"
    assert by_id["a"]["jobUrl"] == "https://y.example/1" and by_id["a"]["provider"] == "infostud" and by_id["a"]["from"] == "filtered"
    assert answer["meta"]["counts"]["filtered"] == 5 and answer["meta"]["filteredFile"] == "ok"


@pytest.mark.parametrize("reason", ["detail_cap", "no_detail_text"])
def test_an_ad_whose_full_text_was_not_read_shows_marked_incomplete(reason):
    answer = all_ads.build(ledger_of(FOUND), store_of(a=record(1, reason)))
    assert classes(answer)["a"] == "filtered_incomplete" and answer["rows"][-1]["reason"].startswith("Incomplete: ")
    assert answer["meta"]["counts"]["filtered_incomplete"] == 1 and answer["meta"]["counts"]["filtered"] == 0


@pytest.mark.parametrize("fields", [
    {"title": ""}, {"title": "   "}, {"title": None}, {"url": ""}, {"url": None}, {"url": "not a web address"}, {"url": "ftp://y.example/1"}, {"url": "https://"},
    {"title": "", "reason": "no_title"}, {"url": "", "reason": "detail_cap"},
])
def test_a_record_with_no_title_or_no_url_is_left_out_and_counted(fields):
    answer = all_ads.build(ledger_of(FOUND), store_of(a=record(1, **fields), b=record(2)))
    assert "a" not in classes(answer) and "b" in classes(answer)
    assert answer["meta"]["diagnostics"]["filteredWithoutTitleOrUrl"] == 1 and answer["meta"]["counts"]["filtered"] == 1


def test_a_jobid_in_both_shows_once_from_the_ledger_whatever_its_mark_says():
    for mark in (True, False):
        answer = all_ads.build(ledger_of(FOUND, NOT_RETURNED), store_of(j4=record(4, inLedger=mark), other=record(5, inLedger=True)))
        rows = [r for r in answer["rows"] if r["jobId"] == "j4"]
        assert len(rows) == 1 and rows[0]["from"] == "ledger" and rows[0]["class"] == "absent"
        assert answer["meta"]["diagnostics"]["filteredAlsoInLedger"] == 1
        assert classes(answer)["other"] == "filtered", "a stale mark does not hide an ad the ledger does not hold"


def test_no_ledger_is_an_empty_state_and_filtered_rows_still_show():
    answer = all_ads.build(None, store_of(a=record(1)))
    assert classes(answer) == {"a": "filtered"} and answer["meta"]["ledgerGeneration"] is None


@pytest.mark.parametrize("body, state", [("{ broken", "unreadable"), ("[]", "unreadable"), ('{"version": 2, "ads": {}}', "unreadable"), (None, "missing")])
def test_a_filtered_file_that_cannot_be_used_is_reported_and_the_ledger_rows_stay(tmp_path, capsys, body, state):
    jobs = tmp_path / "data/jobs"
    jobs.mkdir(parents=True)
    (jobs / "job_history.json").write_text(json.dumps(ledger_of(FOUND)))
    if body is not None:
        (jobs / "filtered_ads.json").write_text(body)
    assert all_ads.main(["--root", str(tmp_path)]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["meta"]["filteredFile"] == state and classes(answer) == {"j1": "found"}


# --- what the route may never do -------------------------------------------------------------------------------------------------


def all_keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from all_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from all_keys(inner)


def test_no_description_and_nothing_else_from_the_entry_is_in_the_answer():
    text_store = store_of(a={**record(1), "description": "A FILTERED AD TEXT", "salary": "9"})
    answer = all_ads.build(ledger_of(*ALL_KINDS), text_store)
    text = json.dumps(answer)
    assert "AD TEXT" not in text and "description" not in set(all_keys(answer))
    assert not {"llmFacts", "salary", "roleKey", "seenUnder", "description", "externalId"} & set(all_keys(answer))


def test_every_row_has_the_same_fields_and_no_score():
    answer = all_ads.build(ledger_of(*ALL_KINDS), store_of(a=record(1)))
    shapes = {tuple(row) for row in answer["rows"]}
    assert len(shapes) == 1 and all(row["matchScore"] is None for row in answer["rows"])


def test_copies_of_one_role_share_a_copy_group_and_a_filtered_ad_has_none():
    answer = all_ads.build(ledger_of(FOUND, entry(8, lastRunId="r1", roleKey=FOUND["roleKey"]), entry(9, roleKey=None), entry(10, roleKey="")), store_of(a=record(1)))
    groups = {row["jobId"]: row["copyGroup"] for row in answer["rows"]}
    assert groups == {"j1": FOUND["roleKey"], "j8": FOUND["roleKey"], "j9": None, "j10": None, "a": None}


def test_an_entry_with_no_ad_is_left_out_and_counted():
    ledger = ledger_of(FOUND)
    ledger["jobs"]["bad"] = {"firstSeen": NOW}
    ledger["jobs"]["worse"] = "text"
    answer = all_ads.build(ledger, None)
    assert classes(answer) == {"j1": "found"} and answer["meta"]["diagnostics"]["ledgerEntriesWithoutAd"] == 2


@pytest.mark.parametrize("body", ["{ broken", "[]", '{"jobs": []}', '{"generation": 4, "jobs": {"cut'])
def test_an_unreadable_ledger_gives_exit_3_a_reason_and_no_list(tmp_path, capsys, body):
    jobs = tmp_path / "data/jobs"
    jobs.mkdir(parents=True)
    (jobs / "job_history.json").write_text(body)
    (jobs / "filtered_ads.json").write_text(json.dumps(store_of(a=record(1))))
    assert all_ads.main(["--root", str(tmp_path)]) == 3
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False and answer["message"] and "rows" not in answer and "meta" not in answer
    assert (jobs / "job_history.json").read_text() == body, "and it is left where it is"
    assert [p.name for p in jobs.iterdir() if "corrupt" in p.name] == []


def fingerprints(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


def test_it_writes_nothing_with_generations_consistent(tmp_path, monkeypatch, capsys):
    real_import(tmp_path, monkeypatch)
    jobs, ledger = tmp_path / "data/jobs/discovered_jobs.json", tmp_path / "data/jobs/job_history.json"
    assert view_guard.state(jobs, ledger)["consistent"], "the check before it then has nothing to rebuild either"
    before = fingerprints(tmp_path)
    assert all_ads.main(["--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["rows"]
    assert fingerprints(tmp_path) == before


def test_scoring_and_the_job_list_are_the_same_with_it_or_without_it(tmp_path, monkeypatch, capsys):
    """The answer is made between two real scoring runs, and neither the view nor the scored file notices."""
    real_import(tmp_path, monkeypatch)
    (tmp_path / "intel.json").write_text(json.dumps(INTEL))
    (tmp_path / "profile.json").write_text("{}")
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    jobs = tmp_path / "data/jobs/discovered_jobs.json"

    def score(name):
        monkeypatch.setattr("sys.argv", ["run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(jobs), "--output", str(tmp_path / name)])
        assert run_scoring.main() == 0
        return json.loads((tmp_path / name).read_text())

    def stable(scored):
        return {**scored, "meta": {k: v for k, v in scored["meta"].items() if k not in ("generatedAt", "sourceRunId")}}

    first = score("first.json")
    view = jobs.read_bytes()
    assert all_ads.main(["--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert jobs.read_bytes() == view
    second = score("second.json")
    assert second["jobs"] == first["jobs"] and jobs.read_bytes() == view
    assert {k for k in stable(first)["meta"] if stable(first)["meta"][k] != stable(second)["meta"].get(k)} == set()


# --- nothing outside the job data's reach ----------------------------------------------------------------------------------------


def test_it_needs_only_the_standard_library():
    source = Path(all_ads.__file__).read_text(encoding="utf-8")
    assert set(re.findall(r"^(?:from|import) (\w+)", source, re.M)) <= {"__future__", "argparse", "json", "re", "sys", "pathlib"}
