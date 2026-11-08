"""Manual Re-score of kept ads (Wave 2 e): scored from the ledger, merged alone, pruned when Keep goes."""
import json
import os
from pathlib import Path

import pytest

import job_history
import kept_ads
import rescore_kept
import run_scoring
from row_state import in_idf_corpus

ROOT = Path(__file__).resolve().parents[2]
INTEL = json.loads((ROOT / "data/examples/candidate-intelligence.example.json").read_text(encoding="utf-8"))
AD = ("Own the product roadmap and discovery for a payments platform. You will work with engineering, design and "
      "stakeholders, define strategy and deliver measurable outcomes. Requirements: five years of product experience.")
KEPT = {"jobId": "kept1", "title": "Senior Product Manager", "company": "Gone Co", "location": "Remote", "isRemote": True,
        "description": AD, "jobUrl": "https://gone.example/1", "provider": "greenhouse"}
LISTED = {"jobId": "listed1", "title": "Product Owner", "company": "Acme", "location": "Remote", "isRemote": True,
          "description": AD, "jobUrl": "https://acme.example/1", "provider": "greenhouse"}


@pytest.fixture
def env(tmp_path):
    d = tmp_path / "jobs"
    d.mkdir()
    jobs = d / "discovered_jobs.json"
    jobs.write_text(json.dumps({"meta": {}, "jobs": [LISTED]}))
    ledger = job_history.empty_ledger()
    ledger["jobs"] = {"kept1": {"job": KEPT}, "listed1": {"job": LISTED}}
    job_history.ledger_path(jobs).write_text(json.dumps(ledger))
    (d / "scored_jobs.json").write_text(json.dumps({"meta": {}, "jobs": [{**LISTED, "matchScore": 50, "tailoredAssets": {"x": 1}}]}))
    intel = tmp_path / "intel.json"
    intel.write_text(json.dumps(INTEL))
    return dict(intelligence=intel, jobs=jobs, manual=d / "manual.json", scored=d / "scored_jobs.json", kept=d / "rescored_kept.json")


def test_a_kept_ad_is_scored_and_merged_without_touching_other_rows(env):
    code, body = rescore_kept.run("kept1", **env)
    assert code == 0 and body["job"]["jobId"] == "kept1" and isinstance(body["job"]["matchScore"], int)
    rows = {r["jobId"]: r for r in json.loads(env["scored"].read_text())["jobs"]}
    assert set(rows) == {"kept1", "listed1"}
    assert rows["listed1"]["matchScore"] == 50 and rows["listed1"]["tailoredAssets"] == {"x": 1}
    assert "kept1" in kept_ads.load(env["kept"])
    assert oct(env["kept"].stat().st_mode & 0o777) == "0o600"


def test_an_unknown_or_invalid_id_changes_nothing(env):
    assert rescore_kept.run("nope", **env)[0] == 4
    assert rescore_kept.run("../x", **env)[0] == 2
    assert not env["kept"].exists()


def test_a_run_is_refused_while_another_holds_the_lock(env):
    import pipeline_lock
    held = pipeline_lock.acquire()
    try:
        assert rescore_kept.run("kept1", **env)[0] == 75
    finally:
        held.release()
    assert not env["kept"].exists()


def test_the_registered_ad_stays_in_every_full_run_and_out_of_the_corpus(env):
    kept_ads.add("kept1", env["kept"])
    rows = kept_ads.with_kept([LISTED], job_history.ledger_path(env["jobs"]), env["kept"])
    assert [r["jobId"] for r in rows] == ["listed1", "kept1"]
    assert not in_idf_corpus(rows[1]) and in_idf_corpus(rows[0])
    # a row the list already holds is never duplicated
    assert kept_ads.with_kept([LISTED, KEPT], job_history.ledger_path(env["jobs"]), env["kept"]) == [LISTED, KEPT]


def test_listed_ads_score_the_same_with_a_registered_ad(env):
    from scorer import score_jobs
    alone = score_jobs([dict(LISTED)], INTEL)
    kept_ads.add("kept1", env["kept"])
    mixed = score_jobs(kept_ads.with_kept([dict(LISTED)], job_history.ledger_path(env["jobs"]), env["kept"]), INTEL)
    assert json.dumps(alone[0], sort_keys=True) == json.dumps(mixed[0], sort_keys=True)


def test_prune_drops_ids_that_are_no_longer_kept_and_have_no_application(env):
    for i in ("kept1", "listed1", "old"):
        kept_ads.add(i, env["kept"])
    dropped = kept_ads.prune({"kept1", "listed1"}, env["kept"])
    assert dropped == ["old"] and set(kept_ads.load(env["kept"])) == {"kept1", "listed1"}
    assert kept_ads.prune({"kept1"}, env["kept"]) == ["listed1"]
    assert kept_ads.prune({"kept1"}, env["kept"]) == []


def test_prune_never_touches_scored_rows(env):
    rescore_kept.run("kept1", **env)
    before = env["scored"].read_text()
    assert rescore_kept.main(["--prune", "", "--kept", str(env["kept"])]) == 0
    assert kept_ads.load(env["kept"]) == {} and env["scored"].read_text() == before
