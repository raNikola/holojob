"""Score ceilings of scoringVersion 1.6 (owner brief 2026-11-18). Code decides; no prompt holds a number.

  ROLE_CEILING   role class "other" or "not available" caps the Fit Score at Weak (benchmarks: CareerPulse role_match cap,
                 ApplyPack role-type ceiling). The class is stamped after scoring (role_class.stamp), so this runs there.
  LOCATION_CAP   an onsite or hybrid job outside the profile's relocation scope: Weak, not Blocked (scorer.py).
  UNMET_CAP      the share of unmet must requirements reaches theta: Good (scorer.py, only while a theta is set).

A cap lowers the number and recomputes the band label and the verdict; `scoreBeforeCaps` keeps the uncapped number. Nothing is hidden.
"""

from __future__ import annotations

import labels

# The five fixes of 1.6. Production runs all of them; only the measurement scripts (leave-one-out, each fix alone) switch one off.
ALL_FIXES = frozenset({"skill", "role_ceiling", "clearance", "location", "unmet"})
DISABLED_FIXES: set[str] = set()


def active_fixes() -> frozenset[str]:
    return ALL_FIXES - DISABLED_FIXES


ROLE_CEILING = 54  # top of Weak (labels.match_label: Weak is 40-54)
LOCATION_CAP = 54
UNMET_CAP = 69  # top of Good (Good is 55-69)
CEILING_ROLE_CLASSES = ("other", "not available")


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
