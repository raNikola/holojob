"""For a candidate who will not leave Nis, onsite elsewhere is unusable."""

import json
from pathlib import Path

import pytest

from dimensions.location_match import score_location_match

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def intelligence():
    return json.loads((FIXTURES / "candidate-intelligence.json").read_text("utf-8"))


def _score(job, intelligence):
    return score_location_match(job, intelligence)[0]


def test_confirmed_onsite_outside_nis_scores_far_below_remote(intelligence):
    onsite = _score({"location": "Belgrade, Serbia", "workMode": "onsite"}, intelligence)
    remote = _score({"location": "Serbia", "workMode": "remote"}, intelligence)
    assert remote - onsite >= 60


def test_board_workmode_remote_beats_unset_is_remote_flag(intelligence):
    # LinkedIn leaves isRemote unset; the mode the LLM read out of the ad counts.
    job = {"location": "Serbia", "isRemote": False, "llmFacts": {"workMode": "remote"}}
    assert _score(job, intelligence) >= 85


def test_onsite_in_nis_matches_with_or_without_diacritic(intelligence):
    with_mark = _score({"location": "Niš, Serbia", "workMode": "onsite"}, intelligence)
    without = _score({"location": "Nis, Serbia", "workMode": "onsite"}, intelligence)
    assert with_mark == without == 90


def test_serbia_alone_must_not_count_as_a_preferred_place(intelligence):
    assert _score({"location": "Belgrade, Serbia", "workMode": "onsite"}, intelligence) == 15


def test_unknown_mode_orders_city_below_country_below_remote(intelligence):
    unknown = {"llmFacts": {"workMode": "unclear"}, "isRemote": False}
    city = _score({**unknown, "location": "Belgrade, Serbia"}, intelligence)
    country = _score({**unknown, "location": "Serbia"}, intelligence)
    remote = _score({"location": "Serbia", "workMode": "remote"}, intelligence)
    assert city < country < remote
