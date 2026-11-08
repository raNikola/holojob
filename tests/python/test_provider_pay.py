"""Pay a board states in structured fields, written so salary.py can read it. Nothing is filled in."""

import pytest

from providers.ashby_provider import AshbyProvider
from providers.base_provider import format_pay_range
from providers.lever_provider import LeverProvider
from salary import parse_monthly_eur


def test_a_range_with_its_period_and_currency():
    assert format_pay_range(120000, 150000.0, "yearly", "eur") == "120000 - 150000 yearly EUR"


def test_one_figure():
    assert format_pay_range(5000, 5000, "monthly", "EUR") == "5000 monthly EUR"
    assert format_pay_range(None, 5000, "monthly", "EUR") == "5000 monthly EUR"


@pytest.mark.parametrize("low, high, currency", [(None, None, "EUR"), (0, 0, "EUR"), (100, 200, ""), (100, 200, None), ("100", "200", "EUR")])
def test_nothing_is_invented(low, high, currency):
    assert format_pay_range(low, high, "yearly", currency) == ""


@pytest.mark.parametrize(
    "interval, text",
    [("per-year-salary", "60000 - 72000 yearly EUR"), ("per-month-salary", "60000 - 72000 monthly EUR"), ("per-hour-wage", "60000 - 72000 hourly EUR"), ("one-time", "60000 - 72000 EUR")],
)
def test_lever_salary_range(interval, text):
    assert LeverProvider._format_salary({"currency": "EUR", "interval": interval, "min": 60000, "max": 72000}) == text


def test_lever_posting_carries_it():
    job = LeverProvider()._normalize_posting(
        {"text": "PM", "hostedUrl": "https://x.example/1", "salaryRange": {"currency": "EUR", "interval": "per-year-salary", "min": 60000, "max": 72000}}, "acme", "", ""
    )
    assert job["salary"] == "60000 - 72000 yearly EUR"
    assert parse_monthly_eur(job["salary"]) == {"min": 5000, "max": 6000, "currency": "EUR", "converted": False}


def test_lever_no_range_no_pay():
    assert LeverProvider._format_salary(None) == ""


def _component(**over):
    return {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "EUR", "minValue": 60000, "maxValue": 72000, **over}


def test_ashby_prefers_the_salary_component():
    compensation = {"compensationTierSummary": "€60K – €72K", "summaryComponents": [{**_component(compensationType="EquityPercentage")}, _component()]}
    assert AshbyProvider()._format_salary(compensation) == "60000 - 72000 yearly EUR"


def test_ashby_a_component_without_a_currency_is_not_guessed():
    compensation = {"compensationTierSummary": "60K – 72K", "summaryComponents": [_component(currencyCode=None)]}
    assert AshbyProvider()._format_salary(compensation) == "60K – 72K"


def test_ashby_no_compensation():
    assert AshbyProvider()._format_salary(None) == ""
