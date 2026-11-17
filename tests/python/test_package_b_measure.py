"""Package B measurement scripts (scripts/measure_*.py): read-only, no model call, nothing under data/ touched.

Every test builds its own temp data directory; none reads or writes /srv/holojob/data.
"""

import ast
import json
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure_baseline as mb  # noqa: E402
import measure_common as mc  # noqa: E402
import measure_extraction_variance as mv  # noqa: E402
import measure_gate_confusion as mg  # noqa: E402
import measure_rescore_impact as mi  # noqa: E402


# --- fixtures -------------------------------------------------------------------------------------------------------

def job(job_id, title="Product Manager", **extra):
    return {"jobId": job_id, "title": title, "company": "Acme", "location": "Niš, Serbia", "description": "Own the roadmap. " * 30,
            "jobUrl": f"https://jobs.example/{job_id}", "provider": "jobspy", "status": "new", **extra}


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "jobs").mkdir(parents=True)
    (d / "intelligence").mkdir()
    (d / "profile").mkdir()
    (d / "intelligence" / "candidate-intelligence.json").write_text(json.dumps({"jobFitPreferences": {}, "roleFamily": "product"}))
    (d / "profile" / "candidate-profile.json").write_text(json.dumps({}))
    (d / "jobs" / "discovered_jobs.json").write_text(json.dumps({"jobs": [job("a"), job("b", "Warehouse Operator")]}))
    return d


def row(**kw):
    base = {"jobId": "x", "matchScore": 60, "scoreBeforeCaps": 60, "matchLabel": "Good", "dataStatus": "sufficient", "redFlags": [],
            "reasons": [], "workAuthorization": {"status": "authorized", "basis": "ad_read"}}
    return {**base, **kw}


# --- cap derivation -------------------------------------------------------------------------------------------------

def test_the_cap_reason_prefixes_still_exist_in_the_scorer():
    source = (Path(mc.ROOT) / "python" / "job_scoring" / "scorer.py").read_text(encoding="utf-8")
    # LANGUAGE_PREFIX is a 1.4 reason, kept in measure_common only to read frozen snapshots; scoringVersion 1.5 has no language cap.
    for prefix in (mc.OFF_TRACK_PREFIX, mc.TITLE_PREFIX):
        assert f'f"{prefix}' in source or f'"{prefix}' in source, prefix


def test_caps_fired_versus_binding():
    # visa-silent cap 45 binds a 67 and not a 40 that the title cap already holds lower
    bound = row(matchScore=45, scoreBeforeCaps=67, workAuthorization={"status": "needs_visa_silent", "basis": "not_read"})
    assert mc.caps_of(bound) == ({"visa:needs_visa_silent"}, {"visa:needs_visa_silent"})
    both = row(matchScore=40, scoreBeforeCaps=67, workAuthorization={"status": "needs_visa_silent"}, reasons=[mc.TITLE_PREFIX + " target role"])
    fired, binding = mc.caps_of(both)
    assert fired == {"visa:needs_visa_silent", "unrelated_title"} and binding == {"unrelated_title"}
    assert mc.caps_of(row(redFlags=["x"], scoreBeforeCaps=55, matchScore=55))[0] == set()  # the red-flag cap only bites above 55
    assert mc.caps_of(row(redFlags=["x"], scoreBeforeCaps=70, matchScore=54)) == ({"red_flag"}, {"red_flag"})
    assert mc.caps_of(row(dataStatus="insufficient", matchScore=5, scoreBeforeCaps=5)) == ({"insufficient_data"}, {"insufficient_data"})


def test_baseline_snapshot_counts():
    rows = [row(jobId="1", matchScore=45, scoreBeforeCaps=67, workAuthorization={"status": "needs_visa_silent", "basis": "not_read"}),
            row(jobId="2", matchScore=45, scoreBeforeCaps=60, workAuthorization={"status": "needs_visa_silent", "basis": "ad_read"}),
            row(jobId="3", matchScore=5, scoreBeforeCaps=5, dataStatus="insufficient", matchLabel=mc.INSUFFICIENT),
            row(jobId="4", matchScore=80, scoreBeforeCaps=80, matchLabel="Strong")]
    s = mb.snapshot(rows, {"scoringVersion": "9.9"})
    assert s["adsTotal"] == 4 and s["adsByScoringVersion"] == {"9.9": 4} and s["ratedAds"] == 3
    assert s["notRead"] == 1 and s["insufficientData"] == 1 and s["silentVisa"] == {"total": 2, "byBasis": {"not_read": 1, "ad_read": 1}}
    assert s["largestTieGroups"][0] == {"score": 45, "count": 2}
    assert s["capsFired"]["visa:needs_visa_silent"] == 2 and s["capsBinding"]["visa:needs_visa_silent"] == 2
    assert s["extractionFacts"] == {"absent": 4}


def test_extraction_status_read_stale_absent():
    from job_fingerprint import job_fingerprint
    ad = job("r")
    assert mb.facts_state({**ad, "llmFacts": {"_fingerprint": job_fingerprint(ad)}}) == "read"
    assert mb.facts_state({**ad, "llmFacts": {"_fingerprint": "old"}}) == "stale"
    assert mb.facts_state(ad) == "absent"


# --- impact ---------------------------------------------------------------------------------------------------------

def test_impact_compare_lists_changed_ids():
    old = mc.snapshot_rows([row(jobId="a", matchScore=40, matchLabel="Weak"), row(jobId="b"), row(jobId="gone")])
    new = mc.snapshot_rows([row(jobId="a", matchScore=60, matchLabel="Good"), row(jobId="b"), row(jobId="fresh")])
    result = mi.compare(old, new)
    assert result["scoreChanged"] == ["a"] and result["bandChanged"] == ["a"] and result["compared"] == 2
    assert result["onlyInBaseline"] == ["gone"] and result["onlyInCurrent"] == ["fresh"]
    assert result["scoreDeltaCounts"] == {20: 1} and result["bandMoves"] == {"Weak -> Good": 1}


def test_a_rescore_of_the_same_tree_changes_nothing(data_dir):
    first = mc.rescore(data_dir)
    second = mc.rescore(data_dir)
    result = mi.compare(mc.snapshot_rows(first["jobs"]), mc.snapshot_rows(second["jobs"]))
    assert result["compared"] == 2 and result["scoreChanged"] == [] and result["bandChanged"] == []


def test_snapshot_file_round_trips_and_a_scored_file_converts(data_dir, tmp_path):
    doc = mc.rescore(data_dir)
    scored = tmp_path / "scored.json"
    scored.write_text(json.dumps(doc))
    converted = mc.read_snapshot(scored)
    snap = tmp_path / "snap.json"
    mc.write_private(snap, json.dumps({"stamp": {"currentRun": {}}, "rows": converted["rows"], "titles": {}}))
    assert stat.S_IMODE(snap.stat().st_mode) == 0o600
    assert mc.read_snapshot(snap)["rows"] == converted["rows"]


def test_rescore_refuses_a_stale_view(data_dir):
    (data_dir / "jobs" / "job_history.json").write_text('{"generation": 5, "jobs": {}}')
    (data_dir / "jobs" / "discovered_jobs.json").write_text('{"meta": {"generation": 4}, "jobs": []}')
    with pytest.raises(mc.StaleViewError):
        mc.rescore(data_dir)


# --- gate confusion -------------------------------------------------------------------------------------------------

def test_gate_confusion_counts_and_missing_ids():
    frozen = {"ads": {"1": {"overall": 0, "hardRequirements": "no"}, "2": {"overall": 3, "hardRequirements": "yes"},
                      "3": {"overall": 2, "hardRequirements": "partial"}}}
    rows = {"1": row(jobId="1", workAuthorization={"status": "needs_visa_refused"}, matchLabel="Reject"),
            "2": row(jobId="2", workAuthorization={"status": "authorized"}, matchLabel="Strong"),
            "3": row(jobId="3", dataStatus="insufficient", matchLabel=mc.INSUFFICIENT, workAuthorization={"status": "unknown"})}
    result = mg.build({"ads": {**frozen["ads"], "4": {"overall": 1, "hardRequirements": "no"}}}, rows, None)
    assert result["present"] == 3 and result["missingIds"] == ["4"]
    assert result["eligibilityVsHardRequirements"]["cells"]["fail|no"] == 1
    assert result["eligibilityVsHardRequirements"]["cells"]["pass|yes"] == 1
    assert result["bandVsOverall"]["cells"][f"{mc.INSUFFICIENT}|2"] == 1
    assert result["bandVsOverall"]["cells"]["Strong|3"] == 1
    assert "\n".join(mg.render(result))  # renders


# --- the Re-score makes no model call -------------------------------------------------------------------------------

def _forbid_every_network_seam(monkeypatch):
    calls = []

    def fail(name):
        def _f(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} was called during a Re-score")
        return _f

    import enrich_jobs
    import llm_client
    import requests

    monkeypatch.setattr(llm_client, "complete_json", fail("llm_client.complete_json"))
    monkeypatch.setattr(enrich_jobs, "complete_json", fail("enrich_jobs.complete_json"))
    monkeypatch.setattr(enrich_jobs, "extract", fail("enrich_jobs.extract"))
    for attr in ("post", "get", "request"):
        monkeypatch.setattr(requests, attr, fail(f"requests.{attr}"))
    monkeypatch.setattr(requests.Session, "request", fail("requests.Session.request"))
    for attr in ("run", "Popen", "check_output", "call"):
        monkeypatch.setattr(subprocess, attr, fail(f"subprocess.{attr}"))
    monkeypatch.setattr(socket.socket, "connect", fail("socket.connect"))
    monkeypatch.setattr(socket, "create_connection", fail("socket.create_connection"))
    return calls


@pytest.mark.parametrize("shadow_env", [None, "1"])
def test_the_rescore_path_makes_no_model_call(data_dir, monkeypatch, shadow_env):
    from match_engine import shadow

    if shadow_env:
        monkeypatch.setenv("HOLOJOB_ENGINE_SHADOW", shadow_env)
    else:
        monkeypatch.delenv("HOLOJOB_ENGINE_SHADOW", raising=False)
    constructed = []
    monkeypatch.setattr(shadow, "CACHE_PATH", data_dir / "engine.json")
    monkeypatch.setattr(shadow.ShadowEngine, "__init__", lambda *a, **k: constructed.append(1))
    calls = _forbid_every_network_seam(monkeypatch)

    doc = mc.rescore(data_dir)

    assert len(doc["jobs"]) == 2 and calls == [] and constructed == []  # the tool switches the shadow engine off even if the env asks for it
    assert not (data_dir / "engine.json").exists()
    assert not list((data_dir).rglob("usage-ledger.jsonl"))  # no AI ledger line either
    import os
    assert os.environ.get("HOLOJOB_ENGINE_SHADOW") == shadow_env  # the environment is put back


def test_measurement_scripts_import_no_provider_or_extraction_entry_point():
    forbidden = {"enrich_jobs", "llm_client", "requests", "socket", "urllib.request", "http.client", "openai", "anthropic", "ai_gate"}
    for name in ("measure_common", "measure_baseline", "measure_rescore_impact", "measure_gate_confusion"):
        tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not (imported & forbidden), (name, imported & forbidden)
    # subprocess is allowed in measure_common for `git rev-parse` / `git status` only
    source = (SCRIPTS / "measure_common.py").read_text(encoding="utf-8")
    assert source.count("subprocess.run") == 1 and '["git", "-C"' in source


# --- the variance script --------------------------------------------------------------------------------------------

def facts(mode="remote", must=2):
    return {"workMode": mode, "roleTrack": "product", "seniority": "senior", "yearsRequired": 5, "jobCountry": "RS", "visaSponsorship": "not_mentioned",
            "remoteEligibility": [], "listingFlags": [], "workModeEvidence": "SECRET EVIDENCE",
            "requirements": [{"kind": "skill", "importance": "must", "postingQuote": "SECRET QUOTE"}] * must}


def test_flip_report_rates():
    report = mv.flip_report({"a": [facts("remote"), facts("hybrid"), facts("remote")], "b": [facts(), facts(), facts()], "c": [facts()]})
    assert report["adsCompared"] == 2 and report["adsWithTooFewPasses"] == ["c"]
    mode = report["fields"]["workMode"]
    assert mode["adsFlipped"] == 1 and mode["adFlipRate"] == 0.5 and mode["flippedIds"] == ["a"]
    assert mode["pairDisagreementRate"] == round(2 / 6, 3)
    assert report["fields"]["roleTrack"]["adsFlipped"] == 0
    assert "SECRET" not in json.dumps(report)


@pytest.fixture
def variance_env(data_dir, tmp_path, monkeypatch):
    for var in ("HOLOJOB_CONFIG_DIR", "HOLOJOB_AI_DIR", "HOLOJOB_SECRETS_DIR"):
        monkeypatch.setenv(var, str(tmp_path / "nothing"))
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({"ids": ["a", "b", "missing"]}))
    priced = {"priceKnown": True, "provider": "p", "model": "m", "ads": 2, "calls": 6, "worstCaseUsd": 0.5, "inputOnlyUsd": 0.1,
              "inputTokensTypical": 1, "maxOutputTokensPerCall": 1, "note": ""}
    monkeypatch.setattr(mv, "estimate", lambda *a, **k: dict(priced))
    return data_dir, ids, priced


def test_variance_without_confirm_prints_the_estimate_and_calls_nothing(variance_env, monkeypatch, capsys):
    data_dir, ids, _ = variance_env
    import enrich_jobs
    calls = _forbid_every_network_seam(monkeypatch)
    monkeypatch.setattr(enrich_jobs, "make_guard", lambda *a, **k: calls.append("make_guard"))
    code = mv.main(["--ids", str(ids), "--runs", "3", "--max-usd", "1", "--data-dir", str(data_dir)])
    text = capsys.readouterr().out
    assert code == 0 and calls == [] and "Nothing was called" in text and '"calls": 6' in text and "--confirm" in text
    assert '"idsNotInJobList": 1' in text


def test_variance_refuses_an_unknown_price_a_bad_cap_and_too_few_runs(variance_env, monkeypatch):
    data_dir, ids, _ = variance_env
    base = ["--ids", str(ids), "--data-dir", str(data_dir)]
    assert mv.main([*base, "--runs", "1", "--max-usd", "1"]) == 2
    assert mv.main([*base, "--runs", "3", "--max-usd", "0"]) == 2
    monkeypatch.setattr(mv, "estimate", lambda *a, **k: {"priceKnown": False, "provider": "p", "model": "m"})
    calls = _forbid_every_network_seam(monkeypatch)
    assert mv.main([*base, "--runs", "3", "--max-usd", "1", "--confirm"]) == 1 and calls == []


def test_variance_with_confirm_runs_the_extraction_n_times_and_writes_a_private_report(variance_env, monkeypatch, tmp_path, capsys):
    data_dir, ids, _ = variance_env
    import enrich_jobs

    class Guard:
        def spent(self):
            return 0.01

    seen = []

    def fake_extract(job_row, model, provider, previous, mapper, guard):
        seen.append((job_row["jobId"], previous))
        return facts("remote" if len(seen) % 2 else "hybrid")

    monkeypatch.setattr(enrich_jobs, "make_guard", lambda cap, provider, model: Guard())
    monkeypatch.setattr(enrich_jobs, "extract", fake_extract)
    out = tmp_path / "out" / "variance.json"
    code = mv.main(["--ids", str(ids), "--runs", "3", "--max-usd", "1", "--data-dir", str(data_dir), "--workers", "1", "--confirm", "--out", str(out)])
    assert code == 0 and len(seen) == 6 and all(prev is None for _, prev in seen)  # --previous-frames none by default
    saved = json.loads(out.read_text())
    assert saved["meta"]["previousFrames"] == "none" and saved["report"]["adsCompared"] == 2
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert "SECRET" not in out.read_text() and "SECRET" not in capsys.readouterr().out
