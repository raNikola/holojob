"""Two-fetch closing for snapshot sources (slice S5c). Offline; every path is under tmp_path."""

import copy
import json
import sys

import pytest
import requests

import importer
import job_history as jh
import run_discovery
import staging
from dedupe_jobs import _crosspost_key
from providers import ashby_provider, greenhouse_provider, lever_provider
from providers.base_provider import board_read, build_canonical_job
from view_guard import derive_view, state as view_state

KEY = "k"


def iso(day):
    return f"2026-11-{day + 1:02d}T10:00:00+00:00"


def ad(n, provider="greenhouse", board="acme"):
    return {
        **build_canonical_job(provider=provider, source=board, title=f"Product Manager {n}", company=f"Co{n}", location="Remote",
                              job_url=f"https://{provider}.example/{n}", description="Own the roadmap. " * 30, is_remote=True, scraped_at=iso(0)),
    }


def complete(*listed):
    return {"complete": True, "listed": {job["jobId"] for job in listed}}


def unproven(*listed):
    return {"complete": False, "listed": {job["jobId"] for job in listed}}


def apply(ledger, jobs, day, *, evidence=None, run_id=None, key=KEY, **kw):
    return jh.apply_run(ledger, jobs, now=iso(day), providers_returned={p: 1 for p in ("greenhouse", "lever", "ashby", "jobspy")}, key=key,
                        role_key=_crosspost_key, board_evidence=evidence, run_id=run_id or f"run{day}", prune=False, **kw)


def seen(*jobs):
    ledger = jh.empty_ledger()
    apply(ledger, list(jobs), 0)
    return ledger


GONE = ad(2)
ID = GONE["jobId"]
BOARD = {"greenhouse": {"acme": complete()}}


def row(out, job):
    return next((o for o in out if o["jobId"] == job["jobId"]), None)


# --- the count ---------------------------------------------------------------------------------------------------------


def test_one_miss_does_not_close_and_the_row_stays_shown_and_marked():
    ledger = seen(GONE)
    out, stats = apply(ledger, [], 1, evidence=BOARD)
    entry = ledger["jobs"][ID]
    assert entry["closedAt"] is None and entry["absentRuns"] == 1 and entry["absentSince"] == iso(1) and entry["lastAbsentRunId"] == "run1"
    assert stats["absent"] == 1 and stats["closed"] == 0
    assert row(out, GONE)["isAbsent"] is True and row(out, GONE)["absentSince"] == iso(1) and row(out, GONE)["isClosed"] is False
    assert entry["lastSeen"] == iso(0), "not seen, so lastSeen stays"


def test_two_consecutive_misses_close_and_keep_the_first_date_of_absence():
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD)
    out, stats = apply(ledger, [], 2, evidence=BOARD)
    entry = ledger["jobs"][ID]
    assert entry["closedAt"] == iso(2) and entry["absentRuns"] == 2 and entry["absentSince"] == iso(1) and stats["closed"] == 1 and stats["absent"] == 0
    assert row(out, GONE)["isClosed"] is True and row(out, GONE)["closedAfterChecks"] == 2 and "isAbsent" not in row(out, GONE)


def test_seen_in_between_resets_the_count():
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD)
    out, _ = apply(ledger, [GONE], 2, evidence=BOARD)
    assert not {"absentRuns", "absentSince", "lastAbsentRunId"} & set(ledger["jobs"][ID]) and "isAbsent" not in row(out, GONE)
    apply(ledger, [], 3, evidence=BOARD)
    assert ledger["jobs"][ID]["closedAt"] is None and ledger["jobs"][ID]["absentRuns"] == 1


@pytest.mark.parametrize("kw, stat", [
    ({"failed_boards": {"greenhouse": {"acme"}}}, "keptFailedBoard"),
    ({"failed_boards": {"greenhouse": None}}, "keptFailedBoard"),
    ({"empty_boards": {"greenhouse": {"acme"}}}, "keptEmptyBoard"),
    ({"sources_not_run": {"greenhouse"}}, "keptSourceNotRun"),
    ({"board_evidence": {"greenhouse": {"acme": unproven()}}}, "keptUnproven"),
    ({"board_evidence": {"greenhouse": {"other": complete()}}}, "keptBoardNotRead"),
    ({"board_evidence": None}, "keptUnproven"),
])
def test_a_failed_empty_partial_or_unproven_fetch_in_between_neither_counts_nor_resets(kw, stat):
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD)
    before = copy.deepcopy(ledger["jobs"][ID])
    kw = dict(kw)
    evidence = kw.pop("board_evidence", BOARD)
    out, stats = apply(ledger, [], 2, evidence=evidence, **kw)
    after = {k: v for k, v in ledger["jobs"][ID].items() if k != "heldRunId"}
    assert after == {k: v for k, v in before.items() if k != "heldRunId"}
    assert stats[stat] == 1 and stats["closed"] == 0
    assert row(out, GONE)["isAbsent"] is True, "still shown and still marked"
    apply(ledger, [], 3, evidence=BOARD)
    assert ledger["jobs"][ID]["closedAt"] == iso(3), "the two misses stay consecutive across a fetch that proves nothing"


def test_the_same_run_twice_counts_once():
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD, run_id="same")
    once = copy.deepcopy(ledger)
    out, stats = apply(ledger, [], 1, evidence=BOARD, run_id="same")
    assert ledger == once and ledger["jobs"][ID]["absentRuns"] == 1 and ledger["jobs"][ID]["closedAt"] is None
    assert stats["absent"] == 0 and row(out, GONE)["isAbsent"] is True


def test_the_closing_run_applied_twice_changes_nothing():
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD)
    apply(ledger, [], 2, evidence=BOARD, run_id="closing")
    once = copy.deepcopy(ledger)
    apply(ledger, [], 2, evidence=BOARD, run_id="closing")
    assert ledger == once


def test_a_listed_ad_a_filter_dropped_is_no_miss_is_not_found_and_clears_an_earlier_miss():
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD)
    out, stats = apply(ledger, [], 2, evidence={"greenhouse": {"acme": complete(GONE)}})
    entry = ledger["jobs"][ID]
    assert stats["listedButFiltered"] == 1 and stats["closed"] == 0 and stats["known"] == 0
    assert entry["closedAt"] is None and "absentRuns" not in entry and entry["lastSeen"] == iso(0)
    assert row(out, GONE) is None, "it does not match the search, so it is not a result"


def test_a_filter_dropped_ad_on_an_unproven_board_stays_as_it_is():
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD)
    apply(ledger, [], 2, evidence={"greenhouse": {"acme": unproven(GONE)}})
    assert ledger["jobs"][ID]["absentRuns"] == 1, "unproven: no reset"


def test_a_closed_ad_listed_again_and_kept_reopens_with_its_dates_and_facts():
    ledger = seen(GONE)
    facts = {"_fingerprint": jh.job_fingerprint(GONE), "x": 1}
    ledger["jobs"][ID]["llmFacts"] = facts
    apply(ledger, [], 1, evidence=BOARD)
    apply(ledger, [], 2, evidence=BOARD)
    out, stats = apply(ledger, [GONE], 3, evidence=BOARD)
    entry = ledger["jobs"][ID]
    assert stats["reopened"] == 1 and entry["closedAt"] is None and "absentRuns" not in entry and entry["firstSeen"] == iso(0)
    assert entry["llmFacts"] == facts and row(out, GONE)["isClosed"] is False and row(out, GONE)["llmFacts"] == facts


def test_a_closed_ad_listed_but_dropped_by_a_filter_stays_closed():
    ledger = seen(GONE)
    apply(ledger, [], 1, evidence=BOARD)
    apply(ledger, [], 2, evidence=BOARD)
    _, stats = apply(ledger, [], 3, evidence={"greenhouse": {"acme": complete(GONE)}})
    assert ledger["jobs"][ID]["closedAt"] == iso(2) and stats["reopened"] == 0


def test_a_cross_post_still_listed_under_another_copy_is_no_miss():
    other = {**ad(3), "title": GONE["title"], "company": GONE["company"]}
    ledger = seen(GONE)
    apply(ledger, [other], 1, evidence=BOARD)
    apply(ledger, [other], 2, evidence=BOARD)
    assert ledger["jobs"][ID]["closedAt"] is None and "absentRuns" not in ledger["jobs"][ID]


def test_a_board_removed_from_the_config_closes_nothing():
    """The bug before S5c: the source returned ads from other boards, so this board's ads closed though it was never read."""
    removed = ad(5, board="removed")
    ledger = seen(removed)
    for day in (1, 2, 3):
        out, stats = apply(ledger, [ad(1)], day, evidence={"greenhouse": {"acme": complete(ad(1))}})
    entry = ledger["jobs"][removed["jobId"]]
    assert entry["closedAt"] is None and "absentRuns" not in entry and stats["keptBoardNotRead"] == 1 and row(out, removed) is not None


def test_closing_ignores_the_search_key_on_a_proven_board_d4():
    ledger = seen(GONE)
    out, _ = apply(ledger, [], 1, evidence=BOARD, key="another")
    assert ledger["jobs"][ID]["absentRuns"] == 1 and row(out, GONE)["isAbsent"] is True
    apply(ledger, [], 2, evidence=BOARD, key="another")
    assert ledger["jobs"][ID]["closedAt"] == iso(2)


def test_an_ad_of_another_search_on_an_unproven_board_stays_out_of_the_output_as_before():
    ledger = seen(GONE)
    out, stats = apply(ledger, [], 1, evidence={"greenhouse": {"acme": unproven()}}, key="another")
    assert row(out, GONE) is None and stats["keptUnproven"] == 0 and "absentRuns" not in ledger["jobs"][ID]


def test_no_minimum_gap_between_the_two_fetches_d5():
    ledger = seen(GONE)
    jh.apply_run(ledger, [], now="2026-11-02T10:00:00+00:00", providers_returned={}, key=KEY, role_key=_crosspost_key, board_evidence=BOARD, run_id="a")
    jh.apply_run(ledger, [], now="2026-11-02T10:00:01+00:00", providers_returned={}, key=KEY, role_key=_crosspost_key, board_evidence=BOARD, run_id="b")
    assert ledger["jobs"][ID]["closedAt"] == "2026-11-02T10:00:01+00:00"


def test_an_entry_closed_before_s5c_stays_as_it_is_and_says_nothing_about_two_checks():
    ledger = seen(GONE)
    ledger["jobs"][ID]["closedAt"] = iso(1)
    before = copy.deepcopy(ledger["jobs"][ID])
    out, _ = apply(ledger, [], 2, evidence=BOARD)
    assert ledger["jobs"][ID] == before and row(out, GONE)["isClosed"] is True and "closedAfterChecks" not in row(out, GONE)


def test_rows_with_no_miss_keep_their_keys_and_a_marked_row_keeps_marks_out_of_the_snapshot():
    keep = ad(1)
    ledger = seen(keep, GONE)
    out, _ = apply(ledger, [keep], 1, evidence=BOARD)
    assert not {"isAbsent", "absentSince", "closedAfterChecks"} & set(row(out, keep))
    assert not {"isAbsent", "absentSince", "closedAfterChecks", "absentRuns"} & set(ledger["jobs"][ID]["job"])
    back = {**row(out, GONE)}
    apply(ledger, [back], 2, evidence=BOARD)
    assert not {"isAbsent", "absentSince", "closedAfterChecks"} & set(ledger["jobs"][ID]["job"])


# --- classes -----------------------------------------------------------------------------------------------------------


def test_the_classes():
    assert jh.source_class("greenhouse") == jh.source_class("lever") == jh.source_class("ashby") == "snapshot"
    assert jh.source_class("infostud") == "unclassified"
    assert jh.source_class("jobspy") == jh.source_class("workable") == jh.source_class("joberty") == jh.source_class("newthing") == "search"
    assert jh.CLOSURE_PROVIDERS == {"greenhouse", "lever", "ashby"}


@pytest.mark.parametrize("provider", ["jobspy", "workable", "joberty", "infostud", "newthing"])
def test_search_based_and_unclassified_never_close_and_are_not_shown_or_marked(provider):
    gone = ad(2, provider)
    ledger = seen(gone)
    evidence = {provider: {"acme": complete()}}  # even if something handed it evidence
    for day in range(1, 6):
        out, stats = apply(ledger, [], day, evidence=evidence)
        assert row(out, gone) is None, "as before S5c; S5e decides this"
        assert stats["closed"] == stats["absent"] == 0
    assert ledger["jobs"][gone["jobId"]]["closedAt"] is None and "absentRuns" not in ledger["jobs"][gone["jobId"]]


# --- the importer's evidence -------------------------------------------------------------------------------------------


def staged(tmp_path, boards, *, source="greenhouse", footer=None, run_id="run0000aaaaaa", status_ok=True):
    """`boards`: {board: (kept, dropped, row)}, row being the boardsRead line, or None to leave it out."""
    run = staging.StagingRun.begin(tmp_path, run_id, search_key=KEY, terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=[], providers=[source])
    writer = run.open_source(source)
    rows = []
    for board, (kept, dropped, line) in boards.items():
        writer.append(kept, part=board, read=len(kept) + len(dropped), dropped=[{"job": j, "reason": "search_terms_not_matched", "externalId": "x"} for j in dropped])
        if line is not None:
            rows.append(line)
    writer.finish(status="ok", complete=True, read=0, kept=0, boardsRead=rows, boardsFailed=[], boardsEmpty=[], discardMismatch=False, **(footer or {}))
    run.finish()
    return staging.read_run(tmp_path, run_id)


def proof(board, n, **extra):
    return board_read(board, read=n, postings=n, complete=True, reason=None, **extra)


def evidence_of(run, name="greenhouse"):
    stage = run.sources[name]
    return importer.board_evidence(run, name, stage, stage.footer, False)


def test_a_proven_board_lists_what_it_kept_and_what_the_filter_dropped(tmp_path):
    kept, dropped = ad(1), ad(2)
    one = evidence_of(staged(tmp_path, {"acme": ([kept], [dropped], proof("acme", 2))}))["acme"]
    assert one["complete"] is True and one["listed"] == {kept["jobId"], dropped["jobId"]}


def test_a_run_with_no_boardsread_gives_no_evidence(tmp_path):
    run = staging.StagingRun.begin(tmp_path, "run0000aaaaaa", search_key=KEY, terms=[], locations=[], country="", remote_filters=[], providers=["greenhouse"])
    writer = run.open_source("greenhouse")
    writer.append([ad(1)], part="acme", read=1)
    writer.finish(status="ok", complete=True, read=1, kept=1)
    run.finish()
    assert evidence_of(staging.read_run(tmp_path, "run0000aaaaaa")) == {}


@pytest.mark.parametrize("line", [
    board_read("acme", read=1, postings=1, complete=False, reason="no proof"),
    proof("acme", 1, anomalies=["paging field in the answer: next"]),
    proof("acme", 5),
])
def test_an_unproven_anomalous_or_unbalanced_board_is_not_complete(tmp_path, line):
    assert evidence_of(staged(tmp_path, {"acme": ([ad(1)], [], line)}))["acme"]["complete"] is False


def test_a_failed_or_empty_board_is_not_complete_whatever_its_line_says(tmp_path):
    for field, name in (("boardsFailed", "f"), ("boardsEmpty", "e")):
        root = tmp_path / name
        root.mkdir()
        run = staged(root, {"acme": ([ad(1)], [], proof("acme", 1))})
        run.sources["greenhouse"].footer[field] = ["acme"]
        assert evidence_of(run)["acme"]["complete"] is False


def test_a_lost_or_torn_discard_stops_the_board_counting_so_a_filtered_ad_cannot_look_gone(tmp_path):
    dropped = ad(2)
    run = staged(tmp_path, {"acme": ([ad(1)], [dropped], proof("acme", 2))})
    gone = copy.deepcopy(run)
    gone.discards.records = []
    assert evidence_of(gone)["acme"]["complete"] is False, "the books do not balance"
    torn = copy.deepcopy(run)
    torn.discards.torn = True
    assert evidence_of(torn)["acme"]["complete"] is False
    no_id = copy.deepcopy(run)
    no_id.discards.records[0]["jobId"] = None
    assert evidence_of(no_id)["acme"]["complete"] is False
    missing = copy.deepcopy(run)
    missing.discards = None
    assert evidence_of(missing)["acme"]["complete"] is False


def test_a_source_in_doubt_gives_no_complete_board(tmp_path):
    run = staged(tmp_path, {"acme": ([ad(1)], [], proof("acme", 1))})
    stage = run.sources["greenhouse"]
    assert importer.board_evidence(run, "greenhouse", stage, stage.footer, True)["acme"]["complete"] is False


@pytest.mark.parametrize("footer", [{"mismatch": True}, {"invalid": 1}])
def test_plan_import_gives_no_closing_from_a_source_with_an_anomaly(tmp_path, footer):
    gone = ad(2)
    ledger = seen(gone)
    run = staged(tmp_path, {"acme": ([ad(1)], [], proof("acme", 1))}, footer=footer)
    result = importer.plan_import(run, ledger, None, now=iso(1))
    assert "absentRuns" not in result.ledger["jobs"][gone["jobId"]] and result.stats["keptSourceNotRun"] == 1


def test_plan_import_counts_a_miss_from_a_proven_board_and_reports_it(tmp_path):
    gone = ad(2)
    ledger = seen(gone)
    run = staged(tmp_path, {"acme": ([ad(1)], [], proof("acme", 1))})
    result = importer.plan_import(run, ledger, None, now=iso(1))
    assert result.ledger["jobs"][gone["jobId"]]["absentRuns"] == 1 and result.report["ledgerChanges"]["absent"] == 1
    assert result.report["boardsProvenComplete"] == ["greenhouse/acme"]
    assert result.view["jobs"] == derive_view(result.ledger)["jobs"], "the row shown comes from the ledger alone"
    assert ledger["jobs"][gone["jobId"]].get("absentRuns") is None, "the ledger passed in is not touched"


def discover(root, monkeypatch, providers):
    """The real run_discovery, with a search the fake postings match."""
    monkeypatch.setattr(run_discovery, "ROOT", root)
    intelligence = root / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": ["product manager"], "locationFilters": ["Remote"], "remoteFilters": ["remote"],
    }}))
    monkeypatch.setattr(run_discovery, "get_provider", lambda name: providers[name])
    monkeypatch.setattr(run_discovery, "effective_provider_names", lambda spec: list(providers))
    monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--providers", "x", "--intelligence", str(intelligence)])
    return run_discovery.main()


# --- real providers: Ashby never, Lever empty never ----------------------------------------------------------------------


class Answer:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.body


def run_real(root, monkeypatch, name, provider, loader, boards, get):
    monkeypatch.setattr(provider, loader, lambda: boards)
    monkeypatch.setattr(requests, "get", get)
    assert discover(root, monkeypatch, {name: provider}) == 0
    return json.loads((root / "data/jobs/job_history.json").read_text())


ASHBY_POST = lambda i: {"id": str(i), "title": f"Product Manager {i}", "location": "Remote", "jobUrl": f"https://a.example/{i}", "descriptionPlain": "Own the roadmap. " * 30}  # noqa: E731


def test_ashby_never_closes_an_ad_however_many_runs_miss_it(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    answer = {"jobs": [ASHBY_POST(1), ASHBY_POST(2)], "apiVersion": "1"}
    get = lambda url, **_: Answer(answer)  # noqa: E731
    ledger = run_real(root, monkeypatch, "ashby", ashby_provider.AshbyProvider(), "_load_companies", ["acme"], get)
    assert len(ledger["jobs"]) == 2
    answer = {"jobs": [ASHBY_POST(1)], "apiVersion": "1"}
    for _ in range(4):
        ledger = run_real(root, monkeypatch, "ashby", ashby_provider.AshbyProvider(), "_load_companies", ["acme"], get)
    assert not any(e["closedAt"] or e.get("absentRuns") for e in ledger["jobs"].values())
    view = json.loads((root / "data/jobs/discovered_jobs.json").read_text())
    assert len(view["jobs"]) == 2 and view["meta"]["history"]["keptUnproven"] == 1


def test_an_empty_lever_board_never_counts(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    post = {"id": "1", "text": "Product Manager", "categories": {"location": "Remote"}, "hostedUrl": "https://l.example/1", "descriptionPlain": "Own the roadmap. " * 30}
    lists = {"now": [post]}

    def get(url, params=None, **_):
        return Answer([] if params else lists["now"])

    ledger = run_real(root, monkeypatch, "lever", lever_provider.LeverProvider(), "_load_companies", ["acme"], get)
    assert len(ledger["jobs"]) == 1
    lists["now"] = []
    for _ in range(3):
        ledger = run_real(root, monkeypatch, "lever", lever_provider.LeverProvider(), "_load_companies", ["acme"], get)
    entry = next(iter(ledger["jobs"].values()))
    assert entry["closedAt"] is None and "absentRuns" not in entry


# --- the replay: real run_discovery -> staging -> importer -> ledger -> view -------------------------------------------


class Board:
    """The public Greenhouse answer of one board, as a real GreenhouseProvider reads it."""

    def __init__(self):
        self.jobs, self.fail = [], False

    def get(self, url, **_):
        if self.fail:
            return Answer({}, 500)
        return Answer({"jobs": self.jobs, "meta": {"total": len(self.jobs)}})


def posting(n, title=None):
    return {"id": n, "title": title or f"Product Manager {n}", "location": {"name": "Remote"}, "absolute_url": f"https://g.example/{n}", "content": "Own the roadmap. " * 30}


def test_the_replay_a_snapshot_ad_goes_absent_closes_and_reopens_through_the_real_path(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    jobs_dir = root / "data/jobs"
    board = Board()
    monkeypatch.setattr(requests, "get", board.get)

    def step(expect=0):
        provider = greenhouse_provider.GreenhouseProvider()
        monkeypatch.setattr(provider, "_load_boards", lambda: [{"company": "Acme", "board": "acme"}])
        assert discover(root, monkeypatch, {"greenhouse": provider}) == expect
        ledger = json.loads((jobs_dir / "job_history.json").read_text())
        view = json.loads((jobs_dir / "discovered_jobs.json").read_text())
        state = view_state(jobs_dir / "discovered_jobs.json", jobs_dir / "job_history.json")
        assert state["consistent"] and state["ledgerGeneration"] == view["meta"]["ledgerGeneration"] == ledger["generation"]
        assert derive_view(ledger) == view, "the view is what the ledger gives"
        return ledger, view

    def by_title(view, title):
        return next((j for j in view["jobs"] if j["title"] == title), None)

    title_a = "Product Manager 2"
    # 1. baseline
    board.jobs = [posting(1), posting(2)]
    ledger, view = step()
    assert ledger["generation"] == 1 and len(view["jobs"]) == 2
    ad_a = by_title(view, title_a)
    assert ad_a["isClosed"] is False and "isAbsent" not in ad_a
    job_id, first_seen = ad_a["jobId"], ad_a["firstSeen"]
    # facts a run of enrichment left, which must come back with the ad
    ledger["jobs"][job_id]["llmFacts"] = {"_fingerprint": jh.job_fingerprint(ledger["jobs"][job_id]["job"]), "workMode": "remote"}
    (jobs_dir / "job_history.json").write_text(json.dumps(ledger, indent=2))
    (jobs_dir / "discovered_jobs.json").write_text(json.dumps(derive_view(ledger), indent=2))
    # 2. the board drops ad A: absent, shown, marked
    board.jobs = [posting(1)]
    ledger, view = step()
    entry = ledger["jobs"][job_id]
    assert ledger["generation"] == 2 and entry["absentRuns"] == 1 and entry["absentSince"] and entry["closedAt"] is None
    ad_a = by_title(view, title_a)
    assert ad_a["isAbsent"] is True and ad_a["isClosed"] is False and ad_a["absentSince"] == entry["absentSince"]
    assert view["meta"]["history"]["absent"] == 1 and view["meta"]["dedupedCount"] == 1, "found is what was found"
    absent_since = entry["absentSince"]
    # 3. the board fails: no change
    board.fail = True
    before = ((jobs_dir / "job_history.json").read_bytes(), (jobs_dir / "discovered_jobs.json").read_bytes())
    # S8b: the board is the run's only source and it failed, so nothing is imported (exit 1): not even the generation moves, and the
    # ledger and the view are the bytes step 2 left. (Before S8b this run held the entries and moved the generation to 3.)
    ledger, view = step(expect=1)
    assert ((jobs_dir / "job_history.json").read_bytes(), (jobs_dir / "discovered_jobs.json").read_bytes()) == before
    entry = ledger["jobs"][job_id]
    assert ledger["generation"] == 2 and entry["absentRuns"] == 1 and entry["absentSince"] == absent_since and entry["closedAt"] is None
    assert by_title(view, title_a)["isAbsent"] is True
    # 4. still missing: closed
    board.fail = False
    ledger, view = step()
    entry = ledger["jobs"][job_id]
    assert ledger["generation"] == 3 and entry["closedAt"] and entry["absentRuns"] == 2
    ad_a = by_title(view, title_a)
    assert ad_a["isClosed"] is True and ad_a["closedAfterChecks"] == 2 and "isAbsent" not in ad_a and view["meta"]["history"]["closed"] == 1
    # 5. listed again: reopened, with firstSeen and facts kept
    board.jobs = [posting(1), posting(2)]
    ledger, view = step()
    entry = ledger["jobs"][job_id]
    assert ledger["generation"] == 4 and view["meta"]["history"]["reopened"] == 1 and entry["closedAt"] is None and "absentRuns" not in entry
    ad_a = by_title(view, title_a)
    assert ad_a["isClosed"] is False and "isAbsent" not in ad_a and ad_a["firstSeen"] == first_seen
    assert ad_a["llmFacts"]["workMode"] == "remote" and entry["llmFacts"]["workMode"] == "remote"
