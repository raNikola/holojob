"""Retry of empty descriptions (package 6): per ledger ad, 1 per scan, a total from Settings, never an expiry."""

import json
from datetime import datetime, timedelta, timezone

import pytest

import job_history as jh
import source_settings
from dedupe_jobs import _crosspost_key
from providers import joberty_provider

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
FULL = "Own the roadmap and the delivery of the platform. " * 8


def ad(description="", job_id="j1"):
    return {"jobId": job_id, "provider": "jobspy", "title": "Product Manager", "company": "Acme",
            "location": "Berlin", "description": description, "jobUrl": f"https://x/{job_id}"}


def scan(ledger, jobs, day, retry_max=2):
    _, stats = jh.apply_run(ledger, jobs, now=(T0 + timedelta(days=day)).isoformat(), providers_returned={"jobspy": len(jobs)},
                            key="k", role_key=_crosspost_key, retry_max=retry_max)
    return stats


def test_an_empty_ad_is_retried_once_per_scan_and_gives_up_after_the_total():
    ledger = jh.empty_ledger()
    first = scan(ledger, [ad()], 0)
    assert (first["descriptionEmptyNew"], first["descriptionRetried"]) == (1, 0)
    second = scan(ledger, [ad()], 1)
    third = scan(ledger, [ad()], 2)
    fourth = scan(ledger, [ad()], 3)
    assert (second["descriptionRetried"], second["descriptionGaveUp"]) == (1, 0)
    assert (third["descriptionRetried"], third["descriptionGaveUp"]) == (1, 1)
    assert (fourth["descriptionRetried"], fourth["descriptionGaveUp"]) == (0, 0)  # counted once, no third retry
    entry = ledger["jobs"]["j1"]
    assert entry["descriptionRetries"] == 2 and entry["descriptionGaveUp"] is True


def test_an_empty_description_never_closes_or_hides_the_ad():
    ledger = jh.empty_ledger()
    for day in range(5):
        written, _ = jh.apply_run(ledger, [ad()], now=(T0 + timedelta(days=day)).isoformat(), providers_returned={"jobspy": 1},
                                  key="k", role_key=_crosspost_key, retry_max=2)
        assert [row["jobId"] for row in written] == ["j1"] and not written[0]["isClosed"]
    assert not ledger["jobs"]["j1"].get("closedAt")


def test_a_full_description_clears_the_count_and_is_reported_recovered():
    ledger = jh.empty_ledger()
    scan(ledger, [ad()], 0)
    scan(ledger, [ad()], 1)
    stats = scan(ledger, [ad(FULL)], 2)
    assert stats["descriptionRecovered"] == 1
    assert "descriptionRetries" not in ledger["jobs"]["j1"] and "descriptionGaveUp" not in ledger["jobs"]["j1"]


def test_a_total_of_zero_turns_the_retry_off():
    ledger = jh.empty_ledger()
    scan(ledger, [ad()], 0, retry_max=0)
    stats = scan(ledger, [ad()], 1, retry_max=0)
    assert stats["descriptionRetried"] == 0 and ledger["jobs"]["j1"]["descriptionGaveUp"] is True


def test_joberty_does_not_ask_again_for_an_ad_that_gave_up(tmp_path):
    ledger = jh.empty_ledger()
    for day in range(3):
        scan(ledger, [ad()], day)
    ledger["jobs"]["j2"] = {"job": {"description": ""}}  # still has retries left
    path = tmp_path / "job_history.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    assert joberty_provider.known_ids(path) == {"j1"}


def test_the_total_comes_from_settings_with_a_default_and_is_validated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLOJOB_SOURCES", str(tmp_path / "sources.json"))
    assert source_settings.description_retry(source_settings.read()) == 2
    assert source_settings.save(None, retry={"maxTotal": 4})["ok"] is True
    assert source_settings.description_retry(source_settings.read()) == 4
    for bad in ({"maxTotal": -1}, {"maxTotal": 99}, {"maxTotal": "3"}, {"maxTotal": True}, {}):
        assert source_settings.save(None, retry=bad)["ok"] is False
    assert source_settings.description_retry(source_settings.read()) == 4
