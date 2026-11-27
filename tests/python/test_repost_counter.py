"""Repost counter (package 7): the six rules must ALL hold, and the loser URL of a crosspost is kept."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "python"
sys.path.insert(0, str(ROOT / "job_scoring"))
sys.path.insert(0, str(ROOT / "job_discovery"))

import repost_counter as rc  # noqa: E402
import dedupe_jobs  # noqa: E402
import source_settings  # noqa: E402


def ad(url, day, title="Senior Product Manager", company="Acme d.o.o.", description=""):
    return {"firstSeen": day, "job": {"title": title, "company": company, "jobUrl": url, "datePosted": day, "description": description}}


def groups(entries, **kw):
    return rc.count_reposts(entries, **kw)["groups"]


def test_all_rules_hold_for_a_repost():
    found = groups({"a": ad("https://x.com/1", "2026-01-01"), "b": ad("https://www.x.com/2", "2026-02-01", title="Product Manager Senior", company="ACME")})
    assert len(found) == 1 and found[0]["ids"] == ["a", "b"]
    assert rc.count_reposts({"a": ad("https://x.com/1", "2026-01-01"), "b": ad("https://x.com/2", "2026-02-01")})["repostsOf"] == {"a": 1, "b": 1}


def test_any_single_broken_rule_gives_no_group():
    base = ad("https://x.com/1", "2026-01-01")
    for other in (
        ad("https://x.com/2", "2026-01-01"),                        # one date only
        ad("https://x.com/1", "2026-02-01"),                        # same URL
        ad("https://y.com/2", "2026-02-01"),                        # other host
        ad("https://x.com/2", "2026-06-01"),                        # outside 90 days
        ad("https://x.com/2", "2026-02-01", company="Other Ltd"),   # other company
        ad("https://x.com/2", "2026-02-01", title="Product Owner"),  # other title words
        ad("", "2026-02-01"),                                       # no URL
        {"job": {"title": "Senior Product Manager", "company": "Acme", "jobUrl": "https://x.com/3"}},  # no date
    ):
        assert groups({"a": base, "b": other}) == [], other


def test_window_comes_from_settings_with_a_default():
    assert source_settings.repost_window({}) == 90 and source_settings.repost_window({"repostWindowDays": 30}) == 30
    assert source_settings.repost_window({"repostWindowDays": 0}) == 90 and source_settings.repost_window({"repostWindowDays": True}) == 90
    pair = {"a": ad("https://x.com/1", "2026-01-01"), "b": ad("https://x.com/2", "2026-02-15")}
    assert groups(pair, window_days=30) == [] and len(groups(pair, window_days=60)) == 1


def test_simhash_is_a_note_only():
    text = " ".join(f"word{i % 37}" for i in range(120))
    entries = {"a": ad("https://x.com/1", "2026-01-01", description=text), "b": ad("https://y.com/2", "2026-01-02", description=text)}
    result = rc.count_reposts(entries, with_similar=True)
    assert result["similarText"] == [["a", "b"]] and result["groups"] == [] and result["repostsOf"] == {}
    short = {k: ad(f"https://x.com/{k}", "2026-01-01", description="short") for k in "ab"}
    assert rc.count_reposts(short, with_similar=True)["similarText"] == []


def test_crosspost_loser_url_is_kept_and_nothing_else_of_it():
    rich = {"jobId": "1", "title": "PM", "company": "Acme", "jobUrl": "https://a.com/1", "description": "long text " * 20}
    poor = {"jobId": "2", "title": "PM", "company": "Acme", "jobUrl": "https://b.com/2", "description": "", "salary": "secret"}
    out = dedupe_jobs.dedupe_jobs([poor, rich])
    assert len(out) == 1 and out[0]["jobUrl"] == "https://a.com/1"
    assert out[0]["alsoListedAt"] == ["https://b.com/2"] and "salary" not in out[0]
