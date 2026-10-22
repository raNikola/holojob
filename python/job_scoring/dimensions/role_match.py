"""Role match dimension.

Matching is by contiguous substring, not by token subset. "product manager"
is not inside "Product Compliance Manager", which is the desired answer --
token subsets scored that title as a perfect match, and a single shared
generic word like "lead" was enough to pass the old 50% overlap threshold.
"""

from __future__ import annotations

from text_utils import normalize_text, tokenize

SENIORITY_NOUNS = frozenset({"manager", "owner", "lead", "head"})


def score_role_match(job: dict, intelligence: dict) -> tuple[int, list[str]]:
    role_strategy = intelligence.get("roleStrategy") or {}
    primary = [r.lower() for r in role_strategy.get("primaryTargetRoles") or []]
    secondary = [r.lower() for r in role_strategy.get("secondaryTargetRoles") or []]
    avoid = [r.lower() for r in role_strategy.get("avoidRoles") or []]
    variants = [r.lower() for r in role_strategy.get("searchRoleVariants") or []]

    title = normalize_text(job.get("title") or "")
    title_tokens = tokenize(title)

    for role in avoid:
        if role and role in title:
            return 15, [f"Avoid role match: {role}"]

    for role in primary:
        if role and role in title:
            return 95, [f"Primary role match: {role}"]

    for role in secondary + variants:
        if role and role in title:
            return 80, [f"Related role match: {role}"]

    # Product roles phrased outside the target list, such as
    # "Manager, Product Platform" or "Product Compliance Manager".
    if "product" in title_tokens and title_tokens & SENIORITY_NOUNS:
        return 65, ["Product role, wording outside target list"]

    if title_tokens:
        return 45, ["Title does not match target roles"]
    return 30, ["Missing job title"]