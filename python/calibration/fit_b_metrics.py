"""Experiment B, evaluation arithmetic (offline, no model, no data access). Pre-registered in ~/holojob-eval/exp-b-plan.md; a change here
after a result is a change of the plan, so it needs an appended section with a new sha256 there first.

Not part of scoring: nothing in python/job_scoring imports this.
"""

from __future__ import annotations

import math
import random

# Owner levels -> gains. Dev ads carry a level 0..3; a holdout verdict is apply / maybe / skip (own proposal for maybe: the midpoint).
VERDICT_GAIN = {"apply": 3.0, "maybe": 1.5, "skip": 0.0}
TOP_GAIN = 3.0
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261119
CI_LEVEL = 0.80
MIN_DELTA = 0.05
SD_MULTIPLE = 2.0


def combined_gain(level_gain: float | None, applied: bool) -> float | None:
    """max(level gain, applied gain). An applied ad has the top gain; an ad with neither a level nor an application is unlabelled (None)."""
    if applied:
        return TOP_GAIN if level_gain is None else max(level_gain, TOP_GAIN)
    return level_gain


def order(scores: dict[str, float], ids: list[str] | None = None) -> list[str]:
    """Ad ids best first: score descending, ties by ad id ascending. An ad with no score ranks last (by id)."""
    ids = list(scores) if ids is None else ids
    return sorted(ids, key=lambda i: (scores.get(i) is None, -(scores.get(i) or 0.0), i))


def dcg(gains: list[float], k: int) -> float:
    return sum(g / math.log2(pos + 2) for pos, g in enumerate(gains[:k]))


def ndcg_at(ranked_gains: list[float], k: int) -> float | None:
    """nDCG@k with linear gain; None when the ideal DCG is 0 (no ad has a positive gain)."""
    ideal = dcg(sorted(ranked_gains, reverse=True), k)
    return None if ideal == 0 else dcg(ranked_gains, k) / ideal


def ndcg_of(scores: dict[str, float], gains: dict[str, float], k: int) -> float | None:
    """nDCG@k over the labelled ads only (unlabelled are excluded, never counted as 0), ties by ad id."""
    labelled = [i for i in gains if gains[i] is not None]
    return ndcg_at([gains[i] for i in order(scores, labelled)], k)


def expected_dcg(pairs: list[tuple], k: int) -> float:
    """Exact expected DCG@k over all orderings within groups of equal scores. `pairs` = [(score or None, gain)]. DCG is linear in the gain at each
    position, and every member of a tied group is equally likely at each of the group's positions, so a group that occupies positions s..s+g-1
    contributes (mean gain of the group) x (sum of the position discounts inside the top k). No sampling. An unscored ad (None) is the last group."""
    groups: dict = {}
    for score, gain in pairs:
        groups.setdefault(None if score is None else float(score), []).append(gain)
    total, start = 0.0, 0
    for score in sorted(groups, key=lambda v: (v is None, -(v or 0.0))):
        members = groups[score]
        discount = sum(1 / math.log2(pos + 2) for pos in range(start, min(start + len(members), k)))
        total += (sum(members) / len(members)) * discount
        start += len(members)
    return total


def ndcg_tie_aware_pairs(pairs: list[tuple], k: int) -> float | None:
    ideal = dcg(sorted((g for _, g in pairs), reverse=True), k)
    return None if ideal == 0 else expected_dcg(pairs, k) / ideal


def ndcg_tie_aware(scores: dict[str, float], gains: dict[str, float], k: int) -> float | None:
    """PRIMARY metric (Amendment 5): nDCG@k, labelled ads only, expected over all orderings inside tied score groups. `ndcg_of` (ad id order) is the secondary."""
    return ndcg_tie_aware_pairs([(scores.get(i), gains[i]) for i in gains if gains[i] is not None], k)


def precision_at(scores: dict[str, float], gains: dict[str, float], k: int, threshold: float = 3.0) -> float | None:
    """Share of the top k labelled ads whose gain reaches `threshold` (the Apply level)."""
    labelled = [i for i in gains if gains[i] is not None]
    top = order(scores, labelled)[:k]
    return None if not top else sum(1 for i in top if gains[i] >= threshold) / len(top)


def tie_share(scores: dict[str, float]) -> float:
    """Share of ads that sit in a group of equal scores (diagnostic: a clustering model makes the id tie-break drive the metric)."""
    values = [v for v in scores.values() if v is not None]
    if not values:
        return 0.0
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sum(c for c in counts.values() if c > 1) / len(values)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(values):
        idx = sorted(range(len(values)), key=lambda i: values[i])
        out, i = [0.0] * len(values), 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and values[idx[j + 1]] == values[idx[i]]:
                j += 1
            for t in range(i, j + 1):
                out[idx[t]] = (i + j) / 2 + 1
            i = j + 1
        return out
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx, vy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return None if not vx or not vy else cov / math.sqrt(vx * vy)


def run_to_run_sd(ndcg_a: float, ndcg_b: float) -> float:
    """SD of nDCG@10 between two runs of the same method on the same ads: |a - b| / sqrt(2) (the sample SD of two values)."""
    return abs(ndcg_a - ndcg_b) / math.sqrt(2)


def delta_for(sd: float) -> float:
    return max(MIN_DELTA, SD_MULTIPLE * sd)


def paired_bootstrap(scores_b: dict[str, float], scores_base: dict[str, float], gains: dict[str, float], k: int = 10,
                     resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED, level: float = CI_LEVEL) -> dict:
    """Paired bootstrap of nDCG@k(B) - nDCG@k(baseline), resampling ads with replacement.

    Each draw is its own item; both methods are scored with the tie-aware nDCG (Amendment 5: expected value over the orderings inside tied scores, so
    no ad id or draw index order is used). A resample whose
    ideal DCG is 0 is discarded and redrawn (counted in `redrawn`). The interval is the percentile interval with `level` mass in the middle.
    """
    ids = sorted(i for i in gains if gains[i] is not None and i in scores_b and i in scores_base)
    if len(ids) < 3:
        return {"n": len(ids), "diffs": [], "low": None, "high": None, "redrawn": 0}
    rng = random.Random(seed)
    diffs, redrawn = [], 0
    while len(diffs) < resamples:
        draw = [ids[rng.randrange(len(ids))] for _ in ids]
        items = list(enumerate(draw))
        g = [gains[i] for _, i in items]
        if dcg(sorted(g, reverse=True), k) == 0:
            redrawn += 1
            continue

        diffs.append(ndcg_tie_aware_pairs([(scores_b[i], gains[i]) for _, i in items], k)
                     - ndcg_tie_aware_pairs([(scores_base[i], gains[i]) for _, i in items], k))
    diffs.sort()
    tail = (1 - level) / 2
    return {"n": len(ids), "diffs": diffs, "low": diffs[int(tail * len(diffs))], "high": diffs[min(len(diffs) - 1, int((1 - tail) * len(diffs)))], "redrawn": redrawn}


def apply_guard(scores_b: dict[str, float], scores_base: dict[str, float], gains: dict[str, float]) -> dict:
    """Labelled Apply ads (gain at the top) that are in the baseline's top half of the evaluated ads must be in B's top half. Returns the violators."""
    ids = [i for i in gains if gains[i] is not None and i in scores_b and i in scores_base]
    half = math.ceil(len(ids) / 2)
    top_base, top_b = set(order(scores_base, ids)[:half]), set(order(scores_b, ids)[:half])
    violators = sorted(i for i in ids if gains[i] >= TOP_GAIN and i in top_base and i not in top_b)
    return {"half": half, "violators": violators, "pass": not violators}


def verdict(scores_b: dict[str, float], scores_base: dict[str, float], gains: dict[str, float], delta: float, k: int = 10) -> dict:
    """The pre-registered win rule: diff >= delta, AND the bootstrap CI lower bound > 0, AND the apply guard holds."""
    nb, n0 = ndcg_tie_aware(scores_b, gains, k), ndcg_tie_aware(scores_base, gains, k)
    nb_id, n0_id = ndcg_of(scores_b, gains, k), ndcg_of(scores_base, gains, k)
    boot = paired_bootstrap(scores_b, scores_base, gains, k)
    guard = apply_guard(scores_b, scores_base, gains)
    diff = None if nb is None or n0 is None else nb - n0
    win = bool(diff is not None and diff >= delta and boot["low"] is not None and boot["low"] > 0 and guard["pass"])
    return {"ndcg10_B": nb, "ndcg10_base": n0, "diff": diff, "delta": delta, "ndcg10_B_idTieBreak": nb_id, "ndcg10_base_idTieBreak": n0_id, "ciLow": boot["low"], "ciHigh": boot["high"], "n": boot["n"],
            "redrawn": boot["redrawn"], "guard": guard, "win": win}
