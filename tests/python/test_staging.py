"""Staging: what a scrape collects, written while it collects (slice 1a). Offline, every path under tmp_path."""

import json
import os
import signal
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

import job_history  # noqa: E402
import run_discovery  # noqa: E402
import run_log  # noqa: E402
import staging  # noqa: E402
from providers import infostud_client, infostud_provider, joberty_provider  # noqa: E402
from providers.base_provider import JobProvider, ProviderOutcome  # noqa: E402

SEARCH = dict(search_key="abc123", terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=["remote"],
              providers=["greenhouse"])


def ad(job_id="g1", **extra):
    return {"jobId": job_id, "provider": "greenhouse", "source": "acme", "title": "Product Manager", "company": "Acme",
            "location": "Remote", "site": "acme", "jobUrl": f"https://a.example/{job_id}", "description": "Own the roadmap.",
            "isRemote": True, "status": "new", **extra}


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def begin(tmp_path, run_id="run1", ledger=None):
    return staging.StagingRun.begin(tmp_path, run_id, ledger_path=ledger, **SEARCH)


# --- the format and its validation ---------------------------------------------------------------------------------


def test_a_whole_canonical_ad_has_no_problems_and_each_defect_is_named():
    assert staging.problems(ad()) == []
    assert staging.problems(ad(example="extra fields of a provider pass", tags=["a"])) == []
    assert staging.problems("text") == ["not an object"]
    assert any("jobId" in p for p in staging.problems(ad(jobId="")))
    assert any("title" in p for p in staging.problems(ad(title=None)))
    assert any("description" in p for p in staging.problems(ad(description=None)))
    assert any("isRemote" in p for p in staging.problems(ad(isRemote="yes")))
    assert any("JSON" in p for p in staging.problems(ad(salaryNumber=float("nan"))))
    assert any("JSON" in p for p in staging.problems(ad(blob={1, 2})))


def test_a_source_file_is_header_batches_footer_and_reads_back_whole(tmp_path):
    run = begin(tmp_path)
    writer = run.open_source("greenhouse")
    assert writer.append([ad("a"), ad("b")], part="board-1", read=5) == 2
    assert writer.append([], part="board-2", read=0) == 0
    writer.append([ad("c")], part="board-3")
    writer.finish(status="ok", complete=True, read=6, kept=3, total=None)

    lines = (tmp_path / "data/jobs/staging/run1/greenhouse.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["t"] for line in lines] == ["header", "batch", "batch", "batch", "footer"]
    header = json.loads(lines[0])
    assert header["source"] == "greenhouse" and header["runId"] == "run1" and header["searchKey"] == "abc123"
    assert header["terms"] == ["pm"] and header["country"] == "Serbia"

    stage = staging.read_source(tmp_path / "data/jobs/staging/run1/greenhouse.jsonl")
    assert stage.usable and stage.finished and stage.complete and not stage.torn
    assert [j["jobId"] for j in stage.jobs] == ["a", "b", "c"]
    assert [(b.part, b.read, len(b.jobs)) for b in stage.batches] == [("board-1", 5, 2), ("board-2", 0, 0), ("board-3", None, 1)]
    assert stage.footer["staged"] == 3 and stage.footer["batches"] == 3 and stage.footer["invalid"] == 0


def test_an_ad_that_is_not_whole_stays_out_of_the_file_and_is_counted(tmp_path):
    writer = begin(tmp_path).open_source("greenhouse")
    assert writer.append([ad("a"), ad("b", title=""), {"jobId": "x"}, ad("c", isRemote=3)], part="p") == 1
    writer.finish(status="ok", complete=True, read=4, kept=4)
    stage = staging.read_source(tmp_path / "data/jobs/staging/run1/greenhouse.jsonl")
    assert [j["jobId"] for j in stage.jobs] == ["a"]
    assert stage.footer["invalid"] == 3 and len(stage.footer["invalidExamples"]) == 3
    assert stage.footer["invalidExamples"][0]["problems"]


def test_the_reader_does_not_trust_the_file_either(tmp_path):
    path = tmp_path / "s.jsonl"
    good = {"t": "header", "source": "s"}
    bad_batch = {"t": "batch", "part": "p", "read": 1, "jobs": [ad("ok"), {"jobId": "", "provider": "x", "title": "t"}]}
    path.write_bytes(b"\n".join(json.dumps(r).encode() for r in (good, bad_batch)) + b"\n")
    stage = staging.read_source(path)
    assert [j["jobId"] for j in stage.jobs] == ["ok"] and stage.rejected_ads == 1


def test_a_torn_last_line_is_ignored_and_the_whole_lines_before_it_are_kept(tmp_path):
    writer = begin(tmp_path).open_source("greenhouse")
    writer.append([ad("a")], part="one")
    writer.append([ad("b")], part="two")
    path = tmp_path / "data/jobs/staging/run1/greenhouse.jsonl"
    third = json.dumps({"t": "batch", "part": "three", "read": None, "jobs": [ad("c")]}).encode()
    with open(path, "ab") as handle:
        handle.write(third[: len(third) // 2])  # the process died in the middle of a write
    stage = staging.read_source(path)
    assert stage.torn and [j["jobId"] for j in stage.jobs] == ["a", "b"]
    assert not stage.finished and not stage.complete, "no footer: the source was stopped"


def test_a_line_in_the_middle_that_does_not_parse_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(
        json.dumps({"t": "header", "source": "s"}).encode() + b"\n" + b"{broken\n"
        + json.dumps({"t": "batch", "part": "p", "read": None, "jobs": [ad("a")]}).encode() + b"\n"
    )
    stage = staging.read_source(path)
    assert [j["jobId"] for j in stage.jobs] == ["a"] and stage.unreadable_lines == 1


def test_a_file_with_no_header_has_no_usable_ads_and_nothing_after_a_footer_counts(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(json.dumps({"t": "batch", "part": "p", "read": None, "jobs": [ad("a")]}).encode() + b"\n")
    assert not staging.read_source(path).usable and staging.read_source(path).jobs == []
    path.write_bytes(
        b"\n".join(json.dumps(r).encode() for r in (
            {"t": "header"}, {"t": "batch", "jobs": [ad("a")]}, {"t": "footer", "complete": True}, {"t": "batch", "jobs": [ad("late")]},
        )) + b"\n"
    )
    assert [j["jobId"] for j in staging.read_source(path).jobs] == ["a"]


def test_complete_means_a_footer_that_says_so(tmp_path):
    run = begin(tmp_path)
    for name, status, complete in (("greenhouse", "ok", True), ("lever", "partial", False), ("ashby", "failed", False)):
        writer = run.open_source(name)
        writer.append([ad(name)], part="p")
        writer.finish(status=status, complete=complete, read=1, kept=1)
    unfinished = run.open_source("workable")
    unfinished.append([ad("w")], part="p")
    stages = staging.read_run(tmp_path, "run1").sources
    assert {n: (s.finished, s.complete) for n, s in stages.items()} == {
        "greenhouse": (True, True), "lever": (True, False), "ashby": (True, False), "workable": (False, False),
    }
    assert [j["jobId"] for j in stages["lever"].jobs] == ["lever"], "a partial source's ads are still its ads"


# --- permissions, ledger link, pruning -----------------------------------------------------------------------------


def test_folders_are_700_and_files_600(tmp_path):
    (tmp_path / "data/jobs").mkdir(parents=True)
    os.chmod(tmp_path / "data/jobs", 0o755)
    ledger = tmp_path / "data/jobs/job_history.json"
    job_history.save(ledger, {"version": 1, "updatedAt": None, "jobs": {}})
    run = begin(tmp_path, ledger=ledger)
    writer = run.open_source("greenhouse")
    writer.append([ad()], part="p")
    writer.finish(status="ok", complete=True, read=1, kept=1)
    base = tmp_path / "data/jobs/staging"
    assert mode(base) == 0o700 and mode(base / "run1") == 0o700
    assert mode(base / "run1/greenhouse.jsonl") == 0o600 and mode(base / "run1/run.json") == 0o600
    assert mode(tmp_path / "data/jobs") == 0o755, "an existing folder keeps its mode"


def test_the_ledger_as_it_was_survives_the_atomic_replace_of_the_ledger(tmp_path):
    ledger = tmp_path / "data/jobs/job_history.json"
    ledger.parent.mkdir(parents=True)
    job_history.save(ledger, {"version": 1, "updatedAt": None, "jobs": {"old": {"firstSeen": "x"}}})
    before = ledger.read_bytes()
    run = begin(tmp_path, ledger=ledger)

    new = job_history.load(ledger)
    new["jobs"]["new"] = {"firstSeen": "y"}
    job_history.save(ledger, new)  # what the run's own commit does
    assert ledger.read_bytes() != before

    kept = tmp_path / "data/jobs/staging/run1.ledger-before.json"
    assert kept.read_bytes() == before
    info = staging.read_run(tmp_path, "run1").manifest["ledgerBefore"]
    assert info["file"] == kept.name and info["linked"] is True and info["bytes"] == len(before)
    import hashlib
    assert info["sha256"] == hashlib.sha256(before).hexdigest()
    assert staging.read_run(tmp_path, "run1").ledger_before == kept
    assert not run.warnings


def test_without_a_ledger_there_is_nothing_to_keep_and_that_is_not_a_warning(tmp_path):
    run = begin(tmp_path, ledger=tmp_path / "data/jobs/job_history.json")
    assert staging.read_run(tmp_path, "run1").manifest["ledgerBefore"] is None and not run.warnings


def test_where_a_hard_link_is_not_possible_the_ledger_is_copied_private(tmp_path, monkeypatch):
    ledger = tmp_path / "data/jobs/job_history.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"version":1,"jobs":{}}')
    os.chmod(ledger, 0o644)

    def refuse(*args, **kwargs):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(staging.os, "link", refuse)
    begin(tmp_path, ledger=ledger)
    kept = tmp_path / "data/jobs/staging/run1.ledger-before.json"
    assert kept.read_bytes() == ledger.read_bytes() and mode(kept) == 0o600
    assert staging.read_run(tmp_path, "run1").manifest["ledgerBefore"]["linked"] is False
    assert mode(ledger) == 0o644, "the live ledger's mode is not touched"


def test_no_staging_run_is_removed_and_usage_counts_a_hard_linked_file_once(tmp_path, monkeypatch):
    """Until S4a deletes by status, nothing removes a run: a run still waiting for import must never be lost."""
    ledger = tmp_path / "data/jobs/job_history.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"version":1,"jobs":{}}')
    stamps = iter(f"2026-11-0{n}T10:00:00+00:00" for n in range(1, 8))
    monkeypatch.setattr(staging, "_now", lambda: next(stamps))
    for n in range(1, 6):
        begin(tmp_path, run_id=f"r{n}", ledger=ledger)
    base = tmp_path / "data/jobs/staging"
    assert sorted(p.name for p in base.iterdir()) == sorted(
        [f"r{n}" for n in range(1, 6)] + [f"r{n}.ledger-before.json" for n in range(1, 6)])
    assert staging.list_runs(tmp_path) == ["r5", "r4", "r3", "r2", "r1"]
    used = staging.usage(tmp_path)
    assert used["runs"] == 5
    assert used["bytes"] < 5 * ledger.stat().st_size + 5 * 2000, "the five links to one ledger are one copy"
    assert staging.prune(tmp_path) == [], "and nothing is pruned: none of these runs was imported"


def test_a_bad_run_id_or_source_name_cannot_leave_the_staging_folder(tmp_path):
    run = begin(tmp_path, run_id="../escape")
    assert run.disabled and run.warnings
    assert not (tmp_path / "data/jobs/escape").exists()
    good = begin(tmp_path, run_id="ok1")
    writer = good.open_source("../evil")
    assert writer.failed and writer.append([ad()]) == 0
    assert staging.read_run(tmp_path, "../escape") is None


# --- staging never stops a run -------------------------------------------------------------------------------------


def test_a_staging_folder_that_cannot_be_made_disables_staging_and_the_writers_write_nothing(tmp_path):
    (tmp_path / "data/jobs").mkdir(parents=True)
    (tmp_path / "data/jobs/staging").write_text("a file where the folder should be")
    run = begin(tmp_path)
    assert run.disabled and run.warnings
    writer = run.open_source("greenhouse")
    assert writer.append([ad()], part="p") == 0
    writer.finish(status="ok", complete=True, read=1, kept=1)
    writer.close_source([ad()], ProviderOutcome(read=1, kept=1))  # no raise


def test_a_write_that_fails_halfway_stops_that_source_only(tmp_path, monkeypatch):
    run = begin(tmp_path)
    writer = run.open_source("greenhouse")
    assert writer.append([ad("a")], part="one") == 1

    def full(*args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(staging.os, "write", full)
    assert writer.append([ad("b")], part="two") == 0 and writer.failed
    monkeypatch.undo()
    assert writer.append([ad("c")], part="three") == 0, "once stopped it stays stopped"
    stage = staging.read_source(tmp_path / "data/jobs/staging/run1/greenhouse.jsonl")
    assert [j["jobId"] for j in stage.jobs] == ["a"] and not stage.finished


def test_sigkill_mid_source_leaves_every_written_batch_readable_and_nothing_else(tmp_path):
    """The real thing: a process killed between two appends. The live files are not touched."""
    (tmp_path / "data/jobs").mkdir(parents=True)
    live = tmp_path / "data/jobs/discovered_jobs.json"
    live.write_text('{"meta":{},"jobs":[]}')
    live_bytes = live.read_bytes()
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import os, signal, sys
        from pathlib import Path
        sys.path.insert(0, {str(ROOT / "python" / "job_discovery")!r})
        import staging
        run = staging.StagingRun.begin(Path({str(tmp_path)!r}), "killed1", search_key="k", terms=["pm"], locations=["Remote"],
                                       country="Serbia", remote_filters=[], providers=["jobspy"])
        writer = run.open_source("jobspy")
        job = lambda i: {{"jobId": f"j{{i}}", "provider": "jobspy", "title": "PM"}}
        writer.append([job(1), job(2)], part="pm @ Remote", read=2)
        writer.append([job(3)], part="lead @ Remote", read=1)
        os.kill(os.getpid(), signal.SIGKILL)
    """))
    done = subprocess.run([sys.executable, str(driver)], capture_output=True)
    assert done.returncode == -signal.SIGKILL, done.stderr.decode()[-600:]
    stage = staging.read_run(tmp_path, "killed1").sources["jobspy"]
    assert [j["jobId"] for j in stage.jobs] == ["j1", "j2", "j3"]
    assert [b.part for b in stage.batches] == ["pm @ Remote", "lead @ Remote"]
    assert not stage.finished and not stage.complete and not stage.torn
    assert live.read_bytes() == live_bytes
    assert sorted(p.name for p in (tmp_path / "data/jobs").iterdir()) == ["discovered_jobs.json", "staging"]


# --- inside a run: the commit path is the old one ------------------------------------------------------------------


class Fake(JobProvider):
    def __init__(self, jobs, status="ok"):
        self.jobs, self.status, self.last_outcome = jobs, status, None

    def fetch_jobs(self, *args):
        self.last_outcome = ProviderOutcome(status=self.status, read=len(self.jobs), kept=len(self.jobs))
        return list(self.jobs)


def discover(root, monkeypatch, providers, *, staging_on=True):
    monkeypatch.setattr(run_discovery, "ROOT", root)
    intelligence = root / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": ["pm"], "locationFilters": ["Remote"], "remoteFilters": ["remote"],
    }}))
    monkeypatch.setattr(run_discovery, "get_provider", lambda name: providers[name])
    monkeypatch.setattr(run_discovery, "effective_provider_names", lambda spec: list(providers))
    if not staging_on:
        def off(cls, root, run_id, **kw):
            run = cls(root, run_id)
            run.disabled = "off for this test"
            return run

        monkeypatch.setattr(run_discovery.staging.StagingRun, "begin", classmethod(off))
    monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--providers", "x", "--intelligence", str(intelligence)])
    return run_discovery.main()


def settled(root):
    """The files the old commit path writes, without what differs between any two runs (clock, run id)."""
    out = {}
    for name in ("job_history.json", "discovered_jobs.json", "normalized_jobs.json", "raw_jobs.csv"):
        text = (root / "data/jobs" / name).read_text(encoding="utf-8")
        if name.endswith(".json"):
            text = json.dumps(_strip(json.loads(text)), sort_keys=True)
        out[name] = text
    return out


def _strip(value):
    volatile = {"generatedAt", "updatedAt", "firstSeen", "lastSeen", "scrapedAt", "sourceRunId", "closedAt"}
    if isinstance(value, dict):
        return {k: ("" if k in volatile else _strip(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def test_with_staging_off_nothing_is_committed_and_the_run_says_so(tmp_path, monkeypatch):
    """S4a: the import reads staging, so a run without it commits nothing: the ledger and the view stay as they were."""
    root = tmp_path / "root"
    (root / "data/jobs").mkdir(parents=True)
    (root / "data/jobs/job_history.json").write_text('{"version":1,"updatedAt":null,"jobs":{}}')
    (root / "data/jobs/discovered_jobs.json").write_text('{"meta":{},"jobs":[]}')
    before = {p.name: p.read_bytes() for p in (root / "data/jobs").iterdir()}
    assert discover(root, monkeypatch, {"greenhouse": Fake([ad("a")])}, staging_on=False) == 1
    assert {p.name: p.read_bytes() for p in (root / "data/jobs").iterdir()} == before
    record = max(run_log.runs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
    body = json.loads(record.read_text())
    assert body["status"] == "failed" and body["staging"]["ok"] is False
    assert any(i["level"] == "error" and "Nothing was imported" in i["message"] for i in body["issues"])


def test_a_provider_that_does_not_stream_has_its_list_staged_whole_when_it_returns(tmp_path, monkeypatch):
    assert discover(tmp_path, monkeypatch, {"greenhouse": Fake([ad("a"), ad("b")])}) == 0
    [run_id] = staging.list_runs(tmp_path)
    stage = staging.read_run(tmp_path, run_id).sources["greenhouse"]
    assert [j["jobId"] for j in stage.jobs] == ["a", "b"]
    assert [b.part for b in stage.batches] == ["all"]
    assert stage.complete and stage.footer["written"] == "at the end" and stage.footer["mismatch"] is False
    assert stage.footer["read"] == 2 and stage.footer["kept"] == 2 and stage.footer["status"] == "ok"
    assert run_id == run_log.find_record(run_id)["runId"], "staging is named by the run's id"
    manifest = staging.read_run(tmp_path, run_id).manifest
    assert manifest["searchKey"] == stage.header["searchKey"] and manifest["providers"] == ["greenhouse"]


def test_a_failed_and_a_skipped_source_get_a_footer_that_is_not_complete(tmp_path, monkeypatch):
    class Skips(Fake):
        def fetch_jobs(self, *args):
            self.last_outcome = ProviderOutcome(status="skipped", skip_reason="not here")
            return []

    class Raises(Fake):
        def fetch_jobs(self, *args):
            raise RuntimeError("boom")

    assert discover(tmp_path, monkeypatch, {"greenhouse": Fake([ad("a")]), "lever": Skips([]), "ashby": Raises([])}) == 0
    sources = staging.read_run(tmp_path, staging.list_runs(tmp_path)[0]).sources
    assert sources["lever"].footer["status"] == "skipped" and sources["lever"].footer["skipReason"] == "not here"
    assert sources["ashby"].footer["status"] == "failed" and "boom" in sources["ashby"].footer["error"]
    assert not sources["lever"].complete and not sources["ashby"].complete and sources["greenhouse"].complete


def test_a_provider_that_stages_less_than_it_returns_is_flagged_in_the_footer(tmp_path, monkeypatch):
    class Careless(Fake):
        def fetch_jobs(self, *args):
            self.stage([self.jobs[0]], part="first")  # forgets the second
            return super().fetch_jobs(*args)

    discover(tmp_path, monkeypatch, {"greenhouse": Careless([ad("a"), ad("b")])})
    stage = staging.read_run(tmp_path, staging.list_runs(tmp_path)[0]).sources["greenhouse"]
    assert stage.footer["mismatch"] is True and stage.footer["written"] == "as it went"


def test_a_run_whose_staging_cannot_start_commits_nothing_and_says_so_in_its_record(tmp_path, monkeypatch):
    (tmp_path / "data/jobs").mkdir(parents=True)
    (tmp_path / "data/jobs/staging").write_text("in the way")
    assert discover(tmp_path, monkeypatch, {"greenhouse": Fake([ad("a")])}) == 1
    assert not (tmp_path / "data/jobs/discovered_jobs.json").exists()
    record = max(run_log.runs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
    issues = json.loads(record.read_text())["issues"]
    assert any(i["level"] == "warning" and "Staging is off" in i["message"] for i in issues)
    assert any(i["level"] == "error" and "Nothing was imported" in i["message"] for i in issues)


def test_the_run_keeps_the_ledger_it_started_from(tmp_path, monkeypatch):
    discover(tmp_path, monkeypatch, {"greenhouse": Fake([ad("a")])})
    first = (tmp_path / "data/jobs/job_history.json").read_bytes()
    discover(tmp_path, monkeypatch, {"greenhouse": Fake([ad("a"), ad("b")])})
    second_run = staging.list_runs(tmp_path)[0]
    kept = staging.read_run(tmp_path, second_run).ledger_before
    assert kept is not None and kept.read_bytes() == first
    assert (tmp_path / "data/jobs/job_history.json").read_bytes() != first


# --- Infostud's reported total, and a scrape that reads the ledger only ---------------------------------------------


def test_infostud_reports_its_total_to_the_footer(tmp_path, monkeypatch):
    row = {"jobId": "i1", "provider": "infostud", "source": "infostud", "site": "infostud", "title": "Product Manager",
           "company": "A", "location": "Beograd, Serbia", "jobUrl": "https://i.example/1", "description": "d", "isRemote": False}
    monkeypatch.setattr(infostud_client, "fetch_raw", lambda categories=None: ([{"id": 1}] * 1, 250))
    monkeypatch.setattr(infostud_client, "normalize", lambda r: dict(row))
    monkeypatch.setattr(infostud_client, "enrich", lambda job, delay=1.0: job)
    monkeypatch.setattr(infostud_client, "is_relevant_role", lambda *a: True)
    provider = infostud_provider.InfostudProvider()
    assert discover(tmp_path, monkeypatch, {"infostud": provider}) == 0
    footer = staging.read_run(tmp_path, staging.list_runs(tmp_path)[0]).sources["infostud"].footer
    assert footer["total"] == 250 and footer["read"] == 1


def test_a_scrape_never_renames_a_ledger_it_cannot_read(tmp_path):
    ledger = tmp_path / "job_history.json"
    ledger.write_text("{not json")
    assert job_history.load(ledger, read_only=True)["jobs"] == {}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["job_history.json"] and ledger.read_text() == "{not json"
    job_history.load(ledger)  # the committing run still sets it aside, as it always did
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("job_history.json.corrupt-")]


def test_joberty_reads_a_corrupt_ledger_without_touching_it(tmp_path):
    ledger = tmp_path / "job_history.json"
    ledger.write_bytes(b"\x00\x01 not a ledger")
    assert joberty_provider.known_ids(ledger) == set()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["job_history.json"]
    assert ledger.read_bytes() == b"\x00\x01 not a ledger"


def test_joberty_still_skips_the_detail_of_an_ad_the_ledger_already_holds(tmp_path):
    ledger = tmp_path / "job_history.json"
    job_history.save(ledger, {"version": 1, "updatedAt": None, "jobs": {
        "j1": {"job": {"description": "x" * 400}}, "j2": {"job": {"description": "short"}},
    }})
    assert joberty_provider.known_ids(ledger) == {"j1"}
