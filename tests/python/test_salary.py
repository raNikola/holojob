"""Salary is display metadata: parsed from the ad's pay text, compared with the
profile's minimum, and kept out of every score field."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from salary import below_minimum, minimum_salary, parse_monthly_eur, salary_metadata
from scorer import score_job

ROOT = Path(__file__).resolve().parents[2]
RUN_SCORING = ROOT / "python" / "job_scoring" / "run_scoring.py"

# Pay strings in the shapes discovery writes today: JobSpy's "<min> - <max>
# <interval> [currency]" (USD is left off by normalize_jobs), and an Ashby
# summary, which is whatever the company typed.
REAL_FORMATS = [
    ("75000 - 85000 yearly EUR", {"min": 6250, "max": 7083}),
    ("49000 - 90000 yearly EUR", {"min": 4083, "max": 7500}),
    ("1500 - 3000 monthly EUR", {"min": 1500, "max": 3000}),
    ("€4,000 - €5,000 / month", {"min": 4000, "max": 5000}),
    ("EUR 4.500 per month", {"min": 4500, "max": 4500}),
]

UNKNOWN = [
    "115000 - 145000 yearly GBP",
    "92900 - 209500 yearly",       # USD is dropped by the formatter: no currency, no guess
    "$120,000 - $150,000 per year",
    "€80K – €100K",                # no interval
    "3000 EUR",
    "€50 per hour",
    "up to €5000 per month",
    "€2000 - €3000 monthly or £50000 yearly",
    "",
    None,
    1234,
]


@pytest.mark.parametrize("text, expected", REAL_FORMATS)
def test_parses_the_formats_in_the_data(text, expected):
    assert parse_monthly_eur(text) == expected


@pytest.mark.parametrize("text", UNKNOWN)
def test_unknown_currency_or_interval_is_unknown_never_a_guess(text):
    assert parse_monthly_eur(text) is None


def test_below_minimum_compares_the_top_of_the_range():
    pay = {"min": 1500, "max": 3000}
    assert below_minimum(pay, 3500) is True
    assert below_minimum(pay, 2500) is False  # the range reaches the floor
    assert below_minimum(None, 2500) is None
    assert below_minimum(pay, None) is None


def test_minimum_salary_unset_or_invalid_is_none():
    assert minimum_salary({}) is None
    assert minimum_salary({"jobFitPreferences": {"minSalaryEur": None}}) is None
    assert minimum_salary({"jobFitPreferences": {"minSalaryEur": 0}}) is None
    assert minimum_salary({"jobFitPreferences": {"minSalaryEur": "abc"}}) is None
    assert minimum_salary({"jobFitPreferences": {"minSalaryEur": 2500}}) == 2500


@pytest.fixture
def intelligence():
    return json.loads((ROOT / "data" / "examples" / "candidate-intelligence.example.json").read_text())


def _job(salary):
    return {
        "jobId": "s-1", "title": "Senior Product Manager", "company": "Example Corp",
        "location": "Berlin, Germany", "description": "Own the roadmap for a payments product.",
        "salary": salary,
    }


def _with_min(intelligence, minimum):
    prefs = {**(intelligence.get("jobFitPreferences") or {}), "minSalaryEur": minimum}
    return {**intelligence, "jobFitPreferences": prefs}


SALARY_KEYS = {"salaryMonthlyEur", "belowMinSalary"}


@pytest.mark.parametrize("salary", ["75000 - 85000 yearly EUR", "1500 - 3000 monthly EUR", "92900 - 209500 yearly", ""])
def test_the_flag_never_touches_score_label_priority_or_recommendation(intelligence, salary):
    unset = score_job(_job(salary), _with_min(intelligence, None))
    low = score_job(_job(salary), _with_min(intelligence, 1))
    high = score_job(_job(salary), _with_min(intelligence, 1_000_000))

    for other in (low, high):
        assert {k: v for k, v in other.items() if k not in SALARY_KEYS} == \
               {k: v for k, v in unset.items() if k not in SALARY_KEYS}
    for field in ("matchScore", "matchLabel", "priority", "applyRecommendation", "redFlags", "hardCapped", "reasons"):
        assert unset[field] == high[field] == low[field]
    assert not any("salary" in str(r).lower() for r in high["redFlags"] + high["reasons"])


def test_flag_values_follow_the_minimum(intelligence):
    assert score_job(_job("1500 - 3000 monthly EUR"), _with_min(intelligence, 3500))["belowMinSalary"] is True
    assert score_job(_job("1500 - 3000 monthly EUR"), _with_min(intelligence, 2500))["belowMinSalary"] is False
    assert score_job(_job("1500 - 3000 monthly EUR"), _with_min(intelligence, None))["belowMinSalary"] is None
    assert score_job(_job("92900 - 209500 yearly"), _with_min(intelligence, 3500))["belowMinSalary"] is None
    assert salary_metadata(_job(""), _with_min(intelligence, 3500)) == {"salaryMonthlyEur": None, "belowMinSalary": None}


def _score_run(tmp_path, intelligence, jobs, name):
    intel = tmp_path / f"{name}-intel.json"
    out = tmp_path / f"{name}-out.json"
    intel.write_text(json.dumps(intelligence))
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({"jobs": jobs}))
    done = subprocess.run(
        [sys.executable, str(RUN_SCORING), "--intelligence", str(intel), "--jobs", str(jobs_file), "--output", str(out)],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    return {j["jobId"]: j for j in json.loads(out.read_text())["jobs"]}


def test_changing_the_minimum_takes_effect_on_a_rescore_of_the_same_jobs(tmp_path, intelligence):
    """No discovery in between: the same jobs file, a different minimum."""
    jobs = [_job("1500 - 3000 monthly EUR")]
    before = _score_run(tmp_path, _with_min(intelligence, 2000), jobs, "a")["s-1"]
    after = _score_run(tmp_path, _with_min(intelligence, 5000), jobs, "b")["s-1"]

    assert before["belowMinSalary"] is False
    assert after["belowMinSalary"] is True
    for field in ("matchScore", "matchLabel", "priority", "applyRecommendation"):
        assert before[field] == after[field]
