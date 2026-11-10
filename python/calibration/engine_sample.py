#!/usr/bin/env python3
"""P1 Stage A, step 7: the shadow engine's evidence matcher on the review sample, into the calibration folder only.

    python python/calibration/engine_sample.py estimate    # builds every request, scans it, counts it; sends nothing
    python python/calibration/engine_sample.py run --yes   # PAID; needs the owner's approval; resumes; hard stop

It reads the ads from review-items.json (description redacted of third-party contacts, as in step 6) and their facts from
enrichment-facts.json, and calls the production matcher unchanged (`match_engine.matcher.match_posting`, same prompt, same
redaction of the evidence, same verifier). What is sent per call: the ad text, that ad's requirements (ref, text, kind,
importance) and the evidence index items (id, source, role, start, end, text), each redacted with the owner's name and
links. Never sent: gates (work authorization, locations, languages, salary), confirmed facts, the profile version, name,
contacts, links. The gates, language requirements settled from the profile, quote checks, scoring (`fit.score`) and the
cheap-gate exclusion run locally.

Every outgoing request is scanned for the owner's identifiers (calibration.prelabel.owner_leaks, fail closed): the
estimate scans all requests, a hit stops the run before any call, and each live call is scanned again. Results go to
engine-shadow.json in this folder, written after every ad. Nothing in the production cache, ledger, facts or scores is
read for state or written (the AI gate's own usage rows excepted: that is how it enforces the daily and monthly limits).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("cv_analysis", "llm", "job_scoring"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
import ai_gate  # noqa: E402
import ai_selection  # noqa: E402
from competency_mapping import load_remap  # noqa: E402
from confirmed_facts import load as load_confirmed_facts  # noqa: E402
from evidence_index import build_candidate  # noqa: E402
from job_fingerprint import job_fingerprint  # noqa: E402
from llm_client import GuardrailRefused, LlmUnavailable, complete_json, preflight, service_tier_for  # noqa: E402
from match_engine import matcher  # noqa: E402
from match_engine.constants import ENGINE_VERSION  # noqa: E402
from match_engine.fit import score  # noqa: E402
from match_engine.gates import cheap_gate_report, gate_results  # noqa: E402
from redact import identity_of  # noqa: E402
from calibration.enrich_sample import FACTS_NAME, sanitized  # noqa: E402
from calibration.prelabel import owner_leaks  # noqa: E402

STAGE_DIR = ROOT / "data" / "calibration" / "stage-a"
PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
RESULTS_NAME = "engine-shadow.json"
FEATURE = "evidence-matcher"
HARD_STOP_USD = 0.25  # the owner's cap for the step 7 batch; retries count against it
CHARS_PER_TOKEN = 3.0  # low on purpose: over-counts, so the input estimate is an upper bound
OUTPUT_PER_REQUIREMENT = 90  # reserved tokens per asked requirement (status, id, quote, strength) ...
OUTPUT_BASE = 600  # ... plus the gates object and reasoning headroom. An assumption, not a measurement.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Captured(LlmUnavailable):
    """Raised by the dry-run `complete` after it has kept the prompt: nothing is sent."""


class ResultStore:
    """engine-shadow.json: one entry per ad, written atomically after each, so a stopped run keeps what is paid for."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = {"version": 1, "engineVersion": ENGINE_VERSION, "promptVersion": matcher.PROMPT_VERSION, "ads": {}}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("ads"), dict):
                self.data = loaded

    def done(self, job_id: str, cache_key: str) -> bool:
        entry = self.data["ads"].get(job_id) or {}
        return entry.get("cacheKey") == cache_key and bool(entry.get("output"))

    def put(self, job_id: str, entry: dict) -> None:
        with self._lock:
            self.data["ads"][job_id] = entry
            self.data["updatedAt"] = _now()
            make_private_dirs(self.path.parent)
            write_text_atomic(self.path, json.dumps(self.data, indent=2, ensure_ascii=False), PRIVATE_FILE_MODE)


def alias_unsafe_ids(candidate: dict, profile: dict) -> tuple[dict, dict]:
    """(candidate, {alias: original id}). An evidence id is a hash; one that happens to hold a run of seven or more digits
    reads as a phone number to the privacy scan. The scan is not loosened: such an id is replaced, for this run only, by a
    neutral alias (ev-cal-N), consistently in the whole index. The aliases are stored with the results."""
    aliases, evidence = {}, []
    for item in candidate["evidence"]:
        if owner_leaks(str(item["id"]), profile):
            alias = f"ev-cal-{len(aliases) + 1}"
            aliases[alias] = item["id"]
            item = {**item, "id": alias}
        evidence.append(item)
    return {**candidate, "evidence": evidence}, aliases


def tokens_of(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def _locally_settled(posting: dict, candidate: dict) -> tuple[int, int]:
    """(requirements the model is asked about, requirements settled without it) by the matcher's own local rules."""
    reqs, _ = matcher.drop_unquoted(((posting.get("facts") or {}).get("requirements")) or [], posting.get("description") or "")
    facts = {f["competencyId"] for f in candidate.get("confirmedFacts") or []}
    local = sum(1 for r in reqs if r["id"] in facts or matcher.settle_language(r, candidate) is not None)
    return len(reqs) - local, local


MODE_PRODUCTION = "production_like"  # no confirmed cheap-gate fail: production would send it
MODE_DIAGNOSTIC = "diagnostic"  # production would skip it; asked anyway so gate quality and matcher quality are measured apart


def plan(out: Path, profile: dict, intelligence: dict, production_only: bool = False) -> dict:
    items = json.loads((out / "review-items.json").read_text(encoding="utf-8"))["items"]
    facts = json.loads((out / FACTS_NAME).read_text(encoding="utf-8"))["facts"] if (out / FACTS_NAME).exists() else {}
    candidate, id_aliases = alias_unsafe_ids(build_candidate(profile, intelligence, load_confirmed_facts()), profile)
    identity = identity_of(profile)
    remap = load_remap(out / "requirement-remap.json")
    store = ResultStore(out / RESULTS_NAME)
    selection = ai_selection.require()
    provider, model = selection["provider"], selection["model"]
    rows, skipped = {}, {"noFacts": 0, "noRequirements": 0, "gateFail": 0, "done": 0}
    gate_fails = {}
    for item in items:
        job = {**sanitized(item), "llmFacts": facts.get(item["jobId"])}
        if not job["llmFacts"]:
            skipped["noFacts"] += 1
            continue
        posting = matcher.posting_from_job(job, remap)
        reqs = posting["facts"].get("requirements")
        if not reqs:
            skipped["noRequirements"] += 1
            continue
        key = matcher.cache_key(job_fingerprint(posting), candidate["profileVersion"], None, reqs)
        if store.done(item["jobId"], key):
            skipped["done"] += 1
            continue
        failed, _ = cheap_gate_report(job, candidate)
        for gate in failed:
            gate_fails[gate] = gate_fails.get(gate, 0) + 1
        if failed and production_only:
            skipped["gateFail"] += 1
            continue
        captured = []

        def capture(prompt, schema=None, model=None, provider=None, _c=captured):
            _c.append(prompt)
            raise Captured("dry run")

        matcher.match_posting(posting, candidate, confirmed=True, provider=provider, model=model, complete=capture,
                              identity=identity)
        if not captured:
            skipped["noRequirements"] += 1  # every requirement was settled locally: nothing to ask
            continue
        asked, local = _locally_settled(posting, candidate)
        rows[item["jobId"]] = {"mode": MODE_DIAGNOSTIC if failed else MODE_PRODUCTION, "excludedBy": list(failed),
                               "job": job, "posting": posting, "prompt": captured[0], "key": key, "asked": asked, "local": local}
    leaks = {j: kinds for j, r in rows.items() if (kinds := owner_leaks(r["prompt"], profile))}
    price = ai_gate.classify(provider, model, selection.get("baseUrl") or None, tier=service_tier_for(provider))
    in_tokens = [tokens_of(len(r["prompt"])) for r in rows.values()]
    out_tokens = [OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * r["asked"] for r in rows.values()]
    cost = None
    if price.get("priceKnown") and rows:
        cost = round(sum(in_tokens) * price["inputPerMTok"] / 1e6 + sum(out_tokens) * price["outputPerMTok"] / 1e6, 4)
    settings = ai_gate.load_settings()
    t = ai_gate.totals(None, settings)
    return {
        "rows": rows, "skipped": skipped, "leaks": leaks, "idAliases": id_aliases, "gateFails": gate_fails, "candidate": candidate, "identity": identity, "store": store,
        "provider": provider, "model": model, "tier": price.get("tier"), "price": price, "inTokens": in_tokens,
        "outTokens": out_tokens, "costUsd": cost, "evidenceItems": len(candidate["evidence"]),
        "budget": {"dailyLimit": settings.get("dailyLimit"), "monthlyLimit": settings.get("monthlyLimit"),
                   "dailySpent": t["today"]["cost"], "monthlySpent": t["thisMonth"]["cost"],
                   "currency": settings.get("currency")},
    }


def describe(p: dict) -> list[str]:
    b, rows = p["budget"], p["rows"]
    asked = sum(r["asked"] for r in rows.values())
    local = sum(r["local"] for r in rows.values())
    sk = p["skipped"]
    lines = [
        f"calls to make: {len(rows)} (one per ad): {sum(1 for r in rows.values() if r['mode'] == MODE_PRODUCTION)} production_like, "
        f"{sum(1 for r in rows.values() if r['mode'] == MODE_DIAGNOSTIC)} diagnostic (production would skip them on a confirmed gate fail); not sent: {sk['gateFail']} confirmed cheap-gate fail, {sk['noFacts']} without facts, "
        f"{sk['noRequirements']} without requirements to ask, {sk['done']} already done",
        f"model: {p['provider']}/{p['model']}, tier {p['tier']}",
        "confirmed cheap-gate fails among the ads (an ad failing two counts in both): " + (
            ", ".join(f"{g} {n}" for g, n in sorted(p["gateFails"].items())) or "none"),
        f"per call: the redacted ad, its requirements, and all {p['evidenceItems']} evidence items (the engine's default sends the whole index); "
        f"{len(p['idAliases'])} evidence ids read as a phone number to the scan and are aliased for this run (the scan is unchanged)",
        f"requirements asked of the model: {asked}; settled locally with no model (confirmed facts, spoken languages): {local}",
    ]
    if rows:
        lines.append(f"input tokens: about {sum(p['inTokens'])} in total ({min(p['inTokens'])}-{max(p['inTokens'])} per call); "
                     f"UPPER BOUND at {CHARS_PER_TOKEN:g} characters per token")
        lines.append(f"output tokens: {sum(p['outTokens'])} reserved ({OUTPUT_BASE} + {OUTPUT_PER_REQUIREMENT} per asked requirement); an assumption, not a measurement")
    if p["costUsd"] is None:
        lines.append("estimated cost: unknown (no price for this model)" if rows else "estimated cost: $0 (nothing to ask)")
    else:
        lines.append(f"estimated cost: ${p['costUsd']:.4f} at ${p['price']['inputPerMTok']}/{p['price']['outputPerMTok']} per 1M input/output tokens, "
                     f"no cache discount; a reply the matcher must retry (malformed once) is a second call, so the worst case is twice that")
    lines.append(f"hard stop in the runner: ${HARD_STOP_USD:.2f}")
    lines.append(f"budget {b['currency']}: today {b['dailySpent']:.4f} of {b['dailyLimit']} (left {float(b['dailyLimit']) - b['dailySpent']:.4f}); "
                 f"this month {b['monthlySpent']:.4f} of {b['monthlyLimit']} (left {float(b['monthlyLimit']) - b['monthlySpent']:.4f})")
    lines.append(f"privacy scan: {len(rows) - len(p['leaks'])} of {len(rows)} requests pass" + (
        "" if not p["leaks"] else "; FAILED kinds: " + "; ".join(sorted({k for v in p['leaks'].values() for k in v}))))
    return lines


def run(out: Path, profile: dict, intelligence: dict, workers: int = 4, complete=complete_json,
        production_only: bool = False) -> dict:
    p = plan(out, profile, intelligence, production_only)
    if p["leaks"]:
        return {"stopped": "privacy scan found owner identifiers; nothing was sent", "asked": 0}
    if p["costUsd"] is None and p["rows"]:
        return {"stopped": "no price for this model; nothing was sent", "asked": 0}
    if p["costUsd"] is not None and p["costUsd"] > HARD_STOP_USD:
        return {"stopped": f"estimate ${p['costUsd']:.4f} is over the hard stop ${HARD_STOP_USD:.2f}; nothing was sent", "asked": 0}
    if not p["rows"]:
        return {"stopped": None, "asked": 0, "ok": 0, "failed": 0, "refused": 0}
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    with ai_gate.context(feature=FEATURE):
        decision = preflight(max(len(r["prompt"]) for r in p["rows"].values()), p["provider"], p["model"])
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=len(p["rows"]))
        return {"stopped": f"AI gate refused: {decision.reason}", "asked": 0}
    stop = threading.Event()
    counts = {"ok": 0, "failed": 0, "refused": 0}
    spent = {"calls": 0, "usd": 0.0, "reason": None}
    lock = threading.Lock()
    price = p["price"]

    def scanned(prompt, schema=None, model=None, provider=None):
        if owner_leaks(prompt, profile):  # again, on the exact text about to leave
            stop.set()
            spent["reason"] = "privacy scan hit on an outgoing request"
            raise GuardrailRefused("privacy scan hit on an outgoing request")
        # Every call, a matcher retry included, is counted at its worst-case cost before it is made.
        worst = tokens_of(len(prompt)) * price["inputPerMTok"] / 1e6 + (OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * 40) * price["outputPerMTok"] / 1e6
        with lock:
            if spent["usd"] + worst > HARD_STOP_USD:
                stop.set()
                spent["reason"] = f"the next call could pass the ${HARD_STOP_USD:.2f} cap"
                raise GuardrailRefused(spent["reason"])
            spent["usd"] += worst
            spent["calls"] += 1
        return complete(prompt, schema=schema, model=model, provider=provider)

    def one(job_id: str) -> str:
        if stop.is_set():
            return "refused"
        row = p["rows"][job_id]
        try:
            outcome = matcher.match_posting(row["posting"], p["candidate"], confirmed=True, provider=p["provider"],
                                            model=p["model"], complete=scanned, identity=p["identity"])
        except GuardrailRefused:
            stop.set()
            return "refused"
        if outcome.output is None:
            return "failed"
        output = outcome.output
        gates = gate_results(row["job"], p["candidate"], output["gates"], output["requirements"])
        p["store"].put(job_id, {"mode": row["mode"], "excludedBy": row["excludedBy"],
                                "cacheKey": row["key"], "at": _now(), "output": output, "gates": gates,
                                "evidenceIdAliases": p["idAliases"],
                                **score(output["requirements"], gates)})
        return "ok"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for future in as_completed([pool.submit(one, j) for j in p["rows"]]):
            counts[future.result()] += 1
    return {"stopped": spent["reason"], "asked": len(p["rows"]), **counts, "modelCalls": spent["calls"],
            "retries": max(0, spent["calls"] - counts["ok"] - counts["failed"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("estimate", "run"))
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    ap.add_argument("--yes", action="store_true", help="make the paid calls (run only)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--production-only", action="store_true", help="leave out the ads production would skip on a confirmed gate fail")
    args = ap.parse_args(argv)
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    intelligence = json.loads(INTELLIGENCE_PATH.read_text(encoding="utf-8"))
    if args.command == "estimate" or not args.yes:
        print("\n".join(describe(plan(args.out, profile, intelligence, args.production_only))))
        if args.command == "run":
            print("nothing sent: add --yes after the estimate is approved")
        return 0
    result = run(args.out, profile, intelligence, args.workers, production_only=args.production_only)
    print(json.dumps(result))
    return 1 if result.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
