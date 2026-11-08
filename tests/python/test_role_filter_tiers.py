"""The three-tier role filter (Wave 3): Target / Near / Excluded, consistent with the scoring tiers in role_tier.py."""

import json
import re
from pathlib import Path

import pytest

from providers import role_filter

from role_tier import ROLE_FAMILIES, title_tier

T, N, X = role_filter.TARGET, role_filter.NEAR, role_filter.EXCLUDED


@pytest.mark.parametrize("title,position,extra,tier,reason", [
    ("Senior Product Manager", "", (), T, None),
    ("Developer", "Product Manager", (), T, None),                      # a board's hand-assigned position
    ("Project Manager", "", (), N, None),                               # not rejected by name alone
    ("Delivery Manager", "", (), N, None),
    ("Programme Manager", "", (), N, None),
    ("Technical Project Manager", "", (), N, None),
    ("Projektni menadžer – rukovodilac projekta", "", (), N, None),     # Serbian, diacritics folded
    ("Developer", "IT Project Manager", (), N, None),                   # the board's position names a near role
    ("Junior Project Manager", "", (), X, "title_excluded:junior"),     # seniority beats everything
    ("Intern Product Manager", "Product Manager", (), X, "title_excluded:intern"),
    ("Account Manager", "", (), X, "title_excluded:account manager"),
    ("Chef", "", (), X, "title_not_matched"),
    ("Menadžer proizvodnje", "", (), X, "title_not_matched"),
    ("Technical Production Manager", "", (), X, "title_not_matched"),
    # A search term alone never makes a title Target: it passes discovery as Near and scoring decides.
    ("Growth Lead", "", ("growth",), N, None),
    ("Growth Lead", "", ("Product Manager",), X, "title_not_matched"),
    ("Product Manager", "", ("Growth",), T, None),
])
def test_tiers(title, position, extra, tier, reason):
    assert role_filter.role_tier(title, position, extra) == (tier, reason)


def test_an_extra_term_never_yields_target():
    for title in ("Growth Lead", "Chef", "Program Lead", "Delivery Lead"):
        for term in (title, title.split()[0], title.lower()):
            assert role_filter.role_tier(title, "", (term,))[0] != T


def test_only_excluded_is_dropped():
    for title in ("Product Manager", "Project Manager", "Chef", "Junior Project Manager"):
        tier, reason = role_filter.role_tier(title)
        assert role_filter.is_relevant_role(title) == (tier != X) and (reason is None) == (tier != X)


def test_near_list_agrees_with_the_scoring_vocabulary():
    """Every title the scoring vocabulary calls near (or product-responsibility) passes discovery."""
    rules = ROLE_FAMILIES["product"]["titleRules"]
    samples = {
        "program(me)? manag": ["Program Manager", "Programme Manager"],
        "product management": ["Product Management Lead"],
        "product operations": ["Product Operations Lead"],
        "product ops\\b": ["Product Ops Lead"],
        "\\btpm\\b": ["Senior TPM"],
        "project manag": ["Project Manager"],
        "delivery manag": ["Delivery Manager"],
    }
    patterns = rules["nearTitlePatterns"] + rules["productResponsibilityTitlePatterns"]
    for pattern, titles in samples.items():
        assert pattern in patterns, f"scoring vocabulary changed: {pattern}"
        for title in titles:
            assert re.search(pattern, title.lower()), (pattern, title)
            assert role_filter.role_tier(title)[0] in (T, N), title


def test_a_project_title_is_still_capped_by_scoring_without_product_evidence():
    """Discovery keeps it; scoring decides. project_delivery is not an accepted track."""
    assert "project_delivery" not in ROLE_FAMILIES["product"]["acceptedRoleTracks"]
    assert title_tier("Project Manager", 30, "product", {}) == "unrelated"
    facts = {"roleTrack": "product_ownership", "roleTrackEvidence": "owns the roadmap"}
    assert title_tier("Project Manager", 30, "product", facts) == "near"
