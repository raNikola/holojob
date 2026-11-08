"""The apply-by date: from the board, or from an unmistakable sentence in the ad. Never a guess, never a score."""

import pytest

from deadline import date_in_text, deadline_metadata
from scorer import score_job


@pytest.mark.parametrize(
    "text, expected",
    [
        ("The application window is expected to close on: 11/05/2026 This is", "2026-11-05"),
        ("The application window is expected to close on: 12/10/2026", "2026-12-10"),
        ("**Application Window closes 10/24/2026** **Pay", "2026-10-24"),
        ("****👉 Application deadline: November 8th, 2026.****", "2026-11-08"),
        ("We accept applications until November 6th 2026.", "2026-11-06"),
        ("The expected application deadline for this job is October 31, 2026.", "2026-10-31"),
        ("Application deadline: 16 November 2026. Questions", "2026-11-16"),
        ("Rok za prijavu je 15.11.2026. godine", "2026-11-15"),
        ("Prijave do 15. 11. 2026.", "2026-11-15"),
        ("<p>Closing date: <b>Dec 1, 2026</b></p>", "2026-12-01"),
        ("Closing date: Dec 1, 2026", "2026-12-01"),
        ("Apply by 25/11/2026", "2026-11-25"),
    ],
)
def test_a_stated_deadline(text, expected):
    assert date_in_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Apply by 03/04/2026",
        "Application deadline: soon",
        "Founded on November 8, 2026 and growing",
        "Application deadline: February 31, 2026",
        "Apply by email to us. November 8, 2026",
        "",
        None,
    ],
)
def test_no_date_is_guessed(text):
    assert date_in_text(text) is None


def test_the_board_date_comes_first():
    job = {"expiresAt": "2026-11-11", "description": "Application deadline: 16 November 2026."}
    assert deadline_metadata(job) == {"applyDeadline": "2026-11-11", "applyDeadlineSource": "board"}


def test_the_text_is_read_when_the_board_says_nothing():
    assert deadline_metadata({"expiresAt": "", "description": "Application deadline: 16 November 2026."}) == {"applyDeadline": "2026-11-16", "applyDeadlineSource": "ad_text"}


def test_nothing_known():
    assert deadline_metadata({"description": "A nice job"}) == {"applyDeadline": None, "applyDeadlineSource": None}


def test_a_bad_board_date_is_not_used():
    assert deadline_metadata({"expiresAt": "soon"})["applyDeadlineSource"] is None


def test_the_deadline_moves_no_score():
    base = {"jobId": "d", "title": "Senior Product Manager", "company": "Acme", "description": "Roadmap work", "location": "Remote"}
    plain = score_job(base, {})
    dated = score_job({**base, "description": "Roadmap work Application deadline: 16 November 2026.", "expiresAt": ""}, {})
    assert (plain["applyDeadline"], dated["applyDeadline"]) == (None, "2026-11-16")
    assert plain["matchScore"] == dated["matchScore"] and plain["hardCapped"] == dated["hardCapped"]
