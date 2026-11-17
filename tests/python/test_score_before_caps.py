"""scoreBeforeCaps: the score with no cap applied, kept only to break ties in the Jobs list (owner decision 2026-11-14)."""

import json
from pathlib import Path

import pytest

import scorer
import work_authorization as wa
from scorer import NO_PROFILE_STACK_CAP, OFF_TRACK_CAP, UNRELATED_TITLE_CAP, score_job

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BODY = ("Own the product roadmap and discovery for our platform. You will work with the team on what customers "
        "need and we will ship it with you. " * 8)


@pytest.fixture
def intelligence():
    data = json.loads((FIXTURES / "candidate-intelligence.json").read_text("utf-8"))
    data["languages"] = ["Serbian (native)", "English (fluent)"]
    return data


@pytest.fixture
def job():
    return {"jobId": "j1", "title": "Product Manager", "company": "Acme", "location": "Niš, Serbia", "workMode": "remote",
            "description": BODY, "jobUrl": "https://example.com/j", "llmFacts": {"roleTrack": "product_management"}}


def force(monkeypatch, *, flags=False, title=None, track=False, visa=None, language=False):
    """Switch exactly the named cap detectors on; the dimension scores stay the real ones."""
    monkeypatch.setattr(scorer, "detect_red_flags", lambda j, i: ["flag"] if flags else [])
    monkeypatch.setattr(scorer, "title_tier", lambda *a, **k: scorer.UNRELATED if title else "target")
    monkeypatch.setattr(scorer, "track_has_evidence", lambda f: bool(track))
    if track:
        monkeypatch.setattr(scorer, "accepted_tracks", lambda i: ("product", {"some_other_track"}))
    status = {"status": visa or wa.AUTHORIZED, "reason": "r", "location": {}}
    monkeypatch.setattr(wa, "authorization_status", lambda j, p: status)
    monkeypatch.setattr(scorer, "language_gap_names", lambda j, i: ["Russian"] if language else [])


def test_an_uncapped_row_has_scoreBeforeCaps_equal_to_matchScore(intelligence, job, monkeypatch):
    force(monkeypatch)
    r = score_job(job, intelligence)
    assert r["scoreBeforeCaps"] == r["matchScore"]


def test_the_real_pipeline_without_a_cap_trigger_matches_too(intelligence, job):
    r = score_job(job, intelligence)
    if not any(x.startswith(("Capped:", "Red flag")) for x in r["reasons"]):
        assert r["scoreBeforeCaps"] == r["matchScore"]


CAP_CASES = [
    ("title 40", dict(title=True), UNRELATED_TITLE_CAP),
    ("track 50", dict(track=True), OFF_TRACK_CAP),
    ("red flag 54", dict(flags=True), 54),
]


@pytest.mark.parametrize("name,kw,cap", CAP_CASES, ids=[c[0] for c in CAP_CASES])
def test_each_cap_lowers_matchScore_but_keeps_the_pre_cap_score(intelligence, job, monkeypatch, name, kw, cap):
    force(monkeypatch)
    free = score_job(job, intelligence)["matchScore"]
    assert free > cap, "the fixture must score above the cap for the test to mean anything"
    force(monkeypatch, **kw)
    r = score_job(job, intelligence)
    assert r["matchScore"] == cap
    assert r["scoreBeforeCaps"] == free


def test_several_caps_keep_the_highest_uncapped_value(intelligence, job, monkeypatch):
    force(monkeypatch)
    free = score_job(job, intelligence)["matchScore"]
    force(monkeypatch, flags=True, title=True, track=True)
    r = score_job(job, intelligence)
    assert r["matchScore"] == UNRELATED_TITLE_CAP and r["scoreBeforeCaps"] == free


@pytest.mark.parametrize("visa", [wa.NEEDS_VISA_REFUSED, wa.OUTSIDE_ALLOWED, wa.NEEDS_VISA_SILENT])
def test_visa_status_and_language_gap_no_longer_lower_the_score(intelligence, job, monkeypatch, visa):
    """scoringVersion 1.5: the same facts are states beside the score, never inside it."""
    force(monkeypatch)
    free = score_job(job, intelligence)["matchScore"]
    force(monkeypatch, visa=visa, language=True)
    r = score_job(job, intelligence)
    assert r["matchScore"] == free == r["scoreBeforeCaps"] and r["languageGap"] == ["Russian"]
    assert r["hardCapped"] is False


def test_caps_do_not_change_matchScore_label_or_priority(intelligence, job, monkeypatch):
    """The new field is read by nothing in the score: label and priority are those of matchScore alone."""
    force(monkeypatch, flags=True)
    r = score_job(job, intelligence)
    assert r["matchLabel"] == scorer.match_label(r["matchScore"])


def test_a_not_read_ad_has_no_score_and_no_pre_cap_score(intelligence, job, monkeypatch):
    force(monkeypatch)
    r = score_job({**job, "description": "", "llmFacts": None}, intelligence)
    assert r["matchScore"] is None and r["scoreBeforeCaps"] is None
    assert r["readStatus"] == "not_read" and r["dataStatus"] == "not_read" and r["matchLabel"] == "Not read"


def test_a_profile_with_no_skill_stack_gets_no_score_above_50_and_a_marker(intelligence, job, monkeypatch):
    force(monkeypatch)
    blank = {k: v for k, v in intelligence.items() if k not in ("atsKeywordBank", "skillsMap")}
    r = score_job(job, blank)
    assert r["matchScore"] <= NO_PROFILE_STACK_CAP and r["profileGuard"] == "no_profile_stack" and r["hardCapped"] is True
    assert any("no profile stack" in x for x in r["reasons"])
    assert score_job(job, intelligence)["profileGuard"] is None
