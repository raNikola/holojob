"""The inspection helper shows shape, counts and hashes, and never a value."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "inspect-private-data.py"
CANARY = "Canaryemployer"


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def write(tmp_path, content, name="private.json"):
    file = tmp_path / name
    file.write_text(content, encoding="utf-8")
    return file


def payload():
    return {
        "atsKeywordBank": {"mediumPriority": ["Short", f"{CANARY} led a team of forty people across the whole product"]},
        "basicProfile": {"fullName": CANARY, "years": 12},
        CANARY: {"role": CANARY},
    }


def test_no_value_and_no_odd_key_reaches_the_output(tmp_path):
    result = run(write(tmp_path, json.dumps(payload())))
    assert result.returncode == 0
    assert CANARY.lower() not in (result.stdout + result.stderr).lower()


def test_it_reports_shape_and_counts(tmp_path):
    out = run(write(tmp_path, json.dumps(payload()))).stdout
    line = next(row for row in out.splitlines() if row.startswith("atsKeywordBank.mediumPriority\t"))
    assert "list" in line and "size=2" in line and "longestWords=11" in line and "sha=" in line
    assert any(row.startswith("<key2>\t") for row in out.splitlines())


def test_depth_limits_the_listing(tmp_path):
    out = run(write(tmp_path, json.dumps(payload())), "--depth", "0").stdout
    assert len(out.splitlines()) == 2


def test_a_file_that_is_not_json_gives_size_and_hash_only(tmp_path):
    result = run(write(tmp_path, f"{CANARY} worked here", "cv.txt"))
    assert result.returncode == 0
    assert "bytes=" in result.stdout and "sha=" in result.stdout
    assert CANARY not in result.stdout + result.stderr


def test_broken_json_does_not_quote_the_file(tmp_path):
    result = run(write(tmp_path, '{"a": "' + CANARY))
    assert CANARY not in result.stdout + result.stderr


def test_a_missing_file_is_a_plain_error(tmp_path):
    result = run(tmp_path / "nothing.json")
    assert result.returncode == 1 and "Traceback" not in result.stderr
