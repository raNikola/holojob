"""Wave 1 discovery safety: an incomplete read never proves an ad disappeared. Offline; every path is under tmp_path."""

import json

import pandas as pd
import pytest
import requests

import jobspy_adapter
import run_discovery
from providers import greenhouse_provider, jobspy_provider, lever_provider
from providers.base_provider import ProviderOutcome, classify_read, parts_outcome
from test_snapshot_closing import Answer, Board, discover, posting
from view_guard import derive_view


def ledger_of(root):
    return json.loads((root / "data/jobs/job_history.json").read_text())


def greenhouse(monkeypatch, boards):
    provider = greenhouse_provider.GreenhouseProvider()
    monkeypatch.setattr(provider, "_load_boards", lambda: [{"company": b, "board": b} for b in boards])
    return provider


class Boards:
    """Answers of several Greenhouse boards: a list of postings, 'fail' (HTTP 500), 429 or an empty list."""

    def __init__(self):
        self.state = {}

    def get(self, url, **_):
        name = url.split("/boards/")[1].split("/")[0]
        mode = self.state[name]
        if mode in (429, 500, 403):
            return Answer({}, mode)
        return Answer({"jobs": mode, "meta": {"total": len(mode)}})


def step(root, monkeypatch, boards, names, expect=0):
    monkeypatch.setattr(requests, "get", boards.get)
    assert discover(root, monkeypatch, {"greenhouse": greenhouse(monkeypatch, names)}) == expect
    return ledger_of(root)


def titles(ledger):
    return {e["job"]["title"]: e for e in ledger["jobs"].values()}


def test_read_classes():
    assert classify_read(ProviderOutcome(status="ok", read=3)) == "ok"
    assert classify_read(ProviderOutcome(status="ok", read=0)) == "incomplete", "ok with nothing read proves nothing"
    assert classify_read(ProviderOutcome(status="partial", read=3)) == "incomplete"
    assert classify_read(ProviderOutcome(status="failed")) == "failed"
    assert classify_read(ProviderOutcome(status="skipped")) == "skipped"
    assert parts_outcome(read=0, kept=0, total=2, failures={}).read_class == "confirmed_empty"
    assert parts_outcome(read=0, kept=0, total=2, failures={"a": "429"}).read_class == "incomplete"
    assert parts_outcome(read=0, kept=0, total=1, failures={"a": "429"}).read_class == "failed"


@pytest.mark.parametrize("code", [429, 403, 500])
def test_a_throttled_source_with_no_ads_closes_nothing(tmp_path, monkeypatch, code):
    root = tmp_path / "root"
    root.mkdir()
    boards = Boards()
    boards.state = {"acme": [posting(1), posting(2)], "beta": [posting(3)]}
    step(root, monkeypatch, boards, ["acme", "beta"])
    # acme is throttled for three runs in a row while beta answers: acme's ads are neither missed nor closed.
    boards.state = {"acme": code, "beta": [posting(3)]}
    for _ in range(3):
        ledger = step(root, monkeypatch, boards, ["acme", "beta"])
    assert all(not e["closedAt"] and not e.get("absentRuns") for e in ledger["jobs"].values())
    view = json.loads((root / "data/jobs/discovered_jobs.json").read_text())
    assert len(view["jobs"]) == 3 and not any(j.get("isClosed") or j.get("isAbsent") for j in view["jobs"])


def test_the_only_source_throttled_changes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    boards = Boards()
    boards.state = {"acme": [posting(1)]}
    step(root, monkeypatch, boards, ["acme"])
    before = (root / "data/jobs/job_history.json").read_bytes()
    boards.state = {"acme": 429}
    step(root, monkeypatch, boards, ["acme"], expect=1)
    assert (root / "data/jobs/job_history.json").read_bytes() == before


def test_a_confirmed_empty_board_is_classified_but_held_and_a_complete_board_still_closes(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    boards = Boards()
    boards.state = {"acme": [posting(1), posting(2)], "beta": [posting(3)]}
    step(root, monkeypatch, boards, ["acme", "beta"])
    # acme answers 200 with no ads at all: confirmed empty, so held. beta drops ad 3 twice: a complete read, so it closes.
    boards.state = {"acme": [], "beta": []}
    boards.state["beta"] = [posting(4)]
    for _ in range(2):
        ledger = step(root, monkeypatch, boards, ["acme", "beta"])
    by_title = titles(ledger)
    assert by_title["Product Manager 3"]["closedAt"], "a complete read of beta that lacks the ad twice closes it"
    assert not by_title["Product Manager 1"]["closedAt"] and not by_title["Product Manager 2"]["closedAt"], "an empty board is held"
    record = next(iter(sorted((root / "data/analytics/runs").glob("*.json"))), None) if (root / "data/analytics/runs").exists() else None
    if record is not None:
        data = json.loads(record.read_text())
        assert all(s["readClass"] in ("ok", "confirmed_empty", "incomplete", "failed", "skipped") for s in data["sources"])


def test_a_board_whose_own_read_class_is_not_ok_never_counts_even_if_it_claims_complete(tmp_path):
    from test_snapshot_closing import ad, evidence_of, proof, staged
    for read_class in ("incomplete", "failed", "confirmed_empty"):
        (tmp_path / read_class).mkdir()
        run = staged(tmp_path / read_class, {"acme": ([ad(1)], [], proof("acme", 1, readClass=read_class))})
        assert evidence_of(run)["acme"]["complete"] is False


def test_mixed_run_one_source_fails_and_the_others_import_normally(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    boards = Boards()
    boards.state = {"acme": [posting(1)], "beta": [posting(2)]}
    step(root, monkeypatch, boards, ["acme", "beta"])
    boards.state = {"acme": 429, "beta": [posting(2), posting(5)]}
    ledger = step(root, monkeypatch, boards, ["acme", "beta"])
    by_title = titles(ledger)
    assert "Product Manager 5" in by_title, "beta's new ad imported although acme failed"
    assert not by_title["Product Manager 1"]["closedAt"] and not by_title["Product Manager 1"].get("absentRuns")
    view = json.loads((root / "data/jobs/discovered_jobs.json").read_text())
    assert derive_view(ledger) == view


def test_a_partial_sole_source_imports_its_good_board(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    boards = Boards()
    boards.state = {"acme": [posting(1)], "beta": [posting(2)]}
    step(root, monkeypatch, boards, ["acme", "beta"])
    boards.state = {"acme": 500, "beta": [posting(2), posting(6)]}
    ledger = step(root, monkeypatch, boards, ["acme", "beta"])
    assert "Product Manager 6" in titles(ledger) and ledger["generation"] == 2


# --- JobSpy: a swallowed error is not "0 ads" ---------------------------------------------------------------------------


def frame_with(failed, rows=()):
    df = pd.DataFrame(list(rows))
    df.attrs["sitesFailed"] = list(failed)
    return df


def test_jobspy_adapter_marks_sites_that_raised(monkeypatch):
    def scrape(sites, *a, **k):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(jobspy_adapter, "_scrape", scrape)
    df = jobspy_adapter.fetch_jobs("pm", "Remote", remote=True, country="Serbia")
    assert df.empty and df.attrs["sitesFailed"], "the caller can tell a blocked search from an empty one"


def test_jobspy_adapter_keeps_ads_of_the_site_that_answered(monkeypatch):
    good = pd.DataFrame([{"title": "Product Manager", "company": "Co", "job_url": "https://x.example/1", "site": "indeed"}])

    def scrape(sites, *a, **k):
        if len(sites) > 1 or sites[0] == "glassdoor":
            raise RuntimeError("blocked")
        return good

    monkeypatch.setattr(jobspy_adapter, "_scrape", scrape)
    monkeypatch.setattr(jobspy_adapter, "_sites_for_country", lambda c: ["indeed", "glassdoor"])
    df = jobspy_adapter.fetch_jobs("pm", "Remote", remote=True, country="Serbia")
    assert len(df) == 1 and df.attrs["sitesFailed"] == ["glassdoor"]


def test_jobspy_provider_reports_a_blocked_search_as_failed_not_as_zero_ads(monkeypatch):
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda *a, **k: frame_with(["indeed", "glassdoor"]))
    provider = jobspy_provider.JobSpyProvider()
    assert provider.fetch_jobs(["pm"], ["Remote"], [], "Serbia") == []
    outcome = provider.last_outcome
    assert outcome.status == "failed" and outcome.read_class == "failed" and outcome.read == 0 and "could not be read" in outcome.error


def test_jobspy_provider_a_search_that_really_returned_nothing_is_not_an_error(monkeypatch):
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda *a, **k: frame_with([]))
    provider = jobspy_provider.JobSpyProvider()
    provider.fetch_jobs(["pm"], ["Remote"], [], "Serbia")
    assert provider.last_outcome.status == "ok" and provider.last_outcome.error is None
