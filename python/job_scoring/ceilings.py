"""Score ceilings of scoringVersion 1.6 (owner brief 2026-11-18). Code decides; no prompt holds a number.

  ROLE_CEILING   role class "other" caps the Fit Score at Weak (benchmarks: CareerPulse role_match cap, ApplyPack role-type ceiling).
                 "not available" never lowers a score: unknown does not lower (owner decision 2026-11-19). The class is stamped after
                 scoring (role_class.ceiling), so this runs there.
  LOCATION_CAP   an onsite or hybrid job outside the profile's relocation scope: Weak, not Blocked (scorer.py).
  UNMET_CAP      the share of the ad's must requirements the evidence engine marks unmet reaches theta: Good. Applied after the engine
                 answers are read (run_scoring), only while a theta is set; an ad with no engine answers is never capped.

A cap lowers the number and recomputes the band label and the verdict; `scoreBeforeCaps` keeps the uncapped number. Nothing is hidden.
"""

from __future__ import annotations

import labels

# The fixes of 1.6. SHIPPED_FIXES passed the pre-registered guard (~/holojob-eval/w5-top-fixes-plan.md, 2026-11-19) and run in production.
# "skill" (role-title tokens out of the Skill dimension) FAILED it alone (dev pair concordance 0.6956 against 0.7007, Spearman 0.4434 against
# 0.4528): its code stays for the record and the measurement scripts, off by default. EXTRA_FIXES / DISABLED_FIXES are for those scripts only.
SHIPPED_FIXES = frozenset({"role_ceiling", "clearance", "location", "unmet"})
ALL_FIXES = SHIPPED_FIXES | {"skill"}
EXTRA_FIXES: set[str] = set()
DISABLED_FIXES: set[str] = set()

# Fix 5 (engine statuses). Chosen by the pre-registered rule (2026-11-19): both variants passed the guard, B had the higher dev pair concordance
# (0.7024 against 0.7007), and its smallest passing theta is 0.3. Variant "A" counts CONTRADICTED, "B" counts CONTRADICTED and NOT_EVIDENCED.
# It acts only on ads that have engine answers (unknown does not lower); theta None = off.
UNMET_THETA: float | None = 0.3
UNMET_VARIANT = "B"
UNMET_STATUSES = {"A": ("CONTRADICTED",), "B": ("CONTRADICTED", "NOT_EVIDENCED")}
UNMET_MIN_DECIDED = 3
DECIDED_STATUSES = ("MET", "PARTIAL", "CONTRADICTED", "NOT_EVIDENCED")


def active_fixes() -> frozenset[str]:
    return (SHIPPED_FIXES | EXTRA_FIXES) - DISABLED_FIXES


ROLE_CEILING = 54  # top of Weak (labels.match_label: Weak is 40-54)
LOCATION_CAP = 54
UNMET_CAP = 69  # top of Good (Good is 55-69)
CEILING_ROLE_CLASSES = ("other",)


def cap_row(row: dict, ceiling: int, reason: str) -> bool:
    """Lower a scored row to `ceiling`, redo its label and verdict, say why. False when the row has no score or is already at or below it."""
    score = row.get("matchScore")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or score <= ceiling:
        return False
    flags, blocked = row.get("redFlags") or [], row.get("blockedBy") or []
    row["matchScore"] = ceiling
    row["matchLabel"] = labels.match_label(ceiling)
    row["applyRecommendation"], row["priority"] = labels.verdict(ceiling, flags, blocked)
    if blocked:
        row["blockedFrom"] = labels.blocked_from(ceiling, flags, blocked)
    row["hardCapped"] = True
    row["reasons"] = [*(row.get("reasons") or []), reason]
    return True


def unmet_share(row: dict, variant: str | None = None) -> dict | None:
    """{"share", "unmet", "decided"} over the must requirements of the row's engine answers, or None (no answers, or under UNMET_MIN_DECIDED)."""
    reqs = ((row.get("engineShadow") or {}).get("requirements")) or []
    musts = [r for r in reqs if isinstance(r, dict) and r.get("importance") == "must" and r.get("status") in DECIDED_STATUSES]
    if len(musts) < UNMET_MIN_DECIDED:
        return None
    counted = UNMET_STATUSES[variant or UNMET_VARIANT]
    unmet = sum(1 for r in musts if r["status"] in counted)
    return {"share": unmet / len(musts), "unmet": unmet, "decided": len(musts)}


def apply_unmet_ceiling(rows: list[dict], theta: float | None = None, variant: str | None = None) -> int:
    """Cap at UNMET_CAP every row whose unmet share reaches theta (default UNMET_THETA; None = off). Returns how many rows were lowered."""
    theta = UNMET_THETA if theta is None else theta
    lowered = 0
    if theta is None or "unmet" not in active_fixes():
        return lowered
    for row in rows:
        info = unmet_share(row, variant)
        if info and info["share"] >= theta and cap_row(
                row, UNMET_CAP, f"Capped: {info['unmet']} of {info['decided']} must requirements are not met by your profile (evidence engine), so no score above {UNMET_CAP}"):
            lowered += 1
    return lowered


NOT_EVALUATED_NOTE = "Ceiling not evaluated: no current evidence-engine answer for this ad, so the unmet-requirements ceiling did not run"
NOT_EVALUATED_OFF = "Ceiling not evaluated: the evidence engine did not run for this scoring, so the unmet-requirements ceiling did not run"


def stamp_engine_coverage(rows: list[dict], engine_on: bool) -> dict:
    """Say, per row, whether the engine ceiling could run: engineCoverage {"status", "reason"}. Returns the counts.

    answered        the row has engine answers for the current profile, prompt and requirement set: the ceiling ran (and may not have lowered it)
    not_evaluated   an open, scored ad with requirements and no current answer (a new or changed ad, a changed profile or prompt, the engine off,
                    a failed call): it passes the ceiling only because nothing was evaluated, and the row says so
    not_applicable  closed, not read, or no requirements extracted: there is nothing for the ceiling to read
    """
    counts = {"answered": 0, "not_evaluated": 0, "not_applicable": 0}
    for row in rows:
        shadow = row.get("engineShadow")
        if isinstance(shadow, dict) and shadow.get("requirements") is not None and not shadow.get("error"):
            status, reason = "answered", None
        elif row.get("isClosed") or row.get("matchScore") is None or not ((row.get("llmFacts") or {}).get("requirements")):
            status, reason = "not_applicable", None
        elif not engine_on:
            status, reason = "not_evaluated", "engine_off"
        else:
            status, reason = "not_evaluated", "failed" if isinstance(shadow, dict) and shadow.get("error") else "no_answer"
        row["engineCoverage"] = {"status": status, "reason": reason}
        counts[status] += 1
        if status == "not_evaluated":
            row["reasons"] = [*(row.get("reasons") or []), NOT_EVALUATED_OFF if reason == "engine_off" else NOT_EVALUATED_NOTE]
    return counts


def apply_role_ceiling(rows: list[dict]) -> int:
    """Cap every row whose role class is other / not available at ROLE_CEILING. Returns how many rows were lowered."""
    lowered = 0
    if "role_ceiling" not in active_fixes():
        return lowered
    for row in rows:
        cls = row.get("roleClass")
        if cls in CEILING_ROLE_CLASSES and cap_row(row, ROLE_CEILING, f"Capped: role class is {cls}, so no score above {ROLE_CEILING}"):
            lowered += 1
    return lowered
