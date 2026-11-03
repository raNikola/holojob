"""Readers of the job list and the rows a run did not find (slice S5d). Offline; every path is under tmp_path."""

import json
import sys
from pathlib import Path

import pytest

from conftest import select_provider
import enrich_jobs
import job_history as jh
import row_state
import run_pipeline as rp
import run_scoring
import view_guard
from llm_enhancer import LlmFitEnhancer
from match_engine import shadow
from scorer import score_jobs
from test_job_history import facts_for
from test_engine_shadow import engine as make_engine, job as engine_job, Fake as EngineFake

INTEL = {
    **json.loads((Path(__file__).parent / "fixtures" / "candidate-intelligence.json").read_text(encoding="utf-8")),
    # the keywords whose rarity moves a score: without them no row could move another, and the corpus tests would prove nothing
    "atsKeywordBank": {"highPriority": ["roadmap", "SQL", "discovery", "stakeholders"], "mediumPriority": ["analytics", "Python"], "supportingKeywords": ["backlog", "fintech"]},
}
NOW = "2026-11-03T10:00:00+00:00"
OLD = "2026-10-25T10:00:00+00:00"
META = {"ledgerGeneration": 3, "generatedAt": NOW, "history": {}}


def row(job_id, title="Senior Product Manager", description="Own the product roadmap and discovery with SQL analytics.", seen=NOW, **extra):
    return {"jobId": job_id, "title": title, "company": "Acme", "location": "Remote", "description": description, "jobUrl": f"https://x/{job_id}",
            "provider": "greenhouse", "status": "new", "firstSeen": OLD, "lastSeen": seen, "closedAt": None, "isNew": False, "isClosed": False, **extra}


ACTIVE = [row("a1"), row("a2", "Product Owner", "Backlog grooming and stakeholders for a fintech product."), row("a3", "Data Analyst", "SQL dashboards and Python.")]
RARE = "Zebrafish quokka narwhal ocelot pangolin roadmap SQL Kubernetes stakeholders discovery " * 8
ABSENT = row("x1", "Senior Product Manager Kubernetes", RARE, seen=OLD, isAbsent=True, absentSince=NOW)
HELD = row("x2", "Staff Product Manager", RARE + " held", seen=OLD)
STALE = row("x3", "Principal Product Manager", RARE + " stale", seen=OLD, isStale=True)


# --- which row is which ------------------------------------------------------------------------------------------------


def test_a_found_row_is_stamped_with_the_views_time_and_anything_else_is_not_found():
    stamp = row_state.found_stamp(META)
    assert stamp == NOW and not row_state.not_found(ACTIVE[0], stamp)
    assert row_state.not_found(HELD, stamp) and row_state.not_found(ABSENT, stamp) and row_state.not_found(STALE, stamp)


def test_a_closed_or_hand_entered_row_is_never_counted_as_not_found():
    stamp = row_state.found_stamp(META)
    assert not row_state.not_found({**HELD, "isClosed": True}, stamp)
    assert not row_state.not_found({**HELD, "manualEntry": True}, stamp)
    assert not row_state.inactive({**HELD, row_state.MARK: True, "manualEntry": True})


@pytest.mark.parametrize("meta", [None, {}, {"generatedAt": NOW}, {"ledgerGeneration": 1}, "x"])
def test_a_view_the_importer_did_not_write_says_nothing_so_nothing_is_held(meta):
    assert row_state.found_stamp(meta) is None
    assert not row_state.not_found(HELD, None) and row_state.not_found(ABSENT, None), "the absent mark stands on its own"


def test_mark_changes_only_the_rows_not_found_and_not_the_rows_passed_in():
    rows = [ACTIVE[0], HELD]
    marked = row_state.mark(rows, META)
    assert marked[0] is ACTIVE[0] and marked[1][row_state.MARK] is True and row_state.MARK not in HELD


def test_counts():
    rows = [*ACTIVE, ABSENT, HELD, {**HELD, "jobId": "c", "isClosed": True}]
    assert row_state.counts(rows, META) == {"found": 3, "absent": 1, "held": 1, "closed": 1}


# --- the corpus --------------------------------------------------------------------------------------------------------


def test_the_extra_rows_would_move_scores_if_they_were_in_the_corpus():
    """Guards the next test: it proves nothing if these rows could not move a score anyway."""
    alone = score_jobs([dict(j) for j in ACTIVE], INTEL)
    unmarked = [{k: v for k, v in dict(j).items() if k not in ("isAbsent", "absentSince", "isStale")} for j in (ABSENT, HELD, STALE)]
    mixed = score_jobs([dict(j) for j in ACTIVE] + unmarked, INTEL)
    assert any(json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True) for a, b in zip(alone, mixed))


@pytest.mark.parametrize("extra", [[ABSENT], [HELD], [STALE], [ABSENT, HELD, STALE]], ids=["absent", "held", "stale", "all"])
def test_active_ads_score_byte_identical_with_and_without_rows_not_found(extra):
    alone = score_jobs([dict(j) for j in ACTIVE], INTEL)
    marked = row_state.mark([dict(j) for j in ACTIVE] + [dict(j) for j in extra], META)
    mixed = score_jobs(marked, INTEL)
    assert [json.dumps(r, sort_keys=True) for r in mixed[: len(ACTIVE)]] == [json.dumps(r, sort_keys=True) for r in alone]
    assert all(isinstance(r["matchScore"], (int, float)) for r in mixed), "the extra rows are scored too"


def test_a_corpus_of_nothing_but_rows_not_found_still_scores():
    assert score_jobs(row_state.mark([dict(HELD)], META), INTEL)[0]["matchScore"] >= 0


@pytest.fixture
def scoring(tmp_path, monkeypatch):
    (tmp_path / "intel.json").write_text(json.dumps(INTEL))
    (tmp_path / "profile.json").write_text("{}")
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])
    monkeypatch.setattr(shadow, "load_remap", lambda: {})

    def go(rows, meta=META, name="a"):
        jobs, out = tmp_path / f"{name}.json", tmp_path / "out" / f"{name}.scored.json"
        jobs.write_text(json.dumps({"meta": meta, "jobs": rows}))
        monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(jobs),
                                          "--manual", str(tmp_path / "manual.json"), "--output", str(out)])
        assert run_scoring.main() == 0
        return json.loads(out.read_text())

    return go


def test_a_real_scoring_run_gives_active_ads_the_same_bytes_and_marks_only_the_rows_not_found(scoring):
    alone = scoring(ACTIVE, name="alone")["jobs"]
    mixed = scoring([*ACTIVE, ABSENT, HELD], name="mixed")["jobs"]
    ids = {j["jobId"] for j in ACTIVE}
    pick = lambda rows: {r["jobId"]: json.dumps(r, sort_keys=True) for r in rows if r["jobId"] in ids}  # noqa: E731
    assert pick(alone) == pick(mixed)
    by_id = {r["jobId"]: r for r in mixed}
    assert by_id["x1"][row_state.MARK] is True and by_id["x2"][row_state.MARK] is True
    assert not any(row_state.MARK in by_id[i] for i in ids)
    assert "matchScore" in by_id["x1"] and "matchScore" in by_id["x2"]


def test_the_manual_path_marks_rows_as_a_full_run_does():
    """A hand-entered job is scored over the corpus a full run uses, so the manual path must leave the same rows out of it."""
    source = Path(__file__).parents[2] / "python/job_import/import_job_url.py"
    assert 'row_state.mark(discovered_jobs, discovered_doc.get("meta"))' in source.read_text(encoding="utf-8")


# --- enrichment --------------------------------------------------------------------------------------------------------


VIEW_META = {"rawCount": 1, "dedupedCount": 1, "sourceRunId": "r1", "searchTerms": [], "locations": [], "remoteFilters": [], "country": "Serbia",
             "providers": ["greenhouse"], "providerCounts": {"greenhouse": 1}, "history": {}}


def enrich(tmp_path, monkeypatch, facts_on=None, argv=()):
    """A ledger and view as an import leaves them: a1 found by the last run; x1 absent; x2 and x3 held. The real enrich_jobs reads them."""
    key_role = lambda job: job["title"]  # noqa: E731
    ledger = {"generation": 3, **jh.empty_ledger()}
    rows = [dict(ACTIVE[0]), dict(ABSENT), dict(HELD), {**HELD, "jobId": "x3", "title": "Principal Product Manager", "jobUrl": "https://x/x3"}]
    jh.apply_run(ledger, rows, now=OLD, providers_returned={}, key="k", role_key=key_role, run_id="r0", prune=False)
    jh.apply_run(ledger, rows[:1], now=NOW, providers_returned={}, key="k", role_key=key_role, run_id="r1", prune=False, sources_not_run={"greenhouse"})
    ledger["jobs"]["x1"].update(absentRuns=1, absentSince=NOW, lastAbsentRunId="r1")
    if facts_on:
        ledger["jobs"][facts_on]["llmFacts"] = {**facts_for(ledger["jobs"][facts_on]["job"]), "workMode": "remote"}
    ledger["lastImport"] = {"runId": "r1", "at": NOW, "startedAt": NOW, "meta": VIEW_META}
    jobs_file = tmp_path / "discovered_jobs.json"
    jh.ledger_path(jobs_file).write_text(view_guard.serialize_ledger(ledger))
    view = view_guard.derive_view(ledger)
    assert row_state.counts(view["jobs"], view["meta"]) == {"found": 1, "absent": 1, "held": 2, "closed": 0}
    jobs_file.write_text(view_guard.serialize_view(view))
    asked = []

    def fake(job, model, provider, previous=None):
        asked.append(job["jobId"])
        return facts_for(job)

    monkeypatch.setattr(enrich_jobs, "extract", fake)
    monkeypatch.setattr("sys.argv", ["enrich_jobs.py", "--jobs", str(jobs_file), "--workers", "1", "--intelligence", str(tmp_path / "none.json"), *argv])
    select_provider(tmp_path, monkeypatch, "claude-code")
    assert enrich_jobs.main() == 0
    return asked, jobs_file


@pytest.mark.parametrize("argv", [(), ("--force",)], ids=["plain", "force"])
def test_enrichment_makes_no_model_call_for_rows_not_found(tmp_path, monkeypatch, capsys, argv, open_ai_budget):
    asked, _ = enrich(tmp_path, monkeypatch, argv=argv)
    assert asked == ["a1"]
    assert "not found by this run 3 (no call)" in capsys.readouterr().out


def test_enrichment_keeps_facts_a_row_not_found_already_has(tmp_path, monkeypatch, open_ai_budget):
    asked, jobs_file = enrich(tmp_path, monkeypatch, facts_on="x2")
    written = {j["jobId"]: j for j in json.loads(jobs_file.read_text())["jobs"]}
    assert asked == ["a1"] and written["x2"]["llmFacts"]["workMode"] == "remote"


def test_the_enrichment_line_still_parses_for_the_pipeline_summary():
    import re

    line = "extracted 1, cached 2 (1 from the ledger), failed 0, not read 3 (outside your allowed locations), refused 0 (AI budget gate), not found by this run 3 (no call)"
    found = re.search(r"extracted (\d+), cached (\d+) \((\d+) from the ledger\), failed (\d+)(?:, not read (\d+)[^,]*)?(?:, refused (\d+))?", line)
    assert found.groups() == ("1", "2", "1", "0", "3", "0")


# --- the fit judge -----------------------------------------------------------------------------------------------------


class Judge:
    def __init__(self):
        self.calls = 0

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.calls += 1
        return {"fit": "good", "dealbreakers": [], "reason": "ok", "strengths": [], "gaps": [], "evidence": [], "missing": []}


HIGH = "Senior Product Manager"


def judged(rows, **kw):
    stub = Judge()
    judge = LlmFitEnhancer("openai", "gpt-4o", complete=stub, threshold=0, **kw)
    return score_jobs(row_state.mark([dict(r) for r in rows], META), INTEL, judge, workers=1), stub, judge


@pytest.mark.parametrize("limit", [None, 1], ids=["no-limit", "limit"])
def test_the_judge_never_calls_for_a_row_not_found_and_it_takes_no_place_under_the_limit(limit):
    rows = [dict(ABSENT), dict(HELD), dict(STALE), dict(ACTIVE[0])]
    _, stub, judge = judged(rows, limit=limit)
    assert stub.calls == 1, "only the active row"
    assert judge.counts["not_active"] == 3


def test_a_judgement_already_paid_for_still_applies_so_the_score_does_not_jump(tmp_path):
    cache = tmp_path / "fit.json"
    stub = Judge()
    first = LlmFitEnhancer("openai", "gpt-4o", complete=stub, threshold=0, cache_path=cache)
    found = score_jobs([dict(ACTIVE[0])], INTEL, first, workers=1)
    first.save()
    assert stub.calls == 1
    again = Judge()
    second = LlmFitEnhancer("openai", "gpt-4o", complete=again, threshold=0, cache_path=cache)
    held = row_state.mark([{**ACTIVE[0], "lastSeen": OLD}], META)
    later = score_jobs(held, INTEL, second, workers=1)
    assert again.calls == 0 and later[0]["matchScore"] == found[0]["matchScore"] and second.counts["cached"] == 1


# --- the shadow engine -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mark", [{"isAbsent": True}, {"isStale": True}, {row_state.MARK: True}], ids=["absent", "stale", "held"])
def test_the_shadow_engine_sends_only_active_rows(tmp_path, mark):
    fake = EngineFake()
    one = make_engine(tmp_path, judge=True, fake=fake)
    rows = [engine_job("a", 90), engine_job("x", 95, **mark)]
    out = one.apply(rows)
    assert fake.calls == 1 and "engineShadow" in out[0] and "engineShadow" not in out[1]
    assert one.counts["notActive"] == 1


def test_a_row_not_found_takes_no_place_under_the_shadow_limit_or_in_the_preview(tmp_path):
    one = make_engine(tmp_path, judge=True, limit=1)
    rows = [engine_job("x", 95, isAbsent=True), engine_job("a", 90)]
    assert one.plan(rows) == {"a"}
    assert one.preview(rows)["toSend"] == 1


def test_the_shadow_preview_does_not_count_a_row_not_found_as_cached(tmp_path):
    first = make_engine(tmp_path, judge=True)
    first.apply([engine_job("x", 90)])
    first.save()
    later = make_engine(tmp_path, judge=True)
    assert later.preview([engine_job("x", 90)])["cached"] == 1
    assert later.preview([engine_job("x", 90, isAbsent=True)])["cached"] == 0


def test_a_shadow_answer_already_cached_still_applies(tmp_path):
    first = make_engine(tmp_path, judge=True)
    first.apply([engine_job("a", 90)])
    first.save()
    fake = EngineFake()
    later = make_engine(tmp_path, judge=True, fake=fake)
    out = later.apply([engine_job("a", 90, isAbsent=True)])
    assert fake.calls == 0 and "engineShadow" in out[0]


# --- the summaries -----------------------------------------------------------------------------------------------------


def test_the_share_of_enriched_jobs_does_not_count_rows_not_found():
    facts = {"llmFacts": {"_fingerprint": "x"}}
    rows = [{**ACTIVE[0], **facts}, {**ACTIVE[1], **facts}, dict(ABSENT), dict(HELD)]
    assert rp.enriched_share(rows, None, META) == 1.0
    assert rp.enriched_share(rows, None, None) == 2 / 3, "with no stamp a held row still counts; the absent mark stands"


def test_the_pipeline_summary_counts_found_rows_apart_and_absent_rows_on_their_own_line(capsys):
    rp.print_summary({"steps": [], "discovery": {"providerCounts": {"greenhouse": 2}, "raw": 2, "deduped": 2, "history": {"new": 1},
                                                 "rows": {"found": 2, "absent": 3, "held": 1, "closed": 4}}})
    out = capsys.readouterr().out
    assert "Job list  : 2 found by this run, 1 kept open, 4 closed and still shown" in out
    assert "Absent    : 3 not listed in the latest fetch" in out


def test_the_pipeline_summary_of_a_view_with_no_rows_field_prints_no_such_lines(capsys):
    rp.print_summary({"steps": [], "discovery": {"providerCounts": {}, "raw": 0, "deduped": 0, "history": {}}})
    out = capsys.readouterr().out
    assert "Job list" not in out and "Absent" not in out


def test_summarize_fills_in_the_row_counts(tmp_path, monkeypatch):
    view = tmp_path / "discovered_jobs.json"
    view.write_text(json.dumps({"meta": META, "jobs": [*ACTIVE, ABSENT, HELD]}))
    monkeypatch.setattr(rp, "DISCOVERED", view)
    monkeypatch.setattr(rp, "SCORED", tmp_path / "none.json")
    monkeypatch.setattr(rp, "read_view", lambda: json.loads(view.read_text()))
    summary = rp.summarize(None, [], None, None)
    assert summary["discovery"]["rows"] == {"found": 3, "absent": 1, "held": 1, "closed": 0}
