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
    # Seniority is a label, never a drop (package 3, owner plan 2026-11-25).
    ("Junior Project Manager", "", (), N, None),
    ("Intern Product Manager", "Product Manager", (), T, None),
    ("Account Manager", "Product Manager", (), X, "title_excluded:account manager"),  # an excluded phrase beats a board's position
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


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_a_title_miss_with_an_empty_text_is_never_dropped(text):
    """Owner plan 2026-11-25: an empty description does not drop the ad; it continues as unknown."""
    decision = role_filter.assess("Chef", "", (), text)
    assert (decision.tier, decision.reason, decision.rule) == (N, None, role_filter.UNKNOWN)


def test_the_text_check_of_a_title_miss():
    soft = role_filter.assess("Implementation Lead", "", (), "You will act as the Product Owner of our platform.")
    assert (soft.tier, soft.reason, soft.rule) == (N, None, role_filter.SOFT)
    hard = role_filter.assess("Implementation Lead", "", (), "You will onboard customers and run rollouts.")
    assert (hard.tier, hard.reason, hard.rule) == (X, "title_not_matched", role_filter.HARD)
    near_only = role_filter.assess("Backend Engineer", "", (), "You report to the project manager.")
    assert near_only.reason == "title_not_matched", "a near phrase in body text does not let a title miss in"
    assert role_filter.assess("Chef", "", (), None).reason == "title_not_matched", "no text check at all: the title decides"
    excluded = role_filter.assess("Account Manager", "", (), "")
    assert (excluded.reason, excluded.rule) == ("title_excluded:account manager", role_filter.HARD), "an excluded title never waits for text"


def test_seniority_is_a_label_never_a_drop():
    for word in role_filter.SENIORITY_LABELS:
        decision = role_filter.assess(f"{word.title()} Product Manager")
        assert decision.reason is None and f"seniority:{word}" in decision.labels, word


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


def test_the_text_check_tally_counts_per_source_and_never_changes_a_decision():
    """The run summary's counter (2026-11-27): examined title misses, and the ones the text check kept that the title alone would drop."""
    cases = [
        ("Implementation Lead", "You will act as the Product Owner of our platform."),  # kept by a phrase in the text
        ("Implementation Lead", "You will onboard customers and run rollouts."),         # examined, dropped
        ("Implementation Lead", ""),                                                     # kept with no text
        ("Product Owner", "anything"),                                                   # a title match: never reaches the text check
        ("Account Manager", "Product Owner"),                                            # hard title drop: never reaches it either
        ("Chef", None),                                                                  # no text check at all: the title decides
    ]
    plain = [role_filter.role_drop_reason(title, "", (), text) for title, text in cases]
    role_filter.begin_text_check("a")
    counted = [role_filter.role_drop_reason(title, "", (), text) for title, text in cases]
    role_filter.begin_text_check(None)
    role_filter.role_drop_reason("Implementation Lead", "", (), "")  # no source: counts nothing
    assert counted == plain
    assert role_filter.text_check_counts("a") == {"examined": 3, "keptByText": 1, "keptNoText": 1}
    assert role_filter.text_check_counts("b") == {"examined": 0, "keptByText": 0, "keptNoText": 0}
