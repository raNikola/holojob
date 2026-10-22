"""priority() must stay in step with apply_recommendation()."""

import pytest

from labels import apply_recommendation, match_label, priority


@pytest.mark.parametrize(
    "score, expected",
    [(100, "P1"), (85, "P1"), (70, "P1"), (69, "P2"), (55, "P2"), (54, "P3"), (40, "P3"), (39, "Reject")],
)
def test_priority_bands(score, expected):
    assert priority(score, apply_recommendation(score, []), []) == expected


def test_p1_is_exactly_the_apply_band():
    for score in range(0, 101):
        rec = apply_recommendation(score, [])
        assert (priority(score, rec, []) == "P1") == (rec == "Apply")


def test_avoided_role_is_rejected_whatever_the_score():
    flags = ["Avoid role match: project manager"]
    assert priority(90, apply_recommendation(90, flags), flags) == "Reject"


def test_excellent_label_is_still_distinct_from_p1():
    assert match_label(85) == "Excellent"
    assert match_label(84) == "Strong"
