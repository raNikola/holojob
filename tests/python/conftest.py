"""Pytest path setup for Holojob Python modules."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Insert in reverse so job_scoring (last) wins import precedence over resume_generator.
for sub in ("job_discovery", "resume_generator", "job_scoring", "cv_analysis"):
    path = ROOT / "python" / sub
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# match_engine is a package: python/ itself goes last, so none of its folders
# shadows a flat module above.
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))


@pytest.fixture(autouse=True)
def _requirement_frames_in_tmp(tmp_path, monkeypatch):
    """No test reads or writes the server's data/cache/requirement-frames.json."""
    import requirement_frames

    monkeypatch.setattr(requirement_frames, "FRAMES_PATH", tmp_path / "requirement-frames.json")


@pytest.fixture(autouse=True)
def _competency_files_in_tmp(tmp_path, monkeypatch):
    """No test reads or writes the server's learned aliases or remap table."""
    import competency_mapping

    monkeypatch.setattr(competency_mapping, "ALIASES_PATH", tmp_path / "competency-aliases.json")
    monkeypatch.setattr(competency_mapping, "REMAP_PATH", tmp_path / "requirement-remap.json")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: hits a live third-party site; skipped when unreachable"
    )
