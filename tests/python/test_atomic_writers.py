"""The writers of data/jobs/*.json that have no test file of their own: a failed write keeps the old file and leaves no temp file."""

import json
import stat

import pytest

import export_jobs
import run_tailor
from conftest import fail_replacing


def _normalized(root):
    return export_jobs.export_normalized_json([{"jobId": "é"}], root)


def _discovered(root):
    return export_jobs.export_discovered_json(
        [{"jobId": "é"}], root, search_terms=[], locations=[], remote_filters=[], raw_count=1)


@pytest.mark.parametrize("export, name", [(_normalized, "normalized_jobs.json"), (_discovered, "discovered_jobs.json")])
def test_a_failed_export_keeps_the_previous_file_and_leaves_no_temp_file(tmp_path, monkeypatch, export, name):
    jobs = tmp_path / "data" / "jobs"
    jobs.mkdir(parents=True)
    target = jobs / name
    target.write_text('{"previous": true}', encoding="utf-8")
    temps = fail_replacing(monkeypatch, target)

    with pytest.raises(OSError, match="disk full"):
        export(tmp_path)

    assert temps and temps[0].endswith(".tmp")
    assert target.read_text(encoding="utf-8") == '{"previous": true}'
    assert [p.name for p in jobs.iterdir()] == [name]


@pytest.mark.parametrize("export", [_normalized, _discovered])
def test_an_export_keeps_its_bytes_and_the_files_mode(tmp_path, export):
    first = export(tmp_path)
    first.chmod(0o640)
    assert export(tmp_path) == first
    text = first.read_bytes().decode("utf-8")
    assert text == json.dumps(json.loads(text), indent=2)  # no trailing newline, non-ASCII escaped
    assert stat.S_IMODE(first.stat().st_mode) == 0o640


@pytest.fixture
def tailor(tmp_path, monkeypatch):
    """run_tailor.main() on temp files, with the tailoring itself replaced; the scored file has a directory of its own."""
    (tmp_path / "profile.json").write_text("{}")
    (tmp_path / "intel.json").write_text("{}")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    scored = jobs / "scored_jobs.json"
    scored.write_text(json.dumps({"meta": {}, "jobs": [{"jobId": "a", "title": "é"}]}), encoding="utf-8")
    monkeypatch.setattr(run_tailor, "tailor_job", lambda job, *a, **k: {**job, "tailoredAssets": {"contentEngine": "rule"}})
    monkeypatch.setattr("sys.argv", ["run_tailor.py", "--job-id", "a", "--no-llm", "--scored", str(scored),
                                     "--profile", str(tmp_path / "profile.json"), "--intelligence", str(tmp_path / "intel.json")])
    return scored


def test_a_failed_tailor_write_keeps_the_previous_scored_file_and_leaves_no_temp_file(tailor, monkeypatch):
    before = tailor.read_bytes()
    temps = fail_replacing(monkeypatch, tailor)

    with pytest.raises(OSError, match="disk full"):
        run_tailor.main()

    assert temps and temps[0].endswith(".tmp")
    assert tailor.read_bytes() == before
    assert [p.name for p in tailor.parent.iterdir()] == ["scored_jobs.json"]


def test_a_tailor_write_keeps_its_bytes_and_the_files_mode(tailor):
    tailor.chmod(0o640)
    assert run_tailor.main() == 0
    text = tailor.read_bytes().decode("utf-8")
    assert text == json.dumps(json.loads(text), indent=2)
    assert json.loads(text)["jobs"][0]["tailoredAssets"] == {"contentEngine": "rule"}
    assert stat.S_IMODE(tailor.stat().st_mode) == 0o640
