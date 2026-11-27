"""Labels and repost count worked out on read (list-cleanup 2a, 2b). What would hurt: a label read from the scraped text when the owner pasted
a better one, a label or count that is stored or that changes the ad, an owner-only field read, a setting that does not reach the counter.
Every path is under tmp_path."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "job_scoring"))

import job_derived as jd  # noqa: E402

SCRAPED = "Product Manager. Full-time. Fluent German required."
PASTED = "Product Manager. At least 6 years of experience. No visa sponsorship."


@pytest.fixture(autouse=True)
def sources_follow_the_root(monkeypatch):
    for var in ("HOLOJOB_SOURCES", "HOLOJOB_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)


def stage(tmp_path, jobs, overlay=None, sources=None):
    data = tmp_path / "data"
    (data / "jobs").mkdir(parents=True)
    (data / "config").mkdir()
    ledger = {"jobs": {i: {"firstSeen": j.get("datePosted", "2026-01-01"), "job": {**j, "jobId": i}} for i, j in jobs.items()}}
    (data / "jobs" / "job_history.json").write_text(json.dumps(ledger))
    if overlay:
        (data / "jobs" / "pasted_descriptions.json").write_text(json.dumps({"ads": overlay}))
    if sources is not None:
        (data / "config" / "sources.json").write_text(json.dumps(sources))
    return tmp_path


def names(answer):
    return {label["label"] for label in answer["labels"]}


def test_labels_come_from_the_owners_text_when_there_is_one(tmp_path):
    job = {"title": "Product Manager", "company": "Acme", "jobUrl": "https://x.com/1", "description": SCRAPED}
    root = stage(tmp_path, {"a1": job}, overlay={"a1": {"text": PASTED, "pastedAt": "2026-11-20"}})
    answer = jd.derived(root, "a1")
    assert names(answer) == {"years:6", "visa:no_sponsorship"} and answer["labelsFrom"] == "pasted"
    assert json.loads((root / "data/jobs/job_history.json").read_text())["jobs"]["a1"]["job"]["description"] == SCRAPED  # nothing written back


def test_without_an_overlay_the_scraped_text_is_read(tmp_path):
    root = stage(tmp_path, {"a1": {"title": "PM", "company": "Acme", "jobUrl": "https://x.com/1", "description": SCRAPED}})
    answer = jd.derived(root, "a1")
    assert names(answer) == {"employment:full_time", "language:german"} and answer["labelsFrom"] == "scraped"


def test_a_hand_entered_job_is_never_overlaid_and_its_notes_are_never_read():
    job = {"jobId": "manual-1", "manualEntry": True, "description": SCRAPED, "notes": "On-site only, no visa sponsorship"}
    labels, source = jd.labels_of(job, {"manual-1": {"text": PASTED}})
    assert {x["label"] for x in labels} == {"employment:full_time", "language:german"} and source == "scraped"


def test_an_unknown_ad_answers_empty_not_an_error(tmp_path):
    answer = jd.derived(stage(tmp_path, {}), "nope")
    assert answer["ok"] and answer["labels"] == [] and answer["repostCount"] == 0


def posting(url, day):
    return {"title": "Senior Product Manager", "company": "Acme d.o.o.", "jobUrl": url, "datePosted": day, "description": ""}


def test_repost_count_is_the_other_postings_and_the_window_is_the_setting(tmp_path):
    jobs = {"a": posting("https://x.com/1", "2026-01-01"), "b": posting("https://x.com/2", "2026-03-01")}
    far = stage(tmp_path / "far", jobs, sources={"version": 1, "boards": {}, "migrations": {}, "repostWindowDays": 30})
    assert jd.repost_window_days(far) == 30 and jd.derived(far, "a")["repostCount"] == 0
    wide = stage(tmp_path / "wide", jobs, sources={"version": 1, "boards": {}, "migrations": {}, "repostWindowDays": 120})
    assert jd.repost_window_days(wide) == 120 and jd.derived(wide, "a")["repostCount"] == 1 == jd.derived(wide, "b")["repostCount"]


def test_a_missing_or_damaged_window_gives_the_default(tmp_path):
    assert jd.repost_window_days(stage(tmp_path / "none", {})) == 90
    assert jd.repost_window_days(stage(tmp_path / "bad", {}, sources={"repostWindowDays": "x"})) == 90
