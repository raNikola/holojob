"""The JobSpy version is pinned and the private LinkedIn detail call keeps the shape package 14 relies on.

LinkedIn descriptions come from `LinkedIn._fetch_details(job_id)`, called once per search card inside `_process_job` when
`fetch_description` is on. A JobSpy upgrade that renames or reshapes it would silently empty every LinkedIn description
(the title filter then treats them as unknown and keeps them), so the pin and the shape are checked.
"""

import inspect
import re
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINNED = "1.4.0"


def test_both_requirement_files_pin_the_installed_jobspy():
    for rel in ("requirements.txt", "python/job_discovery/requirements.txt"):
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        pins = [ln.strip() for ln in lines if re.match(r"python-jobspy\b", ln.strip())]
        assert pins == [f"python-jobspy=={PINNED}"], rel
    assert metadata.version("python-jobspy") == PINNED


def test_linkedin_detail_call_has_the_pinned_shape():
    from jobspy.linkedin import LinkedIn

    params = list(inspect.signature(LinkedIn._fetch_details).parameters)
    assert params == ["self", "job_id"]
    assert "self._fetch_details(job_id)" in inspect.getsource(LinkedIn._process_job)
