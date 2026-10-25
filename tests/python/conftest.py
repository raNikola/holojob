"""Pytest path setup for Career OS Python modules."""

import sys
from pathlib import Path

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


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: hits a live third-party site; skipped when unreachable"
    )
