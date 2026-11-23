"""Re-scrape's one run budget: no limit in code, an unset limit spends nothing, the total never passes the limit, order and counting."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ai_gate
import classify_new
import enrich_jobs
import run_budget

ROOT = Path(__file__).resolve().parents[2]


# --- no limit in code -----------------------------------------------------------------------------------------------------------------------------
def test_an_unset_or_zero_limit_means_the_paid_steps_spend_nothing():
    assert ai_gate.run_limits({}) is None
    assert ai_gate.run_limits({"runLimitUsd": 1.0}) is None and ai_gate.run_limits({"runLimitAds": 5}) is None
    assert ai_gate.run_limits({"runLimitUsd": 0, "runLimitAds": 5}) is None
    assert run_budget.resolve_limits(None, None, {}).stop == "unset"
    assert run_budget.resolve_limits(None, None, {"runLimitUsd": 1.0}).stop == "unset", "one of two is not a limit"
    assert ai_gate.DEFAULT_SETTINGS["runLimitUsd"] is None and ai_gate.DEFAULT_SETTINGS["runLimitAds"] is None
    assert ai_gate.DEFAULT_SETTINGS["allowEngineFill"] is False


def test_a_flag_wins_over_settings_and_zero_means_used_up():
    limits = run_budget.resolve_limits(0.25, 7, {"runLimitUsd": 9, "runLimitAds": 99})
    assert (limits.usd, limits.ads, limits.stop) == (0.25, 7, None)
    assert run_budget.resolve_limits(0.0, 7, {}).stop == "run_usd" and run_budget.resolve_limits(0.25, 0, {}).stop == "run_ads"
    assert run_budget.resolve_limits(None, 7, {"runLimitUsd": 2}).usd == 2, "an omitted flag is read from Settings"


def test_no_script_carries_a_limit_literal():
    for path in ("python/job_scoring/classify_new.py", "python/job_scoring/run_budget.py", "python/run_rescrape.py", "python/run_pipeline.py"):
        text = (ROOT / path).read_text()
        assert not re.search(r'"--max-(usd|ads)",\s*"[\d.]+"', text), path
        assert not re.search(r"(DEFAULT_MAX|MAX_USD|MAX_ADS)\s*=\s*[\d.]+", text), path


def test_the_run_limits_are_validated_and_raising_them_needs_the_confirm():
    assert ai_gate.validate_settings({"runLimitUsd": -1})[1] and ai_gate.validate_settings({"runLimitAds": 1.5})[1]
    assert ai_gate.validate_settings({"allowEngineFill": "yes"})[1]
    assert not ai_gate.validate_settings({"runLimitUsd": None, "runLimitAds": None, "allowEngineFill": False})[1]
    assert ai_gate.save_settings({"runLimitUsd": 1.0})["needsConfirm"] is True
    assert ai_gate.save_settings({"allowEngineFill": True})["needsConfirm"] is True, "engine fill sends a redacted evidence index"
    saved = ai_gate.save_settings({"runLimitUsd": 1.0, "runLimitAds": 10, "allowEngineFill": True}, confirm=True)
    assert saved["ok"] and ai_gate.run_limits() == (1.0, 10) and ai_gate.engine_fill_allowed()
    assert ai_gate.save_settings({"runLimitUsd": 0.5, "allowEngineFill": False})["ok"], "lowering never asks"


# --- one budget: spend and distinct ads from the ledger ---------------------------------------------------------------------------------------------
def ledger_rows(start, calls):
    rows = []
    for index, (feature, job, cost, decision) in enumerate(calls):
        stamp = (start + timedelta(seconds=index + 1)).isoformat()
        rows += [{"type": "call", "id": f"c{index}", "ts": stamp, "feature": feature, "decision": decision, "jobId": job},
                 {"type": "result", "id": f"c{index}", "cost": cost}]
    return rows


def test_spend_and_distinct_ads_are_read_from_the_ledger_since_the_run_began():
    start = datetime.now(timezone.utc)
    before = [{"type": "call", "id": "old", "ts": (start - timedelta(hours=1)).isoformat(), "feature": "fit3-classify", "decision": "allowed", "jobId": "x"},
              {"type": "result", "id": "old", "cost": 5}]
    rows = before + ledger_rows(start, [("fit3-classify", "a", 0.1, "allowed"), ("enrichment", "a", 0.2, "allowed"), ("evidence-matcher", "b", 0.3, "allowed"),
                                        ("enrichment", "c", 9.0, "refused"), ("tailoring", "z", 4.0, "allowed")])
    usd, ads = run_budget.usage_since(start, rows)
    assert round(usd, 6) == 0.6 and ads == {"a", "b"}, "an ad handled by two steps counts once; a refused call, an older call and another feature do not count"
    assert run_budget.usage_since(start, rows, features=("enrichment",))[1] == {"a"}


def test_the_ads_limit_counts_distinct_ads_and_an_ad_already_counted_is_free():
    selected, waiting = run_budget.trim(["a", "x", "y", "b", "z"], 2, {"a", "b"})
    assert selected == ["a", "x", "y", "b"] and waiting == ["z"], "a and b were counted before: only x and y use the 2 new places"
    assert run_budget.trim(["a", "b"], 0, set()) == ([], ["a", "b"])


def test_the_total_spend_of_the_steps_never_passes_the_run_limit():
    """The orchestrator hands each step limit minus what the ledger says was spent; a step's own guard keeps it inside that."""
    limit, spent, started = 1.0, 0.0, datetime.now(timezone.utc)
    rows = []
    for step_cost in (0.45, 0.4, 0.4):
        remainder = max(0.0, limit - run_budget.usage_since(started, rows)[0])
        paid = min(step_cost, remainder)  # a step's guard refuses a call that could pass its remainder
        rows += ledger_rows(started + timedelta(seconds=len(rows)), [("fit3-classify", f"j{len(rows)}", paid, "allowed")])
        spent = run_budget.usage_since(started, rows)[0]
        assert spent <= limit + 1e-9
    assert round(spent, 6) == 1.0


# --- order ----------------------------------------------------------------------------------------------------------------------------------------
def test_this_runs_ads_come_first_then_strongest_first_and_weak_and_blocked_last():
    start = "2026-11-23T10:00:00+00:00"
    old, new = "2026-11-20T10:00:00+00:00", "2026-11-23T10:05:00+00:00"
    prior = {"s": {"matchScore": 80}, "p": {"matchScore": 60}, "w": {"matchScore": 30}, "b": {"matchScore": 90, "blockedBy": ["location"]},
             "k": {"matchScore": 90, "applyRecommendation": "Skip"}}
    jobs = [{"jobId": j, "firstSeen": old} for j in ("w", "b", "p", "s", "u", "k")] + [{"jobId": "n1", "firstSeen": new}, {"jobId": "n2", "firstSeen": new}]
    ordered = [j["jobId"] for j in sorted(jobs, key=lambda j: run_budget.order_key(j, prior, start))]
    assert ordered[:2] == ["n1", "n2"], "this run's ads first"
    assert ordered[2:] == ["s", "p", "u", "w", "k", "b"], "Strong, Possible, not scored, Weak (a Skip verdict is Weak), Blocked"


def test_the_tier_cutoffs_are_the_ones_of_the_jobs_list():
    text = (ROOT / "src/modules/jobs/fitTier.js").read_text()
    assert f"score >= {run_budget.STRONG_MIN} ? TIER_STRONG : score >= {run_budget.POSSIBLE_MIN} ? TIER_POSSIBLE" in text


# --- reading: only Target / Adjacent, never a blocked ad, weak last -------------------------------------------------------------------------------
def test_reading_plan_takes_target_and_adjacent_only_skips_blocked_and_reads_weak_last(monkeypatch, tmp_path):
    import role_class

    classes = {"t1": "target", "a1": "adjacent", "o1": "other", "w1": "target", "b1": "target", "n1": "target"}
    monkeypatch.setattr(role_class, "label", lambda rows, path=None: [r.update(roleClass=classes[r["jobId"]]) for r in rows])
    scored = tmp_path / "scored.json"
    scored.write_text(json.dumps({"jobs": [{"jobId": "t1", "matchScore": 80}, {"jobId": "a1", "matchScore": 60}, {"jobId": "w1", "matchScore": 20},
                                           {"jobId": "b1", "matchScore": 90, "blockedBy": ["location"]}]}))
    run_start = "2026-11-23T10:00:00+00:00"
    pending = [(1, {"jobId": "w1", "firstSeen": "2026-11-01T00:00:00+00:00"}), (2, {"jobId": "o1", "firstSeen": "2026-11-01T00:00:00+00:00"}),
               (3, {"jobId": "a1", "firstSeen": "2026-11-01T00:00:00+00:00"}), (4, {"jobId": "b1", "firstSeen": "2026-11-01T00:00:00+00:00"}),
               (5, {"jobId": "t1", "firstSeen": "2026-11-01T00:00:00+00:00"}), (6, {"jobId": "n1", "firstSeen": "2026-11-23T10:30:00+00:00"})]
    args = type("A", (), {"max_usd": 1.0, "max_ads": 3, "scored": scored, "run_start": run_start, "counted_ids": None})()
    chosen, candidates, over, limits, skipped = enrich_jobs._plan_rescrape(args, pending)
    assert [j["jobId"] for _, j in chosen] == ["n1", "t1", "a1"], "this run's ad first, then Strong, Possible; the ads limit leaves the weak one waiting"
    assert (candidates, over, skipped) == (4, 1, 2), "an ad of another class and an already blocked ad are never read"


def test_an_ad_read_before_keeps_its_block_unsettled_and_is_read_again(monkeypatch, tmp_path):
    import role_class

    monkeypatch.setattr(role_class, "label", lambda rows, path=None: [r.update(roleClass="target") for r in rows])
    scored = tmp_path / "scored.json"
    scored.write_text(json.dumps({"jobs": [{"jobId": "loc", "matchScore": 90, "blockedBy": ["location"]},
                                           {"jobId": "spons", "matchScore": 90, "blockedBy": ["sponsorship"], "llmFacts": {"_fingerprint": "abc"}}]}))
    args = type("A", (), {"max_usd": 1.0, "max_ads": 9, "scored": scored, "run_start": None, "counted_ids": None})()
    chosen, candidates, over, limits, skipped = enrich_jobs._plan_rescrape(args, [(1, {"jobId": "loc"}), (2, {"jobId": "spons"})])
    assert [j["jobId"] for _, j in chosen] == ["spons"] and skipped == 1, "a block that needs no reading is settled; one owed to an earlier reading is checked again"


def test_the_three_steps_name_an_ad_by_the_same_job_id_in_the_ledger():
    """The distinct-ads count is read from the ledger: classification, reading and the engine must all record the row's jobId."""
    from match_engine import matcher

    row = {"jobId": "ad-1", "title": "PM", "description": "x"}
    assert matcher.posting_from_job(row)["id"] == "ad-1"
    assert classify_new.posting_for_prompt(row)[0]["id"] == "ad-1"
    assert 'ai_gate.context(feature="enrichment", job_id=job.get("jobId"))' in (ROOT / "python/job_scoring/enrich_jobs.py").read_text()


@pytest.mark.parametrize("profile, price_known", [(False, True), (True, False)])
def test_classification_that_cannot_send_still_reports_what_waits(monkeypatch, tmp_path, capsys, profile, price_known):
    import pipeline_lock
    import role_class
    from test_classify_new import PROFILE, row
    from test_classify_new_pipeline import FakeLock

    path = tmp_path / "profile.json"
    if profile:
        path.write_text(json.dumps(PROFILE))
    monkeypatch.setattr(pipeline_lock, "acquire", lambda: FakeLock())
    monkeypatch.setattr(role_class, "store_path", lambda: tmp_path / "fit3.json")
    monkeypatch.setattr(classify_new, "scoring_rows", lambda *a: [row("n1"), row("n2", description="a different ad text two")])
    budget = {"dailyLimit": 1, "monthlyLimit": 1, "dailySpent": 0, "monthlySpent": 0}
    monkeypatch.setattr(classify_new, "estimate", lambda todo, *a: {"send": [], "privacyRefused": [], "beyondAdLimit": 0, "provider": "p", "model": "m",
                                                                  "priceKnown": price_known, "inputOnlyUsd": None, "worstCaseUsd": None, "maxUsd": 1, "budget": budget})
    assert classify_new.main(["--profile", str(path), "--scored", str(tmp_path / "s.json"), "--confirm", "--rescrape", "--max-usd", "1", "--max-ads", "5"]) == 0
    summary = json.loads(next(l for l in reversed(capsys.readouterr().out.splitlines()) if l.startswith("{")))
    assert summary["step"] == "classification" and summary["stopped"] == "not_sent" and summary["waiting"] == 2


def test_an_unset_limit_reads_nothing_but_counts_what_waits(monkeypatch, tmp_path):
    import role_class

    monkeypatch.setattr(role_class, "label", lambda rows, path=None: [r.update(roleClass="target") for r in rows])
    args = type("A", (), {"max_usd": None, "max_ads": None, "scored": tmp_path / "none.json", "run_start": None, "counted_ids": None})()
    chosen, candidates, over, limits, _ = enrich_jobs._plan_rescrape(args, [(1, {"jobId": "x"}), (2, {"jobId": "y"})])
    assert chosen == [] and candidates == 2 and limits.stop == "unset"


# --- engine fill: off unless Settings allow it, as many ads as fit, never a refusal of everything --------------------------------------------------
class FakeLock:
    def release(self):
        pass


def drive_engine(monkeypatch, capsys, *, order, flags, run_result=None, cost=0.5):
    import engine_missing
    import pipeline_lock

    engine = type("E", (), {"plan_order": order})()
    monkeypatch.setattr(pipeline_lock, "acquire", lambda: FakeLock())
    monkeypatch.setattr(engine_missing, "build", lambda *a, **k: (engine, [], set(order), {}, {"provider": "p", "model": "m"}))
    budget = {"dailyLimit": 1, "monthlyLimit": 1, "dailySpent": 0, "monthlySpent": 0}
    monkeypatch.setattr(engine_missing, "estimate", lambda eng, jobs, send, profile, sel: {"toAsk": len(send), "costUsd": cost, "price": {}, "budget": budget,
                                                                                         "excluded": {}, "leaks": [], "ownerAds": []})
    monkeypatch.setattr(engine_missing, "describe", lambda *a: [])
    calls = []
    monkeypatch.setattr(engine_missing, "run", lambda *a, **k: calls.append(a[2]["toAsk"]) or run_result)
    code = engine_missing.main(["--rescrape", "--confirm", "--run-start", "2026-11-23T10:00:00+00:00", *flags])
    out = capsys.readouterr().out
    return code, json.loads(next(l for l in reversed(out.splitlines()) if l.startswith("{"))), calls


def test_engine_fill_is_skipped_unless_settings_allow_it(monkeypatch, capsys):
    code, summary, calls = drive_engine(monkeypatch, capsys, order=["a", "b"], flags=["--max-usd", "1", "--max-ads", "10"])
    assert code == 0 and calls == [] and summary["stopped"] == "engine_not_allowed" and summary["waiting"] == 2


def test_engine_fill_asks_as_many_as_fit_and_counts_the_rest_as_waiting(monkeypatch, capsys):
    ai_gate.save_settings({"allowEngineFill": True}, confirm=True)
    result = {"stopped": "the next call could pass the $0.10 cap", "newCalls": 2, "failed": 0, "refused": 1, "modelCalls": 2, "worstCaseUsd": 0.09}
    code, summary, calls = drive_engine(monkeypatch, capsys, order=["a", "b", "c", "d"], flags=["--max-usd", "0.1", "--max-ads", "3"], run_result=result, cost=0.5)
    assert code == 0, "a limit stop is exit 0: the run goes on to scoring"
    assert calls == [3], "the estimate is over the remainder, yet the ads that fit are still asked about (no refusal of everything)"
    assert summary["stopped"] == "run_usd" and summary["filled"] == 2 and summary["waiting"] == 2, "1 over the ads limit + 1 refused after the stop"


def test_engine_fill_with_the_budget_used_up_sends_nothing(monkeypatch, capsys):
    ai_gate.save_settings({"allowEngineFill": True}, confirm=True)
    code, summary, calls = drive_engine(monkeypatch, capsys, order=["a", "b"], flags=["--max-usd", "0", "--max-ads", "5"])
    assert calls == [] and summary["stopped"] == "run_usd" and summary["waiting"] == 2
