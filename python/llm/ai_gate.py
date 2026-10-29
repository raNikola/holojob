#!/usr/bin/env python3
"""The AI budget gate: every real model call asks here first, and every one is recorded.

One module for the whole app. Python call sites import it (llm_client.complete_json,
claude_code._run); the Node side (scripts/run-ai.js) runs it as a CLI through
scripts/ai-gate.js, so there is one decision and one ledger.

The rules (owner decisions, 2026-10-29):

- Each provider / model has a class from src/data/aiPricing.json: free, local,
  paid or unknown. Unknown is treated as paid.
- Free and local calls are always allowed (except automatic tasks, below) and
  still recorded.
- A paid call needs a daily and a monthly limit above 0, a known price, and room
  under both limits and under the optional call counts. A budget of 0 (the
  default) refuses every paid call, the Claude Code CLI included.
- An automatic task (run_pipeline.py, enrich_jobs.py without --manual) runs only
  when settings `automation.enabled` is true; default off. This holds for free
  and local providers too.
- The check runs before the call and reserves the estimate under a file lock,
  so parallel workers and the Node server cannot overrun a limit together.
- A refused call raises AiRefused once and is recorded; the caller skips it.
  Nothing here retries.

Files, created at runtime and never committed (data/ai/ is in .gitignore):

    data/ai/settings.json        budget, limits, automation switch (defaults below when missing)
    data/ai/usage-ledger.jsonl   append-only, one JSON object per line

Costs are always estimates: tokens times the price-table entry. Tokens are the
provider's own count when it reports one, else characters / 4.
"""

from __future__ import annotations

import contextvars
import fcntl
import ipaddress
import json
import math
import os
import sys
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]

LEDGER_VERSION = 1
CLASSES = ("free", "local", "paid", "unknown")
FREE_CLASSES = {"free", "local"}

# A missing settings file means: no paid call, no automatic AI task.
DEFAULT_SETTINGS = {
    "currency": "USD",
    "dailyLimit": 0,
    "monthlyLimit": 0,
    "maxCallsDaily": None,
    "maxCallsMonthly": None,
    # Reserved per call for the answer before its size is known.
    "estimatedOutputTokens": 1000,
    # Day and month boundaries of the limits (IANA name).
    "timezone": "UTC",
    "automation": {"enabled": False},
}

TRIGGER_ENV = "CAREER_OS_AI_TRIGGER"
AUTOMATION = "automation"
MANUAL = "manual"

_feature: contextvars.ContextVar[str | None] = contextvars.ContextVar("ai_feature", default=None)
_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("ai_job_id", default=None)
_thread_lock = threading.RLock()


class AiRefused(RuntimeError):
    """The gate refused this call. It was recorded; skip the call, do not retry it."""

    def __init__(self, reason: str, row: dict | None = None):
        super().__init__(f"AI call refused: {reason}")
        self.reason = reason
        self.row = row or {}


# --- paths and settings ------------------------------------------------------


def ai_dir() -> Path:
    return Path(os.environ.get("CAREER_OS_AI_DIR") or ROOT / "data" / "ai")


def settings_path() -> Path:
    return ai_dir() / "settings.json"


def ledger_path() -> Path:
    return ai_dir() / "usage-ledger.jsonl"


def pricing_path() -> Path:
    return Path(os.environ.get("CAREER_OS_AI_PRICING") or ROOT / "src" / "data" / "aiPricing.json")


def load_settings() -> dict:
    """Effective settings; `error` is set when the file exists but cannot be used (then paid calls are refused)."""
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    path = settings_path()
    if not path.exists():
        return settings
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return {**settings, "error": f"{path.name} unreadable: {exc}"}
    automation = {**settings["automation"], **(stored.get("automation") or {})}
    return {**settings, **stored, "automation": automation}


def _limit(value) -> float:
    """A currency limit; missing, null or anything not a positive number counts as 0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 and math.isfinite(number) else 0.0


def _call_cap(value) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _zone(settings: dict):
    try:
        return ZoneInfo(str(settings.get("timezone") or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


# --- classification ----------------------------------------------------------


def _local_host(base_url: str | None) -> bool:
    if not base_url:
        return True
    host = (urlparse(base_url).hostname or "").lower()
    if not host or host == "localhost" or "." not in host or host.endswith((".local", ".internal")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def load_pricing() -> dict:
    try:
        return json.loads(pricing_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"currency": None, "entries": []}


def classify(provider: str, model: str | None = None, base_url: str | None = None) -> dict:
    """{class, inputPerMTok, outputPerMTok, priceKnown, currency, source, checkedAt} for one provider / model."""
    pricing = load_pricing()
    name = (provider or "").lower()
    entries = [e for e in pricing.get("entries") or [] if str(e.get("provider", "")).lower() == name]
    entry = next((e for e in entries if e.get("model") == model), None) or next(
        (e for e in entries if e.get("model") == "*"), None)
    if entry is None:
        return {"class": "unknown", "inputPerMTok": None, "outputPerMTok": None, "priceKnown": False,
                "currency": pricing.get("currency"), "source": None, "checkedAt": None}
    cls = entry.get("class") if entry.get("class") in CLASSES else "unknown"
    if cls == "local" and not _local_host(base_url):
        # Same software, someone else's machine: its bill is not known.
        cls = "unknown"
    price_in, price_out = entry.get("inputPerMTok"), entry.get("outputPerMTok")
    known = isinstance(price_in, (int, float)) and isinstance(price_out, (int, float))
    return {
        "class": cls,
        "inputPerMTok": price_in if known else None,
        "outputPerMTok": price_out if known else None,
        "priceKnown": known,
        "currency": pricing.get("currency"),
        "source": entry.get("source"),
        "checkedAt": entry.get("checkedAt"),
    }


def is_paid(cls: str) -> bool:
    return cls not in FREE_CLASSES


# --- context -----------------------------------------------------------------


@contextmanager
def context(feature: str | None = None, job_id: str | None = None):
    """Name the feature (and job) of the calls made inside; set it in the thread that makes the call."""
    tokens = [_feature.set(feature) if feature is not None else None,
              _job_id.set(str(job_id)) if job_id is not None else None]
    try:
        yield
    finally:
        if tokens[1] is not None:
            _job_id.reset(tokens[1])
        if tokens[0] is not None:
            _feature.reset(tokens[0])


def current_trigger() -> str:
    return AUTOMATION if os.environ.get(TRIGGER_ENV, "").strip().lower() == AUTOMATION else MANUAL


def estimate_tokens(chars: int) -> int:
    return math.ceil(max(0, int(chars or 0)) / 4)


def _cost(price: dict, input_tokens: int, output_tokens: int) -> float | None:
    if not price["priceKnown"]:
        return None
    return round(input_tokens * price["inputPerMTok"] / 1e6 + output_tokens * price["outputPerMTok"] / 1e6, 6)


# --- ledger ------------------------------------------------------------------


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


@contextmanager
def _locked():
    """One writer at a time across threads and processes (Python and the Node server's CLI calls)."""
    directory = ai_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with _thread_lock:
        with open(directory / ".ledger.lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _append(row: dict) -> None:
    """Append one line; the ledger is never rewritten or truncated."""
    with open(ledger_path(), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_ledger() -> list[dict]:
    path = ledger_path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn last line from a crash is skipped, never repaired in place
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _calls(rows: list[dict]) -> list[dict]:
    """Call rows merged with their result row (actual tokens and cost when known)."""
    results = {r.get("id"): r for r in rows if r.get("type") == "result"}
    merged = []
    for row in rows:
        if row.get("type") != "call":
            continue
        result = results.get(row.get("id"))
        if result:
            row = {**row, **{k: result[k] for k in ("inputTokens", "outputTokens", "tokensAreEstimate", "cost")
                             if k in result and result[k] is not None},
                   "ok": result.get("ok"), "error": result.get("error")}
        merged.append(row)
    return merged


def _bucket():
    return {"calls": 0, "paidCalls": 0, "refused": 0, "cacheHits": 0,
            "inputTokens": 0, "outputTokens": 0, "cost": 0.0, "unpricedPaidCalls": 0}


def totals(now: datetime | None = None, settings: dict | None = None) -> dict:
    """Today's and this month's usage in the settings' timezone. Spend counts paid allowed calls only."""
    settings = settings or load_settings()
    zone = _zone(settings)
    local_now = _now(now).astimezone(zone)
    day_key, month_key = local_now.date().isoformat(), local_now.strftime("%Y-%m")
    out = {"day": day_key, "month": month_key, "today": _bucket(), "thisMonth": _bucket(),
           "byProvider": {}, "byFeature": {}}
    for row in _calls(read_ledger()):
        try:
            when = datetime.fromisoformat(row["ts"]).astimezone(zone)
        except (KeyError, ValueError):
            continue
        if when.strftime("%Y-%m") != month_key:
            continue
        buckets = [out["thisMonth"]] + ([out["today"]] if when.date().isoformat() == day_key else [])
        for key, name in (("byProvider", f"{row.get('provider')}/{row.get('model') or '-'}"),
                          ("byFeature", row.get("feature") or "unspecified")):
            buckets.append(out[key].setdefault(name, _bucket()))
        for b in buckets:
            decision = row.get("decision")
            if decision == "refused":
                b["refused"] += 1
                continue
            if decision == "cache-hit":
                b["cacheHits"] += 1
                continue
            b["calls"] += 1
            b["inputTokens"] += int(row.get("inputTokens") or 0)
            b["outputTokens"] += int(row.get("outputTokens") or 0)
            if is_paid(row.get("class", "unknown")):
                b["paidCalls"] += 1
                if row.get("cost") is None:
                    b["unpricedPaidCalls"] += 1
                else:
                    b["cost"] = round(b["cost"] + float(row["cost"]), 6)
    return out


# --- the gate ----------------------------------------------------------------


@dataclass
class Decision:
    allowed: bool
    reason: str | None
    row: dict = field(default_factory=dict)


def _decide(row: dict, price: dict, settings: dict, now: datetime | None) -> str | None:
    """The refusal reason, or None when the call may go."""
    if row["trigger"] == AUTOMATION and not (settings.get("automation") or {}).get("enabled"):
        return "automatic AI tasks are off (data/ai/settings.json automation.enabled is false)"
    if not is_paid(row["class"]):
        return None
    label = f"{row['provider']}/{row['model'] or 'default'}"
    if settings.get("error"):
        return f"paid call {label} refused: {settings['error']}"
    daily, monthly = _limit(settings.get("dailyLimit")), _limit(settings.get("monthlyLimit"))
    if daily == 0 or monthly == 0:
        return (f"paid call {label} refused: AI budget is 0 "
                f"(daily {daily:g}, monthly {monthly:g} {settings.get('currency')}; class {row['class']})")
    if not price["priceKnown"]:
        return f"paid call {label} refused: price unknown; add it to src/data/aiPricing.json with its source"
    if price.get("currency") != settings.get("currency"):
        return (f"paid call {label} refused: prices are in {price.get('currency')}, "
                f"the budget in {settings.get('currency')}")
    t = totals(now, settings)
    estimate = row["cost"] or 0.0
    if t["today"]["cost"] + estimate > daily:
        return f"daily AI budget reached ({t['today']['cost']:.4f} + {estimate:.4f} > {daily:g} {settings['currency']})"
    if t["thisMonth"]["cost"] + estimate > monthly:
        return (f"monthly AI budget reached ({t['thisMonth']['cost']:.4f} + {estimate:.4f} > "
                f"{monthly:g} {settings['currency']})")
    cap = _call_cap(settings.get("maxCallsDaily"))
    if cap is not None and t["today"]["paidCalls"] + 1 > cap:
        return f"daily paid call limit reached ({cap})"
    cap = _call_cap(settings.get("maxCallsMonthly"))
    if cap is not None and t["thisMonth"]["paidCalls"] + 1 > cap:
        return f"monthly paid call limit reached ({cap})"
    return None


def _call_row(provider: str, model: str | None, prompt_chars: int, base_url: str | None, feature: str | None,
              job_id: str | None, trigger: str | None, output_tokens: int | None, settings: dict,
              now: datetime | None) -> tuple[dict, dict]:
    price = classify(provider, model, base_url)
    input_tokens = estimate_tokens(prompt_chars)
    out_tokens = int(output_tokens if output_tokens is not None else settings.get("estimatedOutputTokens") or 0)
    row = {
        "v": LEDGER_VERSION,
        "type": "call",
        "id": uuid.uuid4().hex,
        "ts": _now(now).isoformat(),
        "feature": feature or _feature.get() or "unspecified",
        "trigger": trigger or current_trigger(),
        "provider": (provider or "").lower(),
        "model": model or None,
        "class": price["class"],
        "jobId": job_id if job_id is not None else _job_id.get(),
        "cache": "miss",
        "inputTokens": input_tokens,
        "outputTokens": out_tokens,
        "tokensAreEstimate": True,
        "cost": _cost(price, input_tokens, out_tokens),
        "currency": price.get("currency"),
        "costIsEstimate": True,
        "priceKnown": price["priceKnown"],
    }
    return row, price


def check(provider: str, model: str | None, prompt_chars: int, *, base_url: str | None = None,
          feature: str | None = None, job_id: str | None = None, trigger: str | None = None,
          output_tokens: int | None = None, now: datetime | None = None) -> Decision:
    """What reserve() would decide, without recording anything. For a batch, before its first call."""
    settings = load_settings()
    row, price = _call_row(provider, model, prompt_chars, base_url, feature, job_id, trigger, output_tokens,
                           settings, now)
    reason = _decide(row, price, settings, now)
    return Decision(reason is None, reason, row)


def record_refused(decision: Decision, skipped: int = 1) -> None:
    """Record a refusal found by check(); `skipped` is how many calls the caller then did not make."""
    row = {**decision.row, "decision": "refused", "reason": decision.reason, "skipped": skipped}
    with _locked():
        _append(row)


class Ticket:
    """An allowed call. finish() records what it actually used; call it once, success or not."""

    def __init__(self, row: dict, price: dict):
        self.row = row
        self.price = price
        self.id = row["id"]
        self._finished = False

    def finish(self, ok: bool, *, input_tokens: int | None = None, output_tokens: int | None = None,
               error: str | None = None, attempts: int | None = None,
               reported_cost_usd: float | None = None, now: datetime | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        measured = input_tokens is not None and output_tokens is not None
        tin = int(input_tokens) if measured else self.row["inputTokens"]
        tout = int(output_tokens) if measured else (self.row["outputTokens"] if ok else 0)
        result = {
            "v": LEDGER_VERSION,
            "type": "result",
            "id": self.id,
            "ts": _now(now).isoformat(),
            "ok": bool(ok),
            "error": (error or "")[:300] or None,
            "inputTokens": tin,
            "outputTokens": tout,
            "tokensAreEstimate": not measured,
            "cost": _cost(self.price, tin, tout),
            "currency": self.price.get("currency"),
            "costIsEstimate": True,
        }
        if attempts is not None:
            result["attempts"] = attempts
        if reported_cost_usd is not None:
            result["providerReportedCostUsd"] = reported_cost_usd
        with _locked():
            _append(result)


def reserve(provider: str, model: str | None, prompt_chars: int, *, base_url: str | None = None,
            feature: str | None = None, job_id: str | None = None, trigger: str | None = None,
            output_tokens: int | None = None, now: datetime | None = None) -> Ticket:
    """Check and record one call before it is made. Raises AiRefused (already recorded) when it may not go."""
    with _locked():
        settings = load_settings()
        row, price = _call_row(provider, model, prompt_chars, base_url, feature, job_id, trigger, output_tokens,
                               settings, now)
        reason = _decide(row, price, settings, now)
        row.update(decision="refused" if reason else "allowed", reason=reason)
        _append(row)
    if reason:
        print(f"AI gate: {reason}", file=sys.stderr, flush=True)
        raise AiRefused(reason, row)
    return Ticket(row, price)


def record_cache_hit(provider: str, model: str | None, *, feature: str | None = None,
                     job_id: str | None = None, now: datetime | None = None) -> None:
    """A stored answer served in place of a call: recorded, never counted against the budget."""
    row = {
        "v": LEDGER_VERSION, "type": "call", "id": uuid.uuid4().hex, "ts": _now(now).isoformat(),
        "feature": feature or _feature.get() or "unspecified", "trigger": current_trigger(),
        "provider": (provider or "").lower(), "model": model or None,
        "class": classify(provider, model)["class"], "jobId": job_id if job_id is not None else _job_id.get(),
        "cache": "hit", "decision": "cache-hit", "reason": None, "inputTokens": 0, "outputTokens": 0,
        "tokensAreEstimate": False, "cost": 0.0, "currency": load_pricing().get("currency"),
        "costIsEstimate": True,
    }
    with _locked():
        _append(row)


def usage_summary(now: datetime | None = None) -> dict:
    """What GET /api/ai/usage returns: effective settings, totals, and where the files are."""
    settings = load_settings()
    return {
        "settings": settings,
        "settingsFile": str(settings_path()),
        "settingsFileExists": settings_path().exists(),
        "ledgerFile": str(ledger_path()),
        "pricingFile": str(pricing_path()),
        "costsAreEstimates": True,
        **totals(now, settings),
    }


# --- CLI (scripts/ai-gate.js) ------------------------------------------------


def _cli(argv: list[str]) -> int:
    """`reserve`, `finish`, `cache-hit`, `usage`: JSON on stdin, one JSON object on stdout."""
    command = argv[0] if argv else ""
    raw = sys.stdin.read() if command != "usage" else ""
    args = json.loads(raw) if raw.strip() else {}
    if command == "reserve":
        try:
            ticket = reserve(args.get("provider") or "", args.get("model"), int(args.get("promptChars") or 0),
                             base_url=args.get("baseUrl"), feature=args.get("feature"), job_id=args.get("jobId"),
                             trigger=args.get("trigger"), output_tokens=args.get("outputTokens"))
        except AiRefused as exc:
            print(json.dumps({"allowed": False, "reason": exc.reason, "id": exc.row.get("id")}))
            return 0
        print(json.dumps({"allowed": True, "id": ticket.id, "class": ticket.row["class"]}))
        return 0
    if command == "finish":
        # The CLI is a new process per step, so the reserved row is read back from the ledger.
        row = next((r for r in read_ledger() if r.get("type") == "call" and r.get("id") == args.get("id")
                    and r.get("decision") == "allowed"), None)
        if row is None:
            print(json.dumps({"ok": False, "error": "unknown call id"}))
            return 1
        if any(r.get("type") == "result" and r.get("id") == row["id"] for r in read_ledger()):
            print(json.dumps({"ok": False, "error": "call already finished"}))
            return 1
        price = classify(row["provider"], row.get("model"), args.get("baseUrl"))
        if price["class"] != row.get("class"):
            price = {**price, "priceKnown": False}
        Ticket(row, price).finish(
            bool(args.get("ok")), input_tokens=args.get("inputTokens"), output_tokens=args.get("outputTokens"),
            error=args.get("error"))
        print(json.dumps({"ok": True}))
        return 0
    if command == "cache-hit":
        record_cache_hit(args.get("provider") or "", args.get("model"), feature=args.get("feature"),
                         job_id=args.get("jobId"))
        print(json.dumps({"ok": True}))
        return 0
    if command == "usage":
        print(json.dumps(usage_summary()))
        return 0
    print("usage: ai_gate.py reserve|finish|cache-hit|usage  (JSON on stdin)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
