#!/usr/bin/env python3
"""P1 Stage A, step 6: read the review sample with the existing enrichment prompt, into the calibration folder only.

    python python/calibration/enrich_sample.py estimate    # calls nothing, writes nothing
    python python/calibration/enrich_sample.py run --yes   # paid; resumes; refused above the hard stop

It reuses `enrich_jobs.build_prompt` and `enrich_jobs.extract` unchanged (PROMPT_VERSION stays as it is), so the facts are
exactly what production enrichment would produce. Differences from production: the ads come from review-items.json, the
facts go to enrichment-facts.json in this folder, the competency aliases and remap table live in this folder too, and no
production file is read for state or written. The model never sees the candidate; every prompt is scanned for the owner's
identifiers first and one hit stops the run before any call (fail closed). The AI gate still writes its own usage row
(that is what enforces the daily and monthly limits); nothing else touches the production ledger.
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
import competency_mapping  # noqa: E402
import enrich_jobs  # noqa: E402
from job_fingerprint import PROMPT_VERSION, job_fingerprint  # noqa: E402
from llm_client import GuardrailRefused, LlmRefused, LlmUnavailable, preflight, service_tier_for  # noqa: E402
from calibration.prelabel import owner_leaks  # noqa: E402
from redact import redact_cv_text  # noqa: E402

STAGE_DIR = ROOT / "data" / "calibration" / "stage-a"
PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
FACTS_NAME = "enrichment-facts.json"
HARD_STOP_USD = 0.50
CHARS_PER_TOKEN = 3.0  # deliberately low: over-counts tokens, so the estimate is an upper bound
OUTPUT_TOKENS = 1000  # reserved per call; a measured enrichment call used 869


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FactsStore:
    """enrichment-facts.json: written atomically after every finished ad, so a stopped run loses nothing already paid."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = {"version": 1, "promptVersion": PROMPT_VERSION, "facts": {}}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("facts"), dict):
                self.data = loaded

    def valid(self, ad: dict) -> bool:
        """Facts that belong to this exact ad under the current prompt version and carry at least one requirement."""
        facts = self.data["facts"].get(ad["jobId"]) or {}
        return facts.get("_fingerprint") == job_fingerprint(sanitized(ad)) and bool(facts.get("requirements"))

    def put(self, job_id: str, facts: dict) -> None:
        with self._lock:
            self.data["facts"][job_id] = facts
            self.data["updatedAt"] = _now()
            make_private_dirs(self.path.parent)
            write_text_atomic(self.path, json.dumps(self.data, indent=2, ensure_ascii=False), PRIVATE_FILE_MODE)


def sanitized(ad: dict) -> dict:
    """The ad as it is sent: third-party phones, e-mails and links in the description replaced by placeholders (the same
    generic redaction the pre-label uses). Facts are stored and checked against this text, so the stored fingerprint is its."""
    description = redact_cv_text(str(ad.get("description") or ""), "", [])[0]
    return {**ad, "description": description}


def role_family(intelligence: dict) -> str | None:
    return intelligence.get("roleFamily") or None


def make_mapper(out: Path, family: str | None):
    """The role family's competency list with learned aliases and remap kept in this folder, starting empty."""
    base = competency_mapping.load_mapper(family)
    if base is None:
        return None
    return competency_mapping.Mapper(base.comps, out / "competency-aliases.json", out / "requirement-remap.json")


def tokens_of(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def plan(out: Path, profile: dict, intelligence: dict) -> dict:
    items = json.loads((out / "review-items.json").read_text(encoding="utf-8"))["items"]
    store = FactsStore(out / FACTS_NAME)
    mapper = make_mapper(out, role_family(intelligence))
    prompts = {i["jobId"]: enrich_jobs.build_prompt(sanitized(i), None, mapper) for i in items}
    leaks = {j: kinds for j, text in prompts.items() if (kinds := owner_leaks(text, profile))}
    pending = [i["jobId"] for i in items if not store.valid(i)]
    selection = ai_selection.require()
    provider, model = selection["provider"], selection["model"]
    price = ai_gate.classify(provider, model, selection.get("baseUrl") or None, tier=service_tier_for(provider))
    per_ad = [tokens_of(len(prompts[j])) for j in pending]
    cost = None
    if price.get("priceKnown") and per_ad:
        cost = round(sum(per_ad) * price["inputPerMTok"] / 1e6 + len(per_ad) * OUTPUT_TOKENS * price["outputPerMTok"] / 1e6, 4)
    settings = ai_gate.load_settings()
    t = ai_gate.totals(None, settings)
    return {
        "items": items, "prompts": prompts, "leaks": leaks, "pending": pending, "provider": provider, "model": model,
        "tier": price.get("tier"), "price": price, "perAdTokens": per_ad, "costUsd": cost, "store": store, "mapper": mapper,
        "budget": {
            "dailyLimit": settings.get("dailyLimit"), "monthlyLimit": settings.get("monthlyLimit"),
            "dailySpent": t["today"]["cost"], "monthlySpent": t["thisMonth"]["cost"], "currency": settings.get("currency"),
        },
    }


def describe(p: dict) -> list[str]:
    per_ad, b = p["perAdTokens"], p["budget"]
    lines = [
        f"ads in the sample: {len(p['items'])}; already with valid facts: {len(p['items']) - len(p['pending'])}; calls to make: {len(p['pending'])}",
        f"model: {p['provider']}/{p['model']}, tier {p['tier']}; competency list in the prompt: {'yes' if p['mapper'] else 'no'}",
    ]
    if per_ad:
        lines.append(f"input tokens: about {sum(per_ad)} in total ({min(per_ad)}-{max(per_ad)} per call, upper bound at "
                     f"{CHARS_PER_TOKEN:g} characters per token); output reserved: {OUTPUT_TOKENS} per call, {OUTPUT_TOKENS * len(per_ad)} in total")
    if p["costUsd"] is None:
        lines.append("estimated cost: unknown (no price for this model)" if p["pending"] else "estimated cost: $0 (nothing to ask)")
    else:
        lines.append(f"estimated cost: ${p['costUsd']:.4f} at ${p['price']['inputPerMTok']}/{p['price']['outputPerMTok']} per 1M input/output tokens, no cache discount")
    lines.append(f"hard stop: ${HARD_STOP_USD:.2f}")
    lines.append(f"budget {b['currency']}: today {b['dailySpent']:.4f} of {b['dailyLimit']} (left {float(b['dailyLimit']) - b['dailySpent']:.4f}); "
                 f"this month {b['monthlySpent']:.4f} of {b['monthlyLimit']} (left {float(b['monthlyLimit']) - b['monthlySpent']:.4f})")
    lines.append("privacy scan: " + ("CLEAN, 0 prompts with an owner identifier" if not p["leaks"] else
                                     f"FAILED, {len(p['leaks'])} prompts: " + "; ".join(sorted({k for v in p['leaks'].values() for k in v}))))
    return lines


def run(out: Path, profile: dict, intelligence: dict, workers: int = 4, extract=enrich_jobs.extract) -> dict:
    p = plan(out, profile, intelligence)
    if p["leaks"]:
        return {"stopped": "privacy scan found owner identifiers; nothing was sent", "asked": 0}
    if p["costUsd"] is None and p["pending"]:
        return {"stopped": "no price for this model; nothing was sent", "asked": 0}
    if p["costUsd"] is not None and p["costUsd"] > HARD_STOP_USD:
        return {"stopped": f"estimate ${p['costUsd']:.4f} is over the hard stop ${HARD_STOP_USD:.2f}; nothing was sent", "asked": 0}
    if not p["pending"]:
        return {"stopped": None, "asked": 0, "ok": 0, "failed": 0, "refused": 0}
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    with ai_gate.context(feature="enrichment"):
        decision = preflight(max(len(p["prompts"][j]) for j in p["pending"]), p["provider"], p["model"])
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=len(p["pending"]))
        return {"stopped": f"AI gate refused: {decision.reason}", "asked": 0}
    stop = threading.Event()
    by_id = {i["jobId"]: i for i in p["items"]}
    counts = {"ok": 0, "failed": 0, "refused": 0}

    def one(job_id: str) -> str:
        if stop.is_set():
            return "refused"
        try:
            facts = extract(sanitized(by_id[job_id]), p["model"], p["provider"], None, mapper=p["mapper"])
        except GuardrailRefused:
            stop.set()
            return "refused"
        except (LlmUnavailable, LlmRefused):
            return "failed"
        p["store"].put(job_id, facts)
        return "ok"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for future in as_completed([pool.submit(one, j) for j in p["pending"]]):
            counts[future.result()] += 1
    if p["mapper"]:
        p["mapper"].save()
    return {"stopped": None, "asked": len(p["pending"]), **counts}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("estimate", "run"))
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    ap.add_argument("--yes", action="store_true", help="make the paid calls (run only)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    intelligence = json.loads(INTELLIGENCE_PATH.read_text(encoding="utf-8"))
    if args.command == "estimate" or not args.yes:
        print("\n".join(describe(plan(args.out, profile, intelligence))))
        if args.command == "run":
            print("nothing sent: add --yes after the estimate is approved")
        return 0
    result = run(args.out, profile, intelligence, args.workers)
    print(json.dumps(result))
    return 1 if result.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
