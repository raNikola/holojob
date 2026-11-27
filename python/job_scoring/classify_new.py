#!/usr/bin/env python3
"""Fit 3 role classification of NEW ads: the ads that have stored text and no entry at all in data/cache/fit3.json.

    .venv/bin/python python/job_scoring/classify_new.py                              # estimate only: counts, tokens, USD; sends nothing
    .venv/bin/python python/job_scoring/classify_new.py --confirm                    # the paid run, limited by Settings (runLimitUsd, runLimitAds)
    .venv/bin/python python/job_scoring/classify_new.py --max-usd 0.05 --max-ads 20 --confirm   # explicit flags win over Settings

Why: scoring 1.7 treats a Fit 3 role class "target" as on-track, and that class exists only for an ad classified in a paid run. A new ad has no class,
reads "not available" and falls back to the old track test. This step gives it a class BEFORE scoring (run it after discovery / import, then Re-score).

Which ads (the scoring set: the job list, hand-entered jobs, registered kept ads): open, not "not found by this run", text present, and NO entry in
fit3.json under the production prompt (candidate i1). An ad that has an entry whose role did not anchor is never called again: it is only counted
("anchoring failed"). Plain Re-score never calls a model and stays free. The full pipeline and Re-scrape run this file WITH --confirm (package 14, owner
decision 2026-11-23), after discovery / enrichment and before scoring, so the same run scores the new ads with their class. No limit is in code: an omitted
--max-usd / --max-ads is read from Settings (runLimitUsd, runLimitAds); if either is not set, nothing is sent and the output says "run limit not set in Settings".
Re-scrape passes the remainder of its one shared run budget (run_budget.py) and processes this run's ads first, then the backlog, strongest first.
A standalone run is a manual AI task; inside the pipeline the trigger the pipeline set is kept (a pipeline step is an automatic task, so the gate
refuses it while automation is off: that stop is counted like any other).

Limits (stop points, never a silent wait): --max-usd (per-call worst case counted against it) and --max-ads. When one is hit,
or the AI gate refuses, or 3 calls in a row fail, classifying stops; the ads left stay "not available" and the run record and the console say how many.
A provider failure never fails the run (exit 0): the ad stays without an entry and is retried next time.

What is sent per ad: the ad's title and description (e-mail addresses and phone numbers in the ad text masked, redact.mask_ad_contacts) and the closed
lists (role names, competency ids and definitions). NO candidate data, no notes, links or source URL. An ad whose raw text carries the owner's own
identifier is refused, and every outgoing prompt is scanned for the owner's identifiers (fail closed). The reply is stored raw under the classification key
(ad quotes only); code anchors it on every read. Existing entries are never changed.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for sub in ("cv_analysis", "llm", "job_scoring", "job_discovery"):
    sys.path.insert(0, str(ROOT / "python" / sub))
sys.path.append(str(ROOT / "python"))

import ai_gate  # noqa: E402
import ai_selection  # noqa: E402
import enrich_jobs  # noqa: E402
import job_history  # noqa: E402
import kept_ads  # noqa: E402
import manual_jobs  # noqa: E402
import pipeline_lock  # noqa: E402
import role_class  # noqa: E402
import run_budget  # noqa: E402
import row_state  # noqa: E402
from atomic_write import write_text_atomic  # noqa: E402
from calibration.prelabel import owner_in_text, owner_leaks  # noqa: E402
from llm_client import GuardrailRefused, LlmUnavailable, complete_json, preflight, service_tier_for  # noqa: E402
from match_engine import fit3  # noqa: E402
from redact import mask_ad_contacts  # noqa: E402

JOBS_PATH = ROOT / "data" / "jobs" / "discovered_jobs.json"
PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
FEATURE = "fit3-classify"
SCORED_PATH = ROOT / "data" / "jobs" / "scored_jobs.json"  # read for the order of the work only
CONSECUTIVE_FAILURES_STOP = 3  # the same systemic-failure stop CareerPulse (app/main.py) and JobOps (score-jobs.ts) use
UPPER_CHARS_PER_TOKEN = 3.0
KEEP_BACKUPS = 3
FILE_MODE = 0o600


# --- which ads --------------------------------------------------------------------------------------------------------------------------------------
def scoring_rows(jobs_path: Path, manual_path: Path, kept_path: Path) -> list[dict]:
    """The rows a scoring run scores, assembled as run_scoring does (list, hand-entered jobs, registered kept ads); read only."""
    discovered = json.loads(jobs_path.read_text(encoding="utf-8")) if jobs_path.exists() else {"jobs": []}
    jobs = discovered.get("jobs") if isinstance(discovered, dict) else discovered
    jobs = manual_jobs.with_manual(list(jobs or []), manual_jobs.load(manual_path))
    return kept_ads.with_kept(jobs, job_history.ledger_path(jobs_path), kept_path)


def read_store(path: Path) -> tuple[dict, dict]:
    """(whole document, its entries). A missing file is empty; an unreadable one raises so that nothing is ever written over it."""
    if not path.exists():
        return {"version": 1, "entries": {}}, {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("entries") or {}, dict):
        raise ValueError("fit3.json has an unknown shape")
    doc.setdefault("entries", {})
    return doc, doc["entries"]


def plan(rows: list[dict], entries: dict, roles: dict, comps: list[dict]) -> dict:
    """Group the scoring rows. Call inside fit3.production_candidate(): the key carries the prompt version.

    todo: [(key, row)] one per key, no entry at all. anchoringFailed: ids that have an entry but no anchored class (never called again).
    Not asked about: a closed ad, a row this run did not find (no model call for those, as everywhere), an ad with no text."""
    out = {"todo": [], "anchoringFailed": [], "noText": 0, "skipped": 0, "classed": 0}
    seen: set[str] = set()
    for row in rows:
        if row.get("isClosed") or row_state.not_found(row):
            out["skipped"] += 1
            continue
        text = row.get("description") or ""
        if not text.strip():
            out["noText"] += 1
            continue
        key = fit3.classification_key(row, roles, comps)
        entry = entries.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("reply"), dict):
            cls = fit3.anchor(entry["reply"], text, roles, comps, row.get("title") or "")["role"].get("class")
            if cls:
                out["classed"] += 1
            else:
                out["anchoringFailed"].append(str(row.get("jobId")))
        elif key not in seen:
            seen.add(key)
            out["todo"].append((key, row))
    return out


def posting_for_prompt(row: dict) -> tuple[dict, dict]:
    """Only what the prompt may carry: id, title and the ad text with third-party contacts masked. Never a note, link, source URL or company."""
    text, masked = mask_ad_contacts(row.get("description") or "")
    return {"id": str(row.get("jobId") or ""), "title": row.get("title") or "", "description": text}, masked


# --- estimate -----------------------------------------------------------------------------------------------------------------------------------------
def estimate(todo: list[tuple[str, dict]], profile: dict, roles: dict, comps: list[dict], max_ads: int, max_usd: float) -> dict:
    """Builds the prompts (nothing is sent), scans them, prices them. Returns counts, the ads that would go, and the budget lines."""
    selection = ai_selection.read()["selection"] or {}
    name, model = selection.get("provider"), selection.get("model")
    price = ai_gate.classify(name, model, selection.get("baseUrl") or None, tier=service_tier_for(name)) if name and model else {"priceKnown": False}
    refused, send, chars = [], [], []
    for key, row in todo:
        posting, _ = posting_for_prompt(row)
        prompt = fit3.build_prompt(posting, roles, comps)
        # The owner's own identifier in the raw text is never "masked away": the ad is refused. The scan then runs on the masked prompt.
        if owner_in_text(f"{row.get('title') or ''}\n{row.get('description') or ''}", profile) or owner_leaks(prompt, profile):
            refused.append(str(row.get("jobId")))
            continue
        send.append((key, row))
        chars.append(len(prompt))
    beyond = max(0, len(send) - max_ads)
    send, chars = send[:max_ads], chars[:max_ads]
    cost = worst = None
    if price.get("priceKnown"):
        out_tokens = int(enrich_jobs.reasoning_options(model).get("max_completion_tokens") or selection.get("maxTokens") or ai_selection.DEFAULTS["maxTokens"])
        cost = round(sum(chars) / 4 * price["inputPerMTok"] / 1e6, 4)  # input-only floor
        worst = round((sum(chars) / UPPER_CHARS_PER_TOKEN * price["inputPerMTok"] + len(chars) * out_tokens * price["outputPerMTok"]) / 1e6, 4)
    settings = ai_gate.load_settings()
    totals = ai_gate.totals(None, settings)
    return {"send": send, "privacyRefused": refused, "beyondAdLimit": beyond, "provider": name, "model": model, "priceKnown": bool(price.get("priceKnown")),
            "inputOnlyUsd": cost, "worstCaseUsd": worst, "maxUsd": max_usd,
            "budget": {"dailyLimit": settings.get("dailyLimit"), "monthlyLimit": settings.get("monthlyLimit"),
                       "dailySpent": totals["today"]["cost"], "monthlySpent": totals["thisMonth"]["cost"]}}


def describe(groups: dict, est: dict | None, max_ads: int) -> list[str]:
    lines = [f"ads with text and no Fit 3 entry (would be classified): {len(groups['todo'])}",
             f"ads whose entry exists but whose role did not anchor (not called again): {len(groups['anchoringFailed'])}",
             f"already classified: {groups['classed']}; no text: {groups['noText']}; closed or not found by the last run (no model call): {groups['skipped']}"]
    if est is None:
        return lines
    lines.append(f"model: {est['provider']}/{est['model']}" if est["provider"] else "model: none selected")
    if est["privacyRefused"]:
        lines.append(f"privacy scan: {len(est['privacyRefused'])} ads hit it and are NOT sent (ids: {', '.join(est['privacyRefused'])})")
    if est["beyondAdLimit"]:
        lines.append(f"over the {max_ads}-ad limit, left for the next run: {est['beyondAdLimit']}")
    if not est["priceKnown"]:
        lines.append("estimated cost: unknown (no price for this model)")
    else:
        lines.append(f"estimated cost: input-only floor ${est['inputOnlyUsd']:.4f}, worst case ${est['worstCaseUsd']:.4f} for {len(est['send'])} calls; cap ${est['maxUsd']:.2f}")
    b = est["budget"]
    lines.append(f"budget: today {b['dailySpent']:.4f} of {b['dailyLimit']}; this month {b['monthlySpent']:.4f} of {b['monthlyLimit']}")
    return lines


# --- the paid run ----------------------------------------------------------------------------------------------------------------------------------
class Guard(enrich_jobs.SpendGuard):
    """SpendGuard counts the `enrichment` feature; this run's calls are `fit3-classify`."""

    def spent(self) -> float:
        rows = ai_gate.read_ledger()
        started = {r.get("id") for r in rows if r.get("type") == "call" and r.get("feature") == FEATURE and r.get("decision") == "allowed"
                   and datetime.fromisoformat(r["ts"]) >= self.started_at}
        return sum(float(r.get("cost") or 0) for r in rows if r.get("type") == "result" and r.get("id") in started)


def run(send: list[tuple[str, dict]], profile: dict, roles: dict, comps: list[dict], guard: Guard, provider, model, *, complete=complete_json) -> dict:
    """One gated call per ad, in order. Returns {"entries": {key: entry}, "failed": {...}, "stopped": reason | None, "left": n, "calls": n}."""
    entries, failed, calls, consecutive, stopped = {}, {}, 0, 0, None
    for index, (key, row) in enumerate(send):
        posting, _ = posting_for_prompt(row)
        # Masking would hide the owner's own phone or e-mail from the scan below: the raw text is checked here too, and such an ad is not sent.
        if owner_in_text(f"{row.get('title') or ''}\n{row.get('description') or ''}", profile):
            failed["privacyRefused"] = failed.get("privacyRefused", 0) + 1
            continue

        def gated(prompt, schema=None, model=None, provider=None, _row=row):
            if owner_leaks(prompt, profile):  # last check on the very text that leaves
                raise GuardrailRefused("privacy scan hit on an outgoing request")
            worst = guard.reserve(prompt)
            try:
                return complete(prompt, schema=schema, model=model, provider=provider)
            finally:
                guard.release(worst)

        try:
            calls += 1
            reply = fit3.classify(posting, confirmed=True, provider=provider, model=model, complete=gated, roles=roles, comps=comps)
        except GuardrailRefused as exc:
            calls -= 1
            if "privacy" in str(exc):
                failed["privacyRefused"] = failed.get("privacyRefused", 0) + 1
                continue
            stopped = f"stopped: {exc}"  # the cap, or a daily / monthly limit of the AI gate: a stop point, nothing waits
            return {"entries": entries, "failed": failed, "stopped": stopped, "left": len(send) - index, "calls": calls}
        except Exception as exc:  # a provider or reply failure is counted; the ad stays unclassified and is retried next time
            name = type(exc).__name__
            failed[name] = failed.get(name, 0) + 1
            consecutive += 1
            if consecutive >= CONSECUTIVE_FAILURES_STOP:
                stopped = f"stopped: {consecutive} calls in a row failed"
                return {"entries": entries, "failed": failed, "stopped": stopped, "left": len(send) - index - 1, "calls": calls}
            continue
        consecutive = 0
        entries[key] = {"reply": reply, "answers": None}
    return {"entries": entries, "failed": failed, "stopped": stopped, "left": 0, "calls": calls}


def merge_into_store(path: Path, new_entries: dict) -> int:
    """Add entries to fit3.json: atomic, mode 600, existing entries and top-level keys untouched. A copy of the file is kept first (the last few)."""
    doc, entries = read_store(path)
    added = {k: v for k, v in new_entries.items() if k not in entries}
    if not added:
        return 0
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.bak-pre-classify-{stamp}")
        write_text_atomic(backup, path.read_text(encoding="utf-8"), FILE_MODE)
        for old in sorted(path.parent.glob(f"{path.name}.bak-pre-classify-*"))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
    doc["entries"] = {**entries, **added}
    doc.setdefault("promptVersion", fit3.PROMPT_VERSION)
    doc["layoutVersion"] = fit3.LAYOUT_VERSION  # informational: not part of the classification key
    write_text_atomic(path, json.dumps(doc, ensure_ascii=False), FILE_MODE)
    return len(added)


def write_run_record(summary: dict) -> None:
    """One Activity record (the run history reads it through an allow-list). A failure to write it never fails the run."""
    try:
        import run_log
        record = run_log.new_record(secrets.token_hex(6), "manual")
        record["orchestrator"] = "classify"
        counts = {**summary, "failedKinds": None}
        record["classification"] = {k: v for k, v in counts.items() if k != "failedKinds"}
        record["status"] = ("failed" if counts["classified"] == 0 and counts["failed"] else "partial" if counts["stopped"] or counts["failed"] or counts["left"] else "ok")
        record["finishedAt"] = run_log.now_iso()
        if counts["stopped"]:
            run_log.add_issue(record, "warning", f"Classification stopped ({counts['stopped']}); {counts['left']} ads left without a class.")
        run_log.save(record)
    except Exception as exc:  # noqa: BLE001
        print(f"run record not written: {type(exc).__name__}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jobs", type=Path, default=JOBS_PATH)
    ap.add_argument("--manual", type=Path, default=manual_jobs.MANUAL_PATH)
    ap.add_argument("--kept", type=Path, default=kept_ads.KEPT_PATH)
    ap.add_argument("--profile", type=Path, default=PROFILE_PATH)
    ap.add_argument("--scored", type=Path, default=SCORED_PATH, help="the last scored list, read only to order the work (strongest first)")
    ap.add_argument("--max-usd", type=float, default=None, help="the run's hard stop in US dollars (omitted: Settings runLimitUsd; 0 = used up)")
    ap.add_argument("--max-ads", type=int, default=None, help="at most this many distinct ads (omitted: Settings runLimitAds; 0 = used up)")
    ap.add_argument("--confirm", action="store_true", help="make the paid calls (without it: estimate only)")
    ap.add_argument("--rescrape", action="store_true", help="a step of Re-scrape: it writes the run's one record, this file writes none")
    run_budget.add_args(ap)
    args = ap.parse_args(argv)
    if (args.max_usd is not None and args.max_usd < 0) or (args.max_ads is not None and args.max_ads < 0):
        print("--max-usd and --max-ads must not be negative", file=sys.stderr)
        return 2
    try:
        return _main(args)
    except Exception as exc:  # noqa: BLE001  a step in a pipeline run must never fail it; the cause is named, not hidden
        print(f"classification: skipped, {type(exc).__name__}: {str(exc)[:160]}")
        print(run_budget.summary_line("classification", candidates=0, classified=0, failed=0, privacyRefused=0, left=0, waiting=None, stopped=run_budget.STOP_NOT_SENT,
                                      anchoringFailed=0, spentUsd=0.0))
        return 0


def _finish(args, summary: dict) -> int:
    """The one summary line (the orchestrator reads it) and, outside Re-scrape, the run's own Activity record."""
    if not args.rescrape:
        write_run_record(summary)
    print(run_budget.summary_line("classification", **{k: v for k, v in summary.items() if k != "failedKinds"}))
    return 0


def _empty_summary(candidates: int, left: int, stopped: str | None, anchoring: int, limits: run_budget.Limits) -> dict:
    return {"candidates": candidates, "classified": 0, "failed": 0, "failedKinds": {}, "privacyRefused": 0, "left": left, "waiting": left,
            "stopped": stopped, "anchoringFailed": anchoring, "spentUsd": 0.0, "capUsd": limits.usd, "maxAds": limits.ads}


def _main(args) -> int:
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        store_path = role_class.store_path()
        _, entries = read_store(store_path)
        with fit3.production_candidate():
            roles, comps = fit3.load_roles(), fit3.closed_competencies("product")
            groups = plan(scoring_rows(args.jobs, args.manual, args.kept), entries, roles, comps)
            limits = run_budget.resolve_limits(args.max_usd, args.max_ads)
            prior = run_budget.prior_view(args.scored)
            if args.group:  # one priority pass of Re-scrape: only its ads are candidates, and only they are counted as waiting
                groups["todo"] = [item for item in groups["todo"] if run_budget.in_group(item[1], args.group, prior, args.run_start)]
            if not groups["todo"]:
                print("\n".join(describe(groups, None, limits.ads)))
                print("classification: nothing to classify")
                print(run_budget.summary_line("classification", candidates=0, classified=0, failed=0, privacyRefused=0, left=0, waiting=0, stopped=None,
                                              anchoringFailed=len(groups["anchoringFailed"]), spentUsd=0.0))
                return 0
            # This run's ads first, then the backlog; strongest first inside each (a stable sort keeps the file order among equals).
            groups["todo"].sort(key=lambda item: run_budget.order_key(item[1], prior, args.run_start))
            profile = json.loads(args.profile.read_text(encoding="utf-8")) if args.profile.exists() else None
            if not profile:
                print("\n".join(describe(groups, None, limits.ads)))
                print("classification: skipped, no profile on disk, so the privacy scan cannot run; nothing was sent")
                return _finish(args, _empty_summary(len(groups["todo"]), len(groups["todo"]), run_budget.STOP_NOT_SENT, len(groups["anchoringFailed"]), limits))
            if limits.stop:
                print("\n".join(describe(groups, None, limits.ads)))
                print("classification: run limit not set in Settings; nothing was sent" if limits.stop == run_budget.STOP_UNSET
                      else f"classification: stopped, {limits.stop}; nothing was sent")
                return _finish(args, _empty_summary(len(groups["todo"]), len(groups["todo"]), limits.stop, len(groups["anchoringFailed"]), limits))
            ids = [str(row.get("jobId")) for _, row in groups["todo"]]
            selected, over_limit = run_budget.trim(ids, limits.ads, run_budget.read_counted(args.counted_ids))
            chosen = set(selected)
            todo = [item for item in groups["todo"] if str(item[1].get("jobId")) in chosen]
            est = estimate(todo, profile, roles, comps, max(1, len(todo)), limits.usd)
            print("\n".join(describe({**groups, "todo": todo}, est, limits.ads)))
            if over_limit:
                print(f"over the ads limit, left for the next run: {len(over_limit)}")
            if not args.confirm:
                print(f"nothing sent: {len(groups['todo'])} new ads wait for a class. Classify them: "
                      f".venv/bin/python python/job_scoring/classify_new.py --confirm   (limits from Settings; then Re-score)")
                return 0
            if not est["priceKnown"] or not est["send"]:
                print("classification: nothing sent" + ("" if est["priceKnown"] else " (no price for this model)"))
                # No price: every ad waits. Every ad refused by the privacy scan: they are never sent, so none waits for a limit.
                waiting = (len(groups["todo"]) if not est["priceKnown"] else len(over_limit))
                summary = _empty_summary(len(groups["todo"]), waiting, run_budget.STOP_NOT_SENT if not est["priceKnown"] else None, len(groups["anchoringFailed"]), limits)
                return _finish(args, {**summary, "privacyRefused": len(est["privacyRefused"])})
            os.environ.setdefault(ai_gate.TRIGGER_ENV, ai_gate.MANUAL)  # a standalone run is manual; a pipeline step keeps the trigger it was given
            base = enrich_jobs.make_guard(limits.usd, est["provider"], est["model"])
            guard = Guard(base.cap, base.price, base.max_output)
            with ai_gate.context(feature=FEATURE):
                decision = preflight(max(len(fit3.build_prompt(posting_for_prompt(r)[0], roles, comps)) for _, r in est["send"]), est["provider"], est["model"])
            if not decision.allowed:
                ai_gate.record_refused(decision, skipped=len(est["send"]))
                result = {"entries": {}, "failed": {}, "stopped": f"stopped: AI gate refused: {decision.reason}", "left": len(est["send"]), "calls": 0}
            else:
                result = run(est["send"], profile, roles, comps, guard, est["provider"], est["model"])
            added = merge_into_store(store_path, result["entries"])  # whatever was paid for is kept, also after a stop
            waiting = result["left"] + est["beyondAdLimit"] + len(over_limit)
            stopped = run_budget.stop_code(result["stopped"]) or (run_budget.STOP_RUN_ADS if over_limit else None)
            summary = {"candidates": len(groups["todo"]), "classified": added, "failed": sum(result["failed"].values()), "failedKinds": result["failed"],
                       "privacyRefused": len(est["privacyRefused"]), "left": waiting, "waiting": waiting,
                       "stopped": stopped, "anchoringFailed": len(groups["anchoringFailed"]), "spentUsd": round(guard.spent(), 4),
                       "capUsd": limits.usd, "maxAds": limits.ads}
            print("classes are in fit3.json; run Re-score to apply them" + (f"; {waiting} ads stay 'not available' ({stopped})" if waiting else ""))
            return _finish(args, summary)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
