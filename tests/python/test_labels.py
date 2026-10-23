"""P1 is the apply-first subset of Apply; the bands never overlap or skip."""

import pytest

from labels import APPLY_MIN_SCORE, P1_MIN_SCORE, apply_recommendation, match_label, priority


@pytest.mark.parametrize(
    "score, expected",
    [(100, "P1"), (85, "P1"), (76, "P1"), (75, "P2"), (70, "P2"), (69, "P2"), (55, "P2"), (54, "P3"), (40, "P3"), (39, "Reject")],
)
def test_priority_bands(score, expected):
    assert priority(score, apply_recommendation(score, []), []) == expected


def test_p1_is_a_strict_subset_of_apply_and_not_all_of_it():
    p1 = {sc for sc in range(101) if priority(sc, apply_recommendation(sc, []), []) == "P1"}
    apply_band = {sc for sc in range(101) if apply_recommendation(sc, []) == "Apply"}
    assert p1 < apply_band
    assert min(p1) == P1_MIN_SCORE and min(apply_band) == APPLY_MIN_SCORE
    # Apply-level jobs below the P1 line are P2, so nothing falls between the tiers.
    assert all(priority(sc, "Apply", []) == "P2" for sc in range(APPLY_MIN_SCORE, P1_MIN_SCORE))


def test_avoided_role_is_rejected_whatever_the_score():
    flags = ["Avoid role match: project manager"]
    assert priority(90, apply_recommendation(90, flags), flags) == "Reject"


def test_excellent_label_is_still_distinct_from_p1():
    assert match_label(85) == "Excellent"
    assert match_label(84) == "Strong"
