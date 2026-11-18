"""Fit 3 ORDER VARIANTS, SHADOW ONLY (W5 step 3, `~/holojob-eval/w5-benchmark-ranking.md`, Part 2, pre-registered).

Each variant is a key over one `fit3` block (the block of `fit3.fit3()`); only the coverage part of the key differs from `fit3.order_key`. Tier, domain, the
Insufficient-evidence group and the id tie-break are Fit 3's own. Nothing here is read by scoring: `scoringVersion` and `fit3.rank` / `fit3.order_key` are
unchanged. Every parameter comes from a benchmark clone (file named per variant); none is tuned.
"""

from __future__ import annotations

from fractions import Fraction

from . import fit3

MUST_WEIGHT, PREFERRED_WEIGHT = 3, 2  # applypack src/resume/score.ts SCORING.requirementWeight (must 3 / preferred 2); core = must, secondary = preferred
CORE_NONE_CAP = 30  # applypack src/screening/score.ts SCREEN_SCORING.caps.coreNone
CONFIDENCE_HIGH, CONFIDENCE_MEDIUM = Fraction(3, 4), Fraction(9, 20)  # applypack SCREEN_SCORING.confidence 0.75 / 0.45
BANDS = ((45, 0), (40, 1), (30, 2))  # career-ops lib/score-action.mjs SCORE_BANDS 4.5 / 4.0 / 3.0 on 5x at one decimal, as 10x integers
ORDERS = ("c1", "c2", "c3")


def round_half_up(x: Fraction) -> int:
    """JavaScript Math.round for a non-negative value."""
    return int((x + Fraction(1, 2)) // 1)


def _resolved_units(block: dict) -> tuple[list[dict], list[dict]]:
    units = block["requirements"]["units"]
    return ([u for u in units if u["ask"] == "core" and fit3.resolved(u)], [u for u in units if u["ask"] == "secondary" and fit3.resolved(u)])


def blend(block: dict) -> tuple[Fraction, Fraction, int]:
    """(B, core credit, resolved core count): B = (3 sum c(core) + 2 sum c(secondary)) / (3 n_core + 2 n_secondary) over the resolved units, 0 with none."""
    core, secondary = _resolved_units(block)
    core_credit = sum((fit3.credit(u) for u in core), Fraction(0))
    denominator = MUST_WEIGHT * len(core) + PREFERRED_WEIGHT * len(secondary)
    total = MUST_WEIGHT * core_credit + PREFERRED_WEIGHT * sum((fit3.credit(u) for u in secondary), Fraction(0))
    return (total / denominator if denominator else Fraction(0)), core_credit, len(core)


def confidence_band(block: dict) -> int:
    value = Fraction(block["requirements"]["coreCounts"]["resolvedCore"], block["requirements"]["coreCounts"]["core"]) if block["requirements"]["coreCounts"]["core"] else Fraction(0)
    return 0 if value >= CONFIDENCE_HIGH else 1 if value >= CONFIDENCE_MEDIUM else 2


def band(x: Fraction) -> int:
    q = round_half_up(50 * x)
    return next((b for floor, b in BANDS if q >= floor), 3)


def order_key(block: dict, order: str) -> tuple:
    """Smaller = ranked better. The id tie-break is added by `rank`, as in `fit3.rank`."""
    if order not in ORDERS:
        raise ValueError(f"unknown order {order!r}")
    head = (fit3.TIER.get(block["role"].get("class"), len(fit3.TIER)), block["domain"] == "different")
    b, core_credit, n_core = blend(block)
    if order == "c1":
        score = round_half_up(100 * b)
        if n_core and core_credit == 0:
            score = min(score, CORE_NONE_CAP)
        return (*head, -score, confidence_band(block))
    if order == "c2":
        return (*head, -round_half_up(50 * b))
    r = block["requirements"]
    return (*head, band(Fraction(r["coreCoverage"] or 0)), band(Fraction(r["secondaryCoverage"] or 0)))


def rank(rows: list[dict], order: str) -> dict:
    """Like `fit3.rank` (same refusal of non-3.0 rows, same Insufficient group), with the key of `order`."""
    for row in rows:
        block = row.get("fit3")
        if not isinstance(block, dict) or block.get("scoringVersion") != fit3.SCORING_VERSION:
            raise fit3.MixedScoringVersions(f"row {row.get('id')!r} is not a scoringVersion {fit3.SCORING_VERSION} row")
    sufficient = [r for r in rows if not r["fit3"]["insufficientEvidence"]]
    return {"ranked": sorted(sufficient, key=lambda r: (*order_key(r["fit3"], order), str(r.get("id")))),
            "insufficient": sorted((r for r in rows if r["fit3"]["insufficientEvidence"]), key=lambda r: str(r.get("id")))}
