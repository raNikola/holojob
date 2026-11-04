"""S7a: the reasons a source or a board did or did not count as proven, and the import block of a run record.

The importer only reports here: `test_the_rule_is_what_it_always_was` pins that the answer (proven or not) is the old rule's, over a grid.
"""

import json
from pathlib import Path

import pytest
import requests

import importer
import proof_reasons as proof
import row_state  # noqa: F401
import staging
from providers import ashby_provider, greenhouse_provider, lever_provider
from providers.base_provider import _settled_boards, board_read
from test_import import canon
from test_cancel_run import managed  # noqa: F401  (fixture)
from test_stale import GOOD, JOB, KEY, OTHER, board_run, day, good_run, imported, ledger_at, staged

ROOT = Path(__file__).resolve().parents[2]
TABLE = json.loads((ROOT / "src/data/proofReasons.json").read_text(encoding="utf-8"))


# --- the shared file ------------------------------------------------------------------------------------------------------------


def test_python_and_the_shared_file_name_the_same_codes():
    assert set(TABLE) == set(proof.ALL_CODES), "a code in one and not the other"
    for code, entry in TABLE.items():
        assert entry["group"] in ("search", "board") and isinstance(entry["text"], str) and entry["text"].strip(), code
        assert entry["text"].startswith(("Proven", "Not proven")), f"{code}: a bare true/false is not an explanation"


def test_every_text_a_provider_gives_for_an_incomplete_board_has_its_own_code(monkeypatch):
    texts = {
        greenhouse_provider.board_completeness(3, None)[1], greenhouse_provider.board_completeness(3, 5)[1],
        ashby_provider.NO_PROOF,
        *(row["reason"] for row in _settled_boards([], {"a": "x"}, ["b"])),
    }
    lever = lever_provider.LeverProvider()
    texts.add(lever._end_of_list("acme", 3)[1])
    lever._answered_at["acme"] = "https://api.lever.co/v0/postings/acme"

    class Answer:
        def __init__(self, body=None, fail=None):
            self.body, self.fail = body, fail

        def raise_for_status(self):
            if self.fail:
                raise self.fail

        def json(self):
            return self.body

    for answer in (Answer(fail=RuntimeError("down")), Answer({"not": "a list"}), Answer([{"id": 1}])):
        monkeypatch.setattr(requests, "get", lambda *a, answer=answer, **k: answer)
        texts.add(lever._end_of_list("acme", 3)[1])
    codes = {proof.board_reason_code(text) for text in texts}
    assert proof.BOARD_NOT_COMPLETE not in codes, [t for t in texts if proof.board_reason_code(t) == proof.BOARD_NOT_COMPLETE]
    assert len(codes) == len(texts), "each provider text maps to a code of its own"
    assert proof.board_reason_code("something a provider says tomorrow") == proof.BOARD_NOT_COMPLETE
    assert proof.board_reason_code(None) == proof.BOARD_NOT_COMPLETE


# --- the rule is what it always was ---------------------------------------------------------------------------------------------


def old_rule(run, stage, footer, state, anomalies):
    """`_search_run_proven` as S5f wrote it, copied here as the oracle."""
    if state != "complete" or anomalies or not footer or stage.torn or footer.get("discardMismatch") or footer.get("boardsFailed"):
        return False
    if run.discards is None or run.discards.torn or run.discards.unreadable_lines or run.discards.rejected:
        return False
    return (footer.get("read") or 0) > 0


FOOTERS = [
    {}, {"status": "failed", "complete": False}, {"status": "partial", "complete": False}, {"status": "skipped", "complete": False},
    {"read": 0, "kept": 0}, {"discardMismatch": True}, {"boardsFailed": ["acme"]}, {"mismatch": True}, None,
]


@pytest.mark.parametrize("footer", FOOTERS, ids=lambda f: "none" if f is None else "-".join(f) or "plain")
@pytest.mark.parametrize("damage", [None, "torn", "discards"])
def test_the_rule_is_what_it_always_was(tmp_path, monkeypatch, footer, damage):
    staged(tmp_path, monkeypatch, "r", day(0), {"jobspy": ([JOB], footer, [])})
    run = staging.read_run(tmp_path, "r")
    stage = run.sources["jobspy"]
    if damage == "torn":
        stage.torn = True
    if damage == "discards":
        run.discards.rejected = 1
    f = stage.footer if stage.usable else None
    status = f.get("status") if f else None
    state = "unfinished" if f is None else {"ok": "complete", "partial": "partial", "failed": "failed", "skipped": "skipped"}.get(status, "unfinished")
    anomalies = ["x"] if f and f.get("mismatch") else []
    reasons = importer._search_proof_reasons(run, stage, f, state, [proof.STAGED_DIFFERS] if anomalies else [])
    assert importer._search_run_proven(run, stage, f, state, anomalies) == old_rule(run, stage, f, state, anomalies)
    assert (reasons == []) == old_rule(run, stage, f, state, anomalies)
    assert set(reasons) <= proof.ALL_CODES


# --- the reasons, one by one ----------------------------------------------------------------------------------------------------


def report_of(root, run_id, **kw):
    return importer.plan_import(staging.read_run(root, run_id), importer.job_history.load(root / "data/jobs/job_history.json"), None, force=True, **kw).report


@pytest.mark.parametrize("footer, code", [
    ({"status": "failed", "complete": False}, proof.SOURCE_FAILED),
    ({"status": "partial", "complete": False}, proof.SOURCE_PARTIAL),
    ({"status": "skipped", "complete": False}, proof.SOURCE_SKIPPED),
    ({"read": 0, "kept": 0}, proof.NOTHING_READ),
    ({"discardMismatch": True}, proof.DISCARDS_MISMATCH),
    ({"boardsFailed": ["acme"]}, proof.PARTS_FAILED),
])
def test_a_search_source_says_why_it_did_not_count(tmp_path, monkeypatch, footer, code):
    staged(tmp_path, monkeypatch, "r", day(0), {"jobspy": ([JOB], footer, [])})
    one = report_of(tmp_path, "r")["proof"]["jobspy"]
    assert one["proven"] is False and code in one["why"] and proof.PROVEN not in one["why"] and one["boards"] == []


def test_a_source_that_never_finished_is_not_finished(tmp_path, monkeypatch):
    staged(tmp_path, monkeypatch, "r", day(0), {"jobspy": ([JOB], None, [])})
    one = report_of(tmp_path, "r")["proof"]["jobspy"]
    assert one["proven"] is False and one["why"][0] == proof.NOT_FINISHED


def test_ads_that_are_not_whole_and_staged_ads_that_differ_are_named(tmp_path, monkeypatch):
    broken = {**canon(5, provider="jobspy"), "jobUrl": "javascript:x"}  # staged, but the importer's validation rejects it: a lost ad
    staged(tmp_path, monkeypatch, "r", day(0), {"jobspy": ([JOB, broken], GOOD, [])})
    one = report_of(tmp_path, "r")["proof"]["jobspy"]
    assert one["proven"] is False and proof.ADS_NOT_WHOLE in one["why"]
    staged(tmp_path, monkeypatch, "m", day(1), {"jobspy": ([JOB], {"mismatch": True}, [])})
    assert proof.STAGED_DIFFERS in report_of(tmp_path, "m")["proof"]["jobspy"]["why"]


def test_a_source_that_did_everything_right_is_proven_with_its_one_reason(tmp_path, monkeypatch):
    staged(tmp_path, monkeypatch, "r", day(0), {"jobspy": ([JOB], GOOD, [])})
    assert report_of(tmp_path, "r")["proof"]["jobspy"] == {"proven": True, "why": [proof.PROVEN], "boards": []}


def test_a_run_with_no_search_key_proves_nothing(tmp_path, monkeypatch):
    staged(tmp_path, monkeypatch, "r", day(0), {"jobspy": ([JOB], GOOD, [])}, key="")
    one = report_of(tmp_path, "r")["proof"]["jobspy"]
    assert one["proven"] is False and one["why"] == [proof.NO_SEARCH_KEY]


def test_a_board_says_why_it_is_or_is_not_complete(tmp_path, monkeypatch):
    job, other = canon(1, source="acme"), canon(2, source="acme")
    board_run(tmp_path, monkeypatch, "a", day(0), "greenhouse", [job, other])
    one = report_of(tmp_path, "a")["proof"]["greenhouse"]
    assert one["proven"] is True and one["why"] == [proof.BOARD_COMPLETE]
    assert one["boards"] == [{"board": "acme", "proven": True, "why": [proof.BOARD_COMPLETE], "detail": None}]

    board_run(tmp_path, monkeypatch, "b", day(1), "greenhouse", [job], complete=False)
    one = report_of(tmp_path, "b")["proof"]["greenhouse"]
    assert one["proven"] is False and proof.BOARDS_NOT_PROVEN in one["why"]
    assert one["boards"][0]["why"] == [proof.BOARD_NOT_COMPLETE] and one["boards"][0]["proven"] is False

    board_run(tmp_path, monkeypatch, "c", day(2), "greenhouse", [job], failed=["acme"])
    assert proof.BOARD_UNREADABLE in report_of(tmp_path, "c")["proof"]["greenhouse"]["boards"][0]["why"]


def test_a_board_whose_files_do_not_add_up_is_not_proven_and_says_so(tmp_path, monkeypatch):
    """The provider says it read 3 postings of the board, but the run's files hold 1 ad and no discard for the other 2."""
    with monkeypatch.context() as patch:
        patch.setattr(staging, "_now", lambda: day(0))
        run = staging.StagingRun.begin(tmp_path, "r", search_key=KEY, terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=[], providers=["greenhouse"])
        writer = run.open_source("greenhouse")
        writer.append([canon(1, source="acme")], part="acme", read=1)
        writer.finish(status="ok", complete=True, read=3, kept=1, boardsFailed=[],
                      boardsRead=[board_read("acme", read=3, postings=3, complete=True, reason=None)])
        run.finish()
    boards = report_of(tmp_path, "r")["proof"]["greenhouse"]["boards"]
    assert boards[0]["proven"] is False and proof.FILES_DONT_ADD_UP in boards[0]["why"] and proof.BOARD_COMPLETE not in boards[0]["why"]


def test_a_board_source_with_no_per_board_proof_says_so(tmp_path, monkeypatch):
    staged(tmp_path, monkeypatch, "r", day(0), {"greenhouse": ([canon(1, source="acme")], GOOD, [])})
    one = report_of(tmp_path, "r")["proof"]["greenhouse"]
    assert one["proven"] is False and proof.NO_BOARD_EVIDENCE in one["why"] and one["boards"] == []


def test_the_boards_the_proof_calls_complete_are_the_boards_the_import_closes_on(tmp_path, monkeypatch):
    job = canon(1, source="acme")
    board_run(tmp_path, monkeypatch, "a", day(0), "greenhouse", [job])
    report = report_of(tmp_path, "a")
    proven = sorted(f"greenhouse/{b['board']}" for b in report["proof"]["greenhouse"]["boards"] if b["proven"])
    assert proven == report["boardsProvenComplete"]


def test_a_cancelled_run_proves_nothing_whatever_its_footers_say(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    staging.mark_cancelled(tmp_path, "b")
    one = report_of(tmp_path, "b")["proof"]["jobspy"]
    assert one["proven"] is False and proof.RUN_CANCELLED in one["why"] and proof.PROVEN not in one["why"]


# --- filter reasons and the block -----------------------------------------------------------------------------------------------


def test_filter_reasons_are_counted_per_source_and_grouped_by_their_prefix(tmp_path, monkeypatch):
    from providers.base_provider import dropped_ad
    from test_filtered_ads import ad

    drops = [dropped_ad({**ad(n), "jobId": f"d{n}", "jobUrl": f"https://x.example/{n}"}, reason, "e")
             for n, reason in enumerate(["title_not_matched", "title_not_matched", "title_excluded:intern", "title_excluded:sales"])]
    staged(tmp_path, monkeypatch, "r", day(0), {"jobspy": ([JOB], GOOD, drops)})
    assert report_of(tmp_path, "r")["filterReasons"]["jobspy"] == {"title_excluded": 2, "title_not_matched": 2}


def test_the_block_of_an_ordinary_run_says_saved_new_and_refreshed_apart(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    outcome = good_run(tmp_path, monkeypatch, "b", day(10), ads=(JOB, OTHER, canon(3, provider="jobspy")))
    block = importer.evidence_block(outcome.result.report, outcome.result.stats)
    assert (block["kind"], block["saved"], block["new"], block["refreshed"]) == ("complete", 3, 1, 2)
    assert block["complete"] is True and block["ledger"] == {"closed": 0, "absent": 0, "reopened": 0, "changed": 0, "known": 2}
    assert block["sources"][0]["name"] == "jobspy" and block["sources"][0]["proof"]["proven"] is True


def test_the_block_of_a_cancelled_run_says_saved_includes_refreshed(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB, OTHER, canon(3, provider="jobspy")], GOOD, [])})
    staging.mark_cancelled(tmp_path, "b")
    outcome = imported(tmp_path, "b")
    block = importer.evidence_block(outcome.result.report, outcome.result.stats)
    assert (block["kind"], block["saved"], block["new"], block["refreshed"]) == ("partial", 3, 1, 2)
    assert "ledger" not in block and block["complete"] is False
    assert block["sources"][0]["proof"]["why"] == [proof.RUN_CANCELLED]


def test_the_block_of_a_cancelled_run_that_saved_nothing(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([], GOOD, [])})
    staging.mark_cancelled(tmp_path, "b")
    outcome = imported(tmp_path, "b")
    block = importer.evidence_block(outcome.result.report, outcome.result.stats)
    assert (block["kind"], block["saved"], block["new"], block["refreshed"], block["nothingSaved"]) == ("nothing", 0, 0, 0, "no_valid_ads")


def test_the_block_holds_counts_and_codes_only(tmp_path, monkeypatch):
    canary = {**canon(9, provider="jobspy"), "title": "CANARY-TITLE", "description": "CANARY-DESCRIPTION", "company": "CANARY-COMPANY"}
    outcome = good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, canary))
    text = json.dumps(importer.evidence_block(outcome.result.report, outcome.result.stats))
    assert "CANARY" not in text and canary["jobUrl"] not in text


# --- the record -----------------------------------------------------------------------------------------------------------------


def test_a_new_record_carries_the_block_and_each_source_s_times(managed, tmp_path):
    code, record = managed("run00000001", jobs=("g1", "g2"))
    assert code == 0
    block = record["import"]
    assert (block["kind"], block["saved"], block["new"], block["refreshed"]) == ("complete", 2, 2, 0)
    assert block["sources"][0]["proof"]["why"] == [proof.PROVEN] and block["sources"][0]["name"] == "jobspy"
    source = record["sources"][0]
    assert source["startedAt"] <= source["finishedAt"] and record["startedAt"] <= source["startedAt"]
    code, record = managed("run00000002", jobs=("g1", "g3"))
    assert (record["import"]["saved"], record["import"]["new"], record["import"]["refreshed"]) == (2, 1, 1)


def test_a_cancelled_run_record_says_the_same_in_its_block(managed, tmp_path):
    from providers.base_provider import ProviderOutcome  # noqa: F401
    import run_log

    managed("run00000001")
    code, record = managed("run00000002", jobs=("g1", "g4"), act=lambda provider, record: run_log.request_cancel(record))
    assert code == run_log.EXIT_CANCELLED
    block = record["import"]
    assert (block["kind"], block["saved"], block["new"], block["refreshed"]) == ("partial", 2, 1, 1)
    assert record["cancel"]["saved"] == 2 and block["sources"][0]["proof"]["why"] == [proof.RUN_CANCELLED]


def test_a_refused_import_is_a_block_of_its_own_kind(managed, tmp_path, monkeypatch):
    import run_discovery

    monkeypatch.setattr(run_discovery.importer, "import_staged_run", lambda *a, **k: importer.ImportOutcome(ok=False, run_id="x", refused=["older_run: test"]))
    code, record = managed("run00000001")
    assert code == 1 and record["import"] == {"kind": "refused", "saved": 0, "new": 0, "refreshed": 0, "sources": []}
