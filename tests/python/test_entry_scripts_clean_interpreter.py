"""Every Python entry script that the Node side or an orchestrator starts by path must import in a clean interpreter.

The defect class (package 13): rescore_kept.py imported a sibling package that only pytest's own path setup made importable; in the container, where the
route starts `python <path>`, it died on import. Here each script is loaded in `python -I` (no PYTHONPATH, no user site, no cwd on the path), as the route
starts it, with only its own directory on the path (what `python <path>` adds), under a name other than __main__ so no main() runs. Nothing is read from data/.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE_PATH = re.compile(r"""['"](python/[A-Za-z0-9_/]+\.py)['"]""")
ORCHESTRATED = [
    "python/job_discovery/run_discovery.py", "python/job_scoring/enrich_jobs.py", "python/job_scoring/classify_new.py",
    "python/job_scoring/run_scoring.py", "python/resume_generator/run_tailor.py", "python/run_pipeline.py", "python/run_rescrape.py",
]


def entry_scripts() -> list[str]:
    found = set(ORCHESTRATED)
    for js in (ROOT / "scripts").glob("*.js"):
        found.update(NODE_PATH.findall(js.read_text(encoding="utf-8")))
    return sorted(p for p in found if (ROOT / p).is_file() and '__name__ == "__main__"' in (ROOT / p).read_text(encoding="utf-8"))


LOADER = (
    "import runpy, sys\n"
    "script = sys.argv[1]\n"
    "sys.path.insert(0, script.rsplit('/', 1)[0])\n"  # what `python <path>` puts first
    "runpy.run_path(script, run_name='entry_import_check')\n"
)


def test_the_check_sees_the_scripts_it_is_about():
    scripts = entry_scripts()
    assert "python/job_scoring/classify_new.py" in scripts and "python/job_scoring/rescore_kept.py" in scripts and "python/run_pipeline.py" in scripts
    assert len(scripts) >= 15


@pytest.mark.parametrize("script", entry_scripts())
def test_an_entry_script_imports_in_a_clean_interpreter(script, tmp_path):
    result = subprocess.run([sys.executable, "-I", "-c", LOADER, str(ROOT / script)], cwd=tmp_path, capture_output=True, text=True, timeout=60,
                            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert result.returncode == 0, f"{script} does not import in a clean interpreter:\n{result.stderr[-600:]}"
