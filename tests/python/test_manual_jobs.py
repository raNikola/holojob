"""Hand-entered jobs: stored apart from discovery, scored by the same path, and never lost or duplicated."""

import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import manual_jobs
from scorer import score_jobs

ROOT = Path(__file__).resolve().parents[2]
RUN_SCORING = ROOT / "python" / "job_scoring" / "run_scoring.py"

_spec = importlib.util.spec_from_file_location("import_job_url_under_test", ROOT / "python" / "job_import" / "import_job_url.py")
importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(importer)

MANUAL_ID = "manual-123e4567-e89b-12d3-a456-426614174000"
OTHER_ID = "manual-223e4567-e89b-12d3-a456-426614174001"
DESCRIPTION = "Own the roadmap for a payments product.\n\nKeep   this  spacing <b>and markup</b> as pasted."
NOTE = "NOTE-CANARY-4417"
LINK = "https://canary-4417.example/private"


def _manual(job_id=MANUAL_ID, url="https://acme.example/jobs/9", **extra):
    return {"jobId": job_id, "title": "Senior Product Manager", "company": "Acme", "description": DESCRIPTION,
            "jobUrl": url, "location": "", "salary": "", "status": "new", **extra}


def _discovered(job_id, url, title="Backend Engineer"):
    return {"jobId": job_id, "title": title, "company": "Other Co", "location": "Berlin, Germany",
            "description": "Build services in Go.", "jobUrl": url, "provider": "jobspy", "status": "new"}


@pytest.fixture
def intelligence():
    return json.loads((ROOT / "data" / "examples" / "candidate-intelligence.example.json").read_text())


class Env:
    def __init__(self, tmp_path, intelligence):
        self.dir = tmp_path / "jobs"
        self.dir.mkdir()
        self.discovered = self.dir / "discovered_jobs.json"
        self.scored = self.dir / "scored_jobs.json"
        self.manual = self.dir / "manual_jobs.json"
        self.intelligence = tmp_path / "intelligence.json"
        self.intelligence.write_text(json.dumps(intelligence))
        self.discovered.write_text(json.dumps({"meta": {}, "jobs": [_discovered("d-1", "https://jobs.example/1"), _discovered("d-2", "https://jobs.example/2")]}))

    def paths(self):
        return ["--discovered", str(self.discovered), "--scored", str(self.scored), "--manual", str(self.manual), "--intelligence", str(self.intelligence)]

    def add(self, payload, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        code = importer.main(["--job-json", "-", *self.paths()])
        out, err = capsys.readouterr()
        return code, out, err

    def rows(self, path=None):
        return {j["jobId"]: j for j in json.loads((path or self.scored).read_text())["jobs"]}

    def full_rescore(self, *extra):
        out = self.dir / "rescored.json"
        done = subprocess.run(
            [sys.executable, str(RUN_SCORING), "--intelligence", str(self.intelligence), "--jobs", str(self.discovered),
             "--manual", str(self.manual), "--output", str(out), *extra],
            capture_output=True, text=True,
        )
        assert done.returncode == 0, done.stderr
        return self.rows(out)


@pytest.fixture
def env(tmp_path, intelligence):
    return Env(tmp_path, intelligence)


@pytest.fixture
def offline(monkeypatch):
    """Anything that could reach the network, a subprocess or a model fails the test."""
    def boom(*_a, **_k):
        raise AssertionError("the --job-json path reached for the network, a process or a model")

    import requests

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(requests.sessions.Session, "request", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(importer.claude_code, "complete_json", boom)
    monkeypatch.setattr(importer.claude_code, "is_available", boom)
    monkeypatch.setattr(importer, "extract_job", boom)


# --- URL rule ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", json.loads((ROOT / "tests" / "fixtures" / "url-normalisation.json").read_text(encoding="utf-8")),
                         ids=lambda c: repr(c["input"]))
def test_url_normalisation_matches_the_shared_fixture(case):
    assert manual_jobs.normalize_url(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", json.loads((ROOT / "tests" / "fixtures" / "url-normalisation.json").read_text(encoding="utf-8")),
                         ids=lambda c: repr(c["input"]))
def test_identity_url_keeps_identifying_parameters_and_drops_tracking_ones(case):
    assert manual_jobs.identity_url(case["input"]) == case.get("identity", case["expected"])


def test_the_add_time_check_keeps_identifying_parameters_and_ignores_tracking_ones(env, monkeypatch, capsys):
    base = "https://careers.example/job"
    env.discovered.write_text(json.dumps({"jobs": [_discovered("g-1", f"{base}/?gh_jid=1#x")]}))
    # a sibling posting of the same board is a different job and can be added
    assert env.add(_manual(url=f"{base}?gh_jid=2"), monkeypatch, capsys)[0] == 0
    # the same posting with other tracking parameters is the same job, and the clash is shown
    code, out, _ = env.add(_manual(OTHER_ID, f"{base}?gh_jid=1&utm_source=mail&fbclid=z&gclid=y&ref=x"), monkeypatch, capsys)
    assert code == 3 and json.loads(out)["existing"]["jobId"] == "g-1"


def test_a_manual_job_replaces_only_the_posting_with_its_own_identity_and_the_run_counts_it(env, monkeypatch):
    base = "https://careers.example/job"
    env.discovered.write_text(json.dumps({"jobs": [
        _discovered("g-1", f"{base}?gh_jid=1"), _discovered("g-2", f"{base}?gh_jid=2"), _discovered("g-3", f"{base}?gh_jid=3"),
    ]}))
    manual_jobs.save([manual_jobs.sanitize(_manual(url=f"{base}?gh_jid=2&utm_source=x"))], env.manual)
    done = subprocess.run(
        [sys.executable, str(RUN_SCORING), "--intelligence", str(env.intelligence), "--jobs", str(env.discovered),
         "--manual", str(env.manual), "--output", str(env.dir / "out.json")],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    doc = json.loads((env.dir / "out.json").read_text())
    assert {j["jobId"] for j in doc["jobs"]} == {"g-1", "g-3", MANUAL_ID}
    assert doc["meta"]["manualJobs"] == {"count": 1, "replacedRows": 1}
    assert "manual jobs: 1 added, 1 discovered rows replaced" in done.stderr
    assert "Senior Product Manager" not in done.stderr  # counts only


# --- what Python is given --------------------------------------------------------------------------------------

def test_sanitize_keeps_only_scoring_fields_and_never_echoes_the_rest():
    job = manual_jobs.sanitize(_manual(notes=NOTE, extraLinks=[{"url": LINK, "label": "x"}], applicationTracking={"x": 1}))
    assert set(job) <= set(manual_jobs.SCORING_FIELDS)
    assert NOTE not in json.dumps(job) and LINK not in json.dumps(job)
    assert job["manualEntry"] is True and job["provider"] == "manual" and job["status"] == "new"


@pytest.mark.parametrize("bad", [
    {"jobId": "../../etc/passwd"}, {"jobId": "manual-x"}, {"title": " "}, {"company": ""}, {"description": ""},
    {"jobUrl": "ftp://x.example/a"}, {"title": 5},
])
def test_sanitize_refuses_and_names_the_field_only(bad):
    with pytest.raises(manual_jobs.InvalidJob) as raised:
        manual_jobs.sanitize({**_manual(), **bad})
    assert raised.value.field in manual_jobs.SCORING_FIELDS
    assert "etc/passwd" not in str(raised.value)


# --- --job-json: the same scoring path, nothing else ----------------------------------------------------------

def test_job_json_makes_no_network_process_or_model_call_and_keeps_the_pasted_text(env, offline, monkeypatch, capsys):
    code, out, _ = env.add(_manual(), monkeypatch, capsys)
    assert code == 0
    row = env.rows()[MANUAL_ID]
    assert row["description"] == DESCRIPTION.strip()
    assert row["manualEntry"] is True and row["provider"] == "manual" and row["status"] == "new"
    assert isinstance(row["matchScore"], int) and row["aiEnrichment"] == "missing"
    assert json.loads(out.strip().splitlines()[-1])["jobs"][0]["jobId"] == MANUAL_ID
    assert not (Path(__import__("os").environ["HOLOJOB_AI_DIR"]) / "usage-ledger.jsonl").exists()


def test_the_row_equals_the_one_a_full_rescore_writes(env, monkeypatch, capsys):
    assert env.add(_manual(), monkeypatch, capsys)[0] == 0
    assert env.full_rescore()[MANUAL_ID] == env.rows()[MANUAL_ID]


def test_missing_location_stays_unknown_and_is_never_capped_as_outside(env, monkeypatch, capsys):
    """With a location gate set (allowed: Serbia), a place the owner left empty is unknown; a stated Berlin is outside."""
    intel = json.loads(env.intelligence.read_text())
    intel["jobFitPreferences"] = {**intel["jobFitPreferences"], "allowedLocations": ["RS"]}
    env.intelligence.write_text(json.dumps(intel))

    assert env.add(_manual(location=""), monkeypatch, capsys)[0] == 0
    row = env.rows()[MANUAL_ID]
    assert row["location"] == "" and row.get("isRemote") is None
    assert row["workAuthorization"]["status"] == "unknown" and row["workAuthorization"]["place"] == "unknown"
    assert "Location not stated" in row["reasons"]

    assert env.add(_manual(OTHER_ID, "https://acme.example/jobs/10", location="Berlin, Germany"), monkeypatch, capsys)[0] == 0
    assert env.rows()[OTHER_ID]["workAuthorization"]["status"] == "outside_allowed"  # the gate works, so the first result means something


def test_notes_and_extra_links_reach_no_output_log_or_file(env, monkeypatch, capsys):
    code, out, err = env.add(_manual(notes=NOTE, extraLinks=[{"url": LINK, "label": NOTE}]), monkeypatch, capsys)
    assert code == 0
    blob = out + err + "".join(p.read_text() for p in env.dir.iterdir() if p.is_file())
    assert NOTE not in blob and "canary-4417" not in blob


def test_a_retry_is_idempotent_and_keeps_the_dates_and_tailored_assets(env, monkeypatch, capsys):
    assert env.add(_manual(), monkeypatch, capsys)[0] == 0
    first = env.rows()[MANUAL_ID]
    doc = json.loads(env.scored.read_text())
    next(j for j in doc["jobs"] if j["jobId"] == MANUAL_ID)["tailoredAssets"] = {"generatedAt": "t"}
    env.scored.write_text(json.dumps(doc))

    assert env.add(_manual(firstSeen="2099-01-01T00:00:00+00:00"), monkeypatch, capsys)[0] == 0
    scored_ids = [j["jobId"] for j in json.loads(env.scored.read_text())["jobs"]]
    assert scored_ids.count(MANUAL_ID) == 1
    assert [j["jobId"] for j in manual_jobs.load(env.manual)].count(MANUAL_ID) == 1
    again = env.rows()[MANUAL_ID]
    assert again["firstSeen"] == first["firstSeen"] and again["tailoredAssets"] == {"generatedAt": "t"}


def test_scoring_failure_keeps_the_job_stored_and_a_retry_scores_it(env, monkeypatch, capsys):
    env.intelligence.rename(env.intelligence.with_name("later.json"))
    code, out, err = env.add(_manual(), monkeypatch, capsys)
    assert code == 4 and json.loads(out)["error"] == "no_intelligence"
    assert [j["jobId"] for j in manual_jobs.load(env.manual)] == [MANUAL_ID]
    assert not env.scored.exists()

    env.intelligence.with_name("later.json").rename(env.intelligence)
    assert env.add(_manual(), monkeypatch, capsys)[0] == 0
    assert MANUAL_ID in env.rows()


def test_an_error_in_scoring_reports_the_class_not_the_job_text(env, monkeypatch, capsys):
    def explode(*_a, **_k):
        raise RuntimeError(f"cannot score {DESCRIPTION}")

    monkeypatch.setattr(importer, "score_jobs", explode)
    code, out, err = env.add(_manual(), monkeypatch, capsys)
    assert code == 5 and json.loads(out)["detail"] == "RuntimeError"
    assert "Keep   this" not in out + err


def test_a_description_is_required_to_store_and_score(env, monkeypatch, capsys):
    code, out, _ = env.add(_manual(description=""), monkeypatch, capsys)
    assert code == 2 and json.loads(out)["field"] == "description"
    assert not env.manual.exists() and not env.scored.exists()


def test_check_only_writes_nothing_and_names_a_clash_even_without_a_description(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_manual(description="", url="https://jobs.example/1/?utm_source=x"))))
    code = importer.main(["--job-json", "-", "--check-only", *env.paths()])
    out = capsys.readouterr().out
    assert code == 3 and json.loads(out)["existing"]["jobId"] == "d-1"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_manual(description="", url="https://fresh.example/1"))))
    assert importer.main(["--job-json", "-", "--check-only", *env.paths()]) == 0
    capsys.readouterr()
    assert not env.manual.exists() and not env.scored.exists()


def test_a_source_url_is_dropped_and_no_source_is_invented(env, monkeypatch, capsys):
    source = "https://canary-4417.linkedin.example/posts/secret"
    code, out, err = env.add(_manual(sourceUrl=source), monkeypatch, capsys)
    assert code == 0
    blob = out + err + "".join(p.read_text() for p in env.dir.iterdir() if p.is_file())
    assert "canary-4417" not in blob
    assert "sourceChoice" not in env.rows()[MANUAL_ID]


def test_store_only_saves_the_job_for_the_next_run_and_scores_nothing(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([_manual(notes=NOTE)])))
    code = importer.main(["--job-json", "-", "--store-only", *env.paths()])
    out = capsys.readouterr().out
    assert code == 0 and json.loads(out)["stored"] == [MANUAL_ID]
    assert not env.scored.exists() and [j["jobId"] for j in manual_jobs.load(env.manual)] == [MANUAL_ID]
    assert NOTE not in out + env.manual.read_text()
    assert MANUAL_ID in env.full_rescore()  # the next scoring run has it


def test_a_batch_upserts_the_valid_jobs_and_skips_the_rest(env, monkeypatch, capsys):
    code, out, _ = env.add([_manual(), _manual(OTHER_ID, "https://acme.example/jobs/10"), {"jobId": "bad"}], monkeypatch, capsys)
    assert code == 0
    summary = json.loads(out.strip().splitlines()[-1])
    assert {j["jobId"] for j in summary["jobs"]} == {MANUAL_ID, OTHER_ID}
    assert summary["skipped"][0]["error"] == "invalid"


# --- duplicates: manual after discovery, discovery after manual, URL import after manual ---------------------------

def test_a_manual_job_with_a_discovered_jobs_url_is_refused_and_names_it(env, monkeypatch, capsys):
    code, out, _ = env.add(_manual(url="HTTPS://Jobs.Example/1/?utm_source=x"), monkeypatch, capsys)
    assert code == 3
    assert json.loads(out)["existing"]["jobId"] == "d-1"
    assert not env.manual.exists() and not env.scored.exists()


def test_a_discovery_run_after_a_manual_job_adds_no_second_row(env, monkeypatch, capsys):
    assert env.add(_manual(url="https://acme.example/jobs/9"), monkeypatch, capsys)[0] == 0
    # the next discovery finds the same posting under its own id
    env.discovered.write_text(json.dumps({"jobs": [_discovered("d-9", "https://acme.example/jobs/9/", "Senior Product Manager")]}))
    rows = env.full_rescore()
    assert list(rows) == [MANUAL_ID]


def test_a_url_import_of_a_manual_jobs_link_is_refused(env, monkeypatch, capsys):
    assert env.add(_manual(url="https://acme.example/jobs/9"), monkeypatch, capsys)[0] == 0
    monkeypatch.setattr(importer.claude_code, "is_available", lambda: False)
    monkeypatch.setattr(importer, "extract_job", lambda url, use_llm: (_discovered("url-1", url), ""))
    code = importer.main(["--url", "https://ACME.example/jobs/9/", *env.paths()])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 1 and out["imported"] == [] and "already in your jobs" in out["errors"][0]["error"]
    assert "url-1" not in env.rows()


# --- the URL import uses the same limited fetcher --------------------------------------------------------------

@pytest.mark.parametrize("url", ["http://127.0.0.1:3073/api/jobs", "http://169.254.169.254/latest/meta-data/", "https://holojob.void/", "http://100.64.0.9/", "ftp://example.com/x"])
def test_the_url_import_cannot_be_pointed_at_the_home_network(url, monkeypatch):
    import safe_fetch

    monkeypatch.setattr(safe_fetch, "_request", lambda *a, **k: pytest.fail("a request was made"))
    job, error = importer.extract_job(url, use_llm=False)
    assert job is None and error.startswith("fetch failed:")


def test_the_url_import_reads_a_page_through_the_limited_fetcher(monkeypatch):
    import safe_fetch

    html = '<script type="application/ld+json">{"@type":"JobPosting","title":"PM","hiringOrganization":{"name":"Acme"},"description":"<p>' + "Own the roadmap. " * 20 + '</p>"}</script>'
    monkeypatch.setattr(safe_fetch, "fetch_page", lambda url: safe_fetch.Page(url, html))
    job, error = importer.extract_job("https://jobs.example.com/1", use_llm=False)
    assert error == "" and job["title"] == "PM" and job["company"] == "Acme"


# --- what can delete a manual job -----------------------------------------------------------------------------

def test_a_rescrape_and_a_full_rescore_keep_the_manual_job(env, monkeypatch, capsys):
    assert env.add(_manual(), monkeypatch, capsys)[0] == 0
    env.discovered.write_text(json.dumps({"meta": {}, "jobs": [_discovered("d-3", "https://jobs.example/3")]}))  # discovery rewrites it
    rows = env.full_rescore()
    assert MANUAL_ID in rows and "d-3" in rows and "d-1" not in rows


def test_min_score_never_drops_a_manual_job(env, monkeypatch, capsys):
    assert env.add(_manual(), monkeypatch, capsys)[0] == 0
    assert MANUAL_ID in env.full_rescore("--min-score", "100")


def test_a_rescore_before_any_discovery_still_has_the_manual_job(env, monkeypatch, capsys):
    assert env.add(_manual(), monkeypatch, capsys)[0] == 0
    env.discovered.unlink()
    assert list(env.full_rescore()) == [MANUAL_ID]


def test_discovery_and_url_import_never_write_the_manual_file(env, monkeypatch, capsys):
    assert env.add(_manual(), monkeypatch, capsys)[0] == 0
    before = env.manual.read_text()
    monkeypatch.setattr(importer.claude_code, "is_available", lambda: False)
    monkeypatch.setattr(importer, "extract_job", lambda url, use_llm: (_discovered("url-2", url), ""))
    importer.main(["--url", "https://elsewhere.example/a", *env.paths()])
    assert env.manual.read_text() == before
    assert MANUAL_ID in env.rows() and "url-2" in env.rows()  # the URL import's merge removed nothing


def test_the_export_discovery_uses_does_not_know_the_manual_file():
    source = (ROOT / "python" / "job_discovery" / "export_jobs.py").read_text()
    assert "manual_jobs" not in source


def test_tailoring_writes_every_row_back_by_id():
    source = (ROOT / "python" / "resume_generator" / "run_tailor.py").read_text()
    assert 'by_id = {j.get("jobId"): j for j in jobs}' in source and 'scored_doc["jobs"] = list(by_id.values())' in source


def test_with_manual_prefers_the_manual_row_by_id_and_by_url():
    manual = [dict(_manual(), manualEntry=True)]
    jobs = [_discovered("d-1", "https://acme.example/jobs/9/"), _discovered(MANUAL_ID, "https://x.example/other"), _discovered("d-2", "https://y.example/z")]
    merged = manual_jobs.with_manual(jobs, manual)
    assert [j["jobId"] for j in merged] == ["d-2", MANUAL_ID]
    assert merged[-1].get("manualEntry") is True


# --- editing a manual job: the stored row is replaced, and wins over a discovered row ----------------------------------

def test_an_edit_replaces_the_row_keeps_the_first_dates_and_stores_updated_at():
    old = manual_jobs.sanitize({"jobId": MANUAL_ID, "title": "PM", "company": "Acme", "description": "Own it.", "jobUrl": "https://acme.example/1",
                                "createdAt": "2026-10-01T00:00:00Z", "firstSeen": "2026-10-01T00:00:00Z"})
    edit = manual_jobs.sanitize({"jobId": MANUAL_ID, "title": "Senior PM", "company": "Acme", "description": "Own it.", "jobUrl": "https://acme.example/2",
                                 "createdAt": "2030-01-01T00:00:00Z", "firstSeen": "2030-01-01T00:00:00Z", "updatedAt": "2026-10-31T09:00:00Z"})
    rows = manual_jobs.upsert([edit], [old])
    assert len(rows) == 1
    assert rows[0]["title"] == "Senior PM" and rows[0]["jobUrl"] == "https://acme.example/2"
    assert rows[0]["createdAt"] == "2026-10-01T00:00:00Z" and rows[0]["firstSeen"] == "2026-10-01T00:00:00Z"
    assert rows[0]["updatedAt"] == "2026-10-31T09:00:00Z"


def test_an_edited_manual_job_wins_over_a_discovered_row_in_every_run():
    edited = manual_jobs.sanitize({"jobId": MANUAL_ID, "title": "Senior PM", "company": "Acme", "description": "Own it.", "jobUrl": "https://acme.example/2"})
    discovered = [{"jobId": "d-1", "title": "Senior PM (copy)", "jobUrl": "https://acme.example/2/"}, {"jobId": "d-2", "title": "Other", "jobUrl": "https://other.example/1"}]
    merged = manual_jobs.with_manual(discovered, [edited])
    assert [j["jobId"] for j in merged] == ["d-2", MANUAL_ID]
    assert merged[-1]["title"] == "Senior PM"


def test_the_same_id_under_a_new_address_is_not_a_clash_with_itself():
    stored = [manual_jobs.sanitize({"jobId": MANUAL_ID, "title": "PM", "company": "Acme", "description": "x", "jobUrl": "https://acme.example/1"})]
    assert manual_jobs.find_clash(MANUAL_ID, "https://acme.example/1?utm_source=a", stored) is None
    assert manual_jobs.find_clash(OTHER_ID, "https://acme.example/1", stored)["jobId"] == MANUAL_ID


def _failing_fsync(directory, on_disk_at_failure):
    def fail(*_args, **_kwargs):
        on_disk_at_failure.extend(p.name for p in directory.iterdir())
        raise OSError("disk full")
    return fail


def test_a_failed_manual_save_keeps_the_previous_file_and_leaves_no_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "manual_jobs.json"
    path.write_text('{"previous": true}', encoding="utf-8")
    on_disk_at_failure = []
    monkeypatch.setattr(os, "fsync", _failing_fsync(tmp_path, on_disk_at_failure))

    with pytest.raises(OSError, match="disk full"):
        manual_jobs.save([_manual()], path)

    assert any(name.endswith(".tmp") for name in on_disk_at_failure)  # it failed with the temp file there
    assert path.read_text(encoding="utf-8") == '{"previous": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["manual_jobs.json"]


def test_a_failed_merge_keeps_the_previous_scored_file_and_leaves_no_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "scored_jobs.json"
    before = json.dumps({"meta": {}, "jobs": [{"jobId": "a"}]})
    path.write_text(before, encoding="utf-8")
    on_disk_at_failure = []
    monkeypatch.setattr(os, "fsync", _failing_fsync(tmp_path, on_disk_at_failure))

    with pytest.raises(OSError, match="disk full"):
        importer.merge_into_scored([{"jobId": "b"}], path)

    assert any(name.endswith(".tmp") for name in on_disk_at_failure)  # it failed with the temp file there
    assert path.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == ["scored_jobs.json"]
