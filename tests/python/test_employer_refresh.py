"""Refresh from the employer page (package 13): the scraped original is never changed, a proposal is private and server-side only,
a hand-entered ad and an unreadable page are refused, and an accepted proposal becomes the overlay with source "employer"."""

import json
import stat
from types import SimpleNamespace

import employer_refresh as er
import pasted_descriptions as pd

ORIGINAL = "Great product role.\nWe offer a team."
PAGE_TEXT = "Great product role.\nOwn the roadmap and the delivery of the platform for customers.\nWe offer a team."
HTML = f'<html><script type="application/ld+json">{json.dumps({"@type": "JobPosting", "title": "PM", "description": PAGE_TEXT.replace(chr(10), "<br>")})}</script></html>'


def ledger(tmp_path, job):
    jobs = tmp_path / "discovered_jobs.json"
    (tmp_path / "job_history.json").write_text(json.dumps({"version": 1, "jobs": {"j1": {"job": job}}}))
    return jobs


def page(url="https://employer.example/jobs/1", html=HTML):
    return lambda _url: SimpleNamespace(url=url, html=html)


def test_proposal_is_private_diffed_and_leaves_the_ledger_alone(tmp_path):
    jobs = ledger(tmp_path, {"jobId": "j1", "description": ORIGINAL})
    before = (tmp_path / "job_history.json").read_text()
    path = tmp_path / "employer_refresh.json"
    code, body = er.propose("j1", "https://employer.example/jobs/1", jobs=jobs, path=path, fetch_page=page())
    assert code == 0 and body["ok"] and not body["identical"]
    ops = [d["op"] for d in body["diff"]]
    assert ops.count("add") == 1 and ops.count("del") == 0 and ops.count("same") == 2
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (tmp_path / "job_history.json").read_text() == before  # the original is kept
    assert er.proposal_text("j1", path) == PAGE_TEXT


def test_hand_entered_unknown_and_unreadable_are_refused_and_store_nothing(tmp_path):
    path = tmp_path / "p.json"
    jobs = ledger(tmp_path, {"jobId": "j1", "manualEntry": True, "description": ORIGINAL})
    assert er.propose("j1", "https://e.example/", jobs=jobs, path=path, fetch_page=page())[0] == 4
    assert er.propose("zz", "https://e.example/", jobs=jobs, path=path, fetch_page=page())[0] == 4
    assert er.propose("../x", "https://e.example/", jobs=jobs, path=path, fetch_page=page())[0] == 2
    jobs = ledger(tmp_path, {"jobId": "j1", "description": ORIGINAL})
    assert er.propose("j1", "https://e.example/", jobs=jobs, path=path, fetch_page=page(html="<html></html>"))[0] == 3
    assert not path.exists()


def test_discard_forgets_and_an_accepted_text_overlays_with_its_source(tmp_path):
    path = tmp_path / "p.json"
    jobs = ledger(tmp_path, {"jobId": "j1", "description": ORIGINAL})
    er.propose("j1", "https://e.example/", jobs=jobs, path=path, fetch_page=page())
    assert er.discard("j1", path) is True and er.proposal_text("j1", path) is None
    overlay = tmp_path / "pasted.json"
    pd.put("j1", PAGE_TEXT, overlay, source="employer")
    rows = [{"jobId": "j1", "description": ORIGINAL}]
    assert pd.apply(rows, overlay) == 1
    assert rows[0]["description"] == PAGE_TEXT and rows[0]["descriptionSource"] == "employer"
