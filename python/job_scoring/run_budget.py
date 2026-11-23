"""One run budget for Re-scrape's paid steps (owner decision 2026-11-23).

Classification, reading and engine fill share ONE limit, set in Settings (`runLimitUsd`, `runLimitAds`, `ai_gate.run_limits`). No number
lives in code: a missing or 0 limit means the paid steps spend nothing and the run says "run limit not set in Settings". The orchestrator
(`run_rescrape.py`) measures what the run has really spent from the AI ledger, so a step's own print is never trusted, and passes the
REMAINDER to the next step as `--max-usd` / `--max-ads`. A distinct ad counts once, however many steps handle it.

This module also holds what the three steps share: the fixed stop codes, the order (this run's ads first, then the backlog; strongest first
inside each), and the one-line JSON summary each step prints. It decides nothing about scoring: the tier cutoffs are the ones of
`src/modules/jobs/fitTier.js` (a test keeps them equal), used only to order paid work.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
for sub in ("llm", "job_scoring"):
    sys.path.insert(0, str(HERE.parents[0] / sub))

import ai_gate  # noqa: E402

FEATURES = ("fit3-classify", "enrichment", "evidence-matcher")  # the ledger features of the three paid steps
STRONG_MIN, POSSIBLE_MIN = 70, 55  # = fitTier.js; ordering only

# The fixed stop codes (the Activity screen has the wording; free text of a stop never goes into a record).
STOP_RUN_USD, STOP_RUN_ADS, STOP_DAILY, STOP_MONTHLY, STOP_CALL_CAP = "run_usd", "run_ads", "daily", "monthly", "call_cap"
STOP_FAILURES, STOP_UNSET, STOP_GATE, STOP_ENGINE_NOT_ALLOWED = "failures", "unset", "gate", "engine_not_allowed"
# not_sent: the step could not send (no price for the model, no profile for the privacy scan, an error); no_report: it ended without its summary line.
STOP_NOT_SENT, STOP_NO_REPORT = "not_sent", "no_report"
STOP_CODES = (STOP_RUN_USD, STOP_RUN_ADS, STOP_DAILY, STOP_MONTHLY, STOP_CALL_CAP, STOP_FAILURES, STOP_UNSET, STOP_GATE, STOP_ENGINE_NOT_ALLOWED,
              STOP_NOT_SENT, STOP_NO_REPORT)


def stop_code(text: str | None) -> str | None:
    """A stop's text (a guard message or the AI gate's reason) as one fixed code; None for no stop."""
    if not text:
        return None
    low = str(text).lower()
    if low in STOP_CODES:
        return low
    if "in a row" in low:
        return STOP_FAILURES
    if "could pass the" in low and "cap" in low:
        return STOP_RUN_USD
    if "paid call limit" in low:
        return STOP_CALL_CAP
    if "daily ai budget" in low:
        return STOP_DAILY
    if "monthly ai budget" in low:
        return STOP_MONTHLY
    return STOP_GATE


@dataclass
class Limits:
    usd: float
    ads: int
    stop: str | None = None  # unset | run_usd | run_ads: the step sends nothing and counts what waits


def _positive(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 and number != float("inf") and number == number else 0.0


def resolve_limits(max_usd: float | None, max_ads: int | None, settings: dict | None = None) -> Limits:
    """The limits of one step. A flag that was given wins (0 means the budget is used up); an omitted one is read from Settings, never from code."""
    settings = ai_gate.load_settings() if settings is None else settings
    usd = max_usd if max_usd is not None else _positive(settings.get("runLimitUsd"))
    ads = max_ads if max_ads is not None else (settings.get("runLimitAds") if isinstance(settings.get("runLimitAds"), int) else 0)
    if (max_usd is None and usd <= 0) or (max_ads is None and not ads > 0):
        return Limits(0.0, 0, STOP_UNSET)
    if usd <= 0:
        return Limits(0.0, max(0, int(ads)), STOP_RUN_USD)
    if ads <= 0:
        return Limits(float(usd), 0, STOP_RUN_ADS)
    return Limits(float(usd), int(ads))


# The priority groups of Re-scrape (owner decision 2026-11-23), worked as ordered passes over the same steps so a small limit is spent on them in this order:
#   new       the ads this run found: classify, read, engine fill
#   existing  ads classified before this run, Strong or Possible, still unread or without an engine answer: read, then engine fill
#   backlog   everything older: classify the unclassified, then read and engine-fill those that turn out Target / Adjacent, with what budget remains
GROUPS = ("new", "existing", "backlog")


def in_group(job: dict, group: str | None, prior: dict[str, dict], run_start: str | None) -> bool:
    """Is this ad part of the pass `group`? No group means every ad (a standalone run). `prior` is the last scored view (jobId -> fields), which gives the tier.

    A pass of `existing` runs before the backlog is classified, so every Strong or Possible ad it can see was classified before this run: the group
    needs no snapshot. `backlog` is every ad of an older run, whatever its tier (Strong first, Weak last by the order)."""
    if group is None:
        return True
    is_new = first_seen_after(job, run_start)
    if group == "new":
        return is_new
    if is_new:
        return False
    if group == "existing":
        return tier_rank(prior.get(str(job.get("jobId")))) in (0, 1)
    return True


def add_args(ap) -> None:
    """The flags every paid step shares when it runs inside Re-scrape."""
    ap.add_argument("--group", choices=GROUPS, default=None, help="only the ads of this priority group (Re-scrape works new, existing, backlog in that order)")
    ap.add_argument("--run-start", default=None, help="ISO time the run began: ads first seen after it are processed first")
    ap.add_argument("--counted-ids", type=Path, default=None, help="a JSON list of ad ids this run already counted; they do not use the ads limit again")


# --- what the run has spent ---------------------------------------------------------------------------------------------------------------------
def usage_since(started_at: datetime, rows: list[dict] | None = None, features: tuple[str, ...] = FEATURES) -> tuple[float, set[str]]:
    """(US dollars, distinct ad ids) of the allowed calls of the paid features since `started_at`, from the ledger."""
    rows = ai_gate.read_ledger() if rows is None else rows
    calls: dict[str, str] = {}
    for row in rows:
        if row.get("type") != "call" or row.get("decision") != "allowed" or row.get("feature") not in features:
            continue
        try:
            if datetime.fromisoformat(row["ts"]) < started_at:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        calls[row.get("id")] = str(row.get("jobId") or "")
    usd = sum(float(r.get("cost") or 0) for r in rows if r.get("type") == "result" and r.get("id") in calls)
    return round(usd, 6), {j for j in calls.values() if j}


def read_counted(path: Path | None) -> set[str]:
    if not path:
        return set()
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(i) for i in found} if isinstance(found, list) else set()


# --- order --------------------------------------------------------------------------------------------------------------------------------------
def prior_view(scored_path: Path) -> dict[str, dict]:
    """jobId -> the few fields of the last scored row that decide the order. A missing or unreadable file is an empty view."""
    try:
        rows = json.loads(scored_path.read_text(encoding="utf-8")).get("jobs") or []
    except (OSError, ValueError, AttributeError):
        return {}
    keep = ("matchScore", "applyRecommendation", "blockedBy", "isClosed", "llmFacts", "roleClass")
    return {str(r.get("jobId")): {k: r.get(k) for k in keep} for r in rows if isinstance(r, dict) and r.get("jobId") is not None}


def is_blocked(row: dict | None) -> bool:
    return bool(row) and (bool(row.get("blockedBy")) or row.get("applyRecommendation") == "Blocked")


def tier_rank(row: dict | None) -> int:
    """0 Strong, 1 Possible, 2 not scored yet, 3 Weak, 4 Blocked. Mirrors fitTier.js (70+ / 55-69, Skip is Weak); ordering only."""
    if row is None:
        return 2
    if is_blocked(row):
        return 4
    score = row.get("matchScore")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return 2
    if row.get("applyRecommendation") == "Skip":
        return 3
    return 0 if score >= STRONG_MIN else 1 if score >= POSSIBLE_MIN else 3


def first_seen_after(job: dict, run_start: str | None) -> bool:
    if not run_start:
        return False
    try:
        return datetime.fromisoformat(str(job.get("firstSeen"))) >= datetime.fromisoformat(run_start)
    except (TypeError, ValueError):
        return False


def order_key(job: dict, prior: dict[str, dict], run_start: str | None) -> tuple:
    """This run's ads first, then the backlog; inside each, Strong, Possible, not scored, Weak, Blocked."""
    return (0 if first_seen_after(job, run_start) else 1, tier_rank(prior.get(str(job.get("jobId")))))


def trim(ordered_ids: list[str], max_ads: int, counted: set[str]) -> tuple[list[str], list[str]]:
    """(selected, waiting) from ads in processing order. An ad the run already counted is free; a new one takes one of `max_ads`."""
    seen, fresh, selected, waiting = set(counted), 0, [], []
    for job_id in ordered_ids:
        if job_id in seen:
            selected.append(job_id)
        elif fresh < max_ads:
            fresh += 1
            seen.add(job_id)
            selected.append(job_id)
        else:
            waiting.append(job_id)
    return selected, waiting


def summary_line(step: str, **fields) -> str:
    """The one JSON line a step prints last. Counts and a fixed stop code only; the orchestrator reads it."""
    return json.dumps({"step": step, **fields})


def parse_summary(output: str, step: str) -> dict | None:
    for line in reversed(output.strip().splitlines()):
        if line.startswith("{"):
            try:
                found = json.loads(line)
            except ValueError:
                continue
            if isinstance(found, dict) and found.get("step") == step:
                return found
    return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
