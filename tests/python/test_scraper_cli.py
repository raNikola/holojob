"""The LinkedIn scraper takes its cookie from the environment, never from argv (BROWSER_STORAGE_POLICY, step 3).

Real process, no network and no browser: both paths stop before Playwright starts.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "python/outreach_scraper/scrape_linkedin_contacts.py"
COOKIE = "LI-CANARY-5d2e8b9a41"


def run(*args, env=None):
    clean = {k: v for k, v in os.environ.items() if k != "LINKEDIN_LI_AT"}
    clean.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=clean, capture_output=True, text=True, timeout=60)


def test_li_at_is_no_longer_a_command_line_option():
    result = run("--company", "Acme", "--mode", "deep", "--i-accept-tos-risk", "--li-at", COOKIE)
    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr


def test_deep_mode_without_the_variable_stops_with_a_fixed_message():
    result = run("--company", "Acme", "--mode", "deep", "--i-accept-tos-risk")
    error = json.loads(result.stdout.strip().splitlines()[-1])["error"]
    assert "LINKEDIN_LI_AT" in error
    assert COOKIE not in result.stdout + result.stderr
