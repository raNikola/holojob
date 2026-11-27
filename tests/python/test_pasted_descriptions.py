"""Paste box for discovered ads (package 12): the pasted text is private, overrides a thin scrape for scoring, and never touches a hand-entered job."""

import stat

import pytest

import pasted_descriptions as pd

TEXT = "Own the roadmap and the delivery of the platform for our customers. " * 3


def test_a_paste_is_stored_private_and_overlaid_on_its_ad_only(tmp_path):
    path = tmp_path / "jobs" / "pasted_descriptions.json"
    pd.put("j1", TEXT, path, now="2026-11-27T10:00:00+00:00")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    rows = [
        {"jobId": "j1", "description": "", "title": "PM"},
        {"jobId": "j2", "description": "scraped"},
        {"jobId": "j1", "manualEntry": True, "description": "typed by hand"},
    ]
    assert pd.apply(rows, path) == 1
    assert rows[0]["description"] == TEXT.strip() and rows[0]["descriptionStatus"] == "complete" and rows[0]["descriptionSource"] == "pasted"
    assert rows[1]["description"] == "scraped" and rows[2]["description"] == "typed by hand"


def test_a_bad_paste_is_refused_without_quoting_the_text(tmp_path):
    path = tmp_path / "p.json"
    for bad, field in (("too short", "text_too_short"), (None, "text"), ("x" * (pd.MAX_TEXT + 1), "text_too_long")):
        with pytest.raises(pd.InvalidPaste) as caught:
            pd.put("j1", bad, path)
        assert caught.value.field == field and str(caught.value) == field
    with pytest.raises(pd.InvalidPaste):
        pd.put("../x", TEXT, path)
    assert not path.exists()


def test_remove_forgets_the_paste_and_a_missing_file_is_empty(tmp_path):
    path = tmp_path / "p.json"
    assert pd.load(path) == {} and pd.apply([{"jobId": "j1", "description": ""}], path) == 0
    pd.put("j1", TEXT, path)
    assert pd.remove("j1", path) is True and pd.remove("j1", path) is False and pd.load(path) == {}
