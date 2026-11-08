"""Per-category yield of Infostud's listing (Wave 4, c): counts only, so the owner can see where the relevant ads come from.

`summarize` is pure (rows in, counts out) and is what the tests cover. `scripts/infostud-coverage-probe.py` does the network part.
It decides nothing: no category is added or removed because of it. No title, company or link is in its output; a board
`standardizedPosition` label is public taxonomy, and only its counts are shown.
"""

from __future__ import annotations

from collections import Counter

from providers import role_filter

TOP_POSITIONS = 8


def summarize(per_category: dict, extra_terms: tuple[str, ...] = (), combined: tuple[list, int] | None = None) -> dict:
    """`per_category`: {category id: (normalized rows, reported total)}. `combined`: (rows, reported total) of the one query that
    holds every category, as discovery reads it. Returns counts per category and across them."""
    seen_in: dict = {}
    categories = {}
    for category, (rows, reported) in per_category.items():
        tiers: Counter = Counter()
        reasons: Counter = Counter()
        positions: Counter = Counter()
        ids = set()
        for row in rows:
            ids.add(row.get("externalId"))
            tier, reason = role_filter.role_tier(row.get("title", ""), row.get("standardizedPosition") or "", extra_terms)
            tiers[tier] += 1
            if reason:
                reasons[reason.split(":", 1)[0]] += 1
            else:
                positions[row.get("standardizedPosition") or "(none)"] += 1
            seen_in.setdefault(row.get("externalId"), set()).add(category)
        categories[category] = {
            "reported": reported, "read": len(rows), "readMatchesReported": len(rows) == reported,
            "target": tiers[role_filter.TARGET], "near": tiers[role_filter.NEAR], "excluded": tiers[role_filter.EXCLUDED],
            "excludedBy": dict(reasons), "relevantPositions": dict(positions.most_common(TOP_POSITIONS)),
        }
    distinct = len(seen_in)
    out = {
        "categories": categories,
        "distinctAds": distinct,
        "inMoreThanOneCategory": sum(1 for v in seen_in.values() if len(v) > 1),
        "sumOfReported": sum(c["reported"] for c in categories.values()),
    }
    if combined is not None:
        rows, reported = combined
        ids = {row.get("externalId") for row in rows}
        out["combined"] = {
            "reported": reported, "read": len(rows), "readMatchesReported": len(rows) == reported,
            "sameAdsAsTheCategoriesTogether": ids == set(seen_in),
            "onlyInCombined": len(ids - set(seen_in)), "onlyInCategories": len(set(seen_in) - ids),
        }
    return out
