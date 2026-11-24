"""The Jobs screen's Active period (owner decision 2026-11-24): a Settings field, whole days 1..365, default 14 written in one place.

Runs against the tmp data/ai the autouse fixture in conftest.py sets up.
"""

import json

import pytest

import ai_gate


def stored():
    return json.loads(ai_gate.settings_path().read_text())


def test_the_active_period_defaults_to_14_days_in_one_place():
    assert ai_gate.DEFAULT_SETTINGS["activeWindowDays"] == 14
    assert ai_gate.usage_summary()["settings"]["activeWindowDays"] == 14


@pytest.mark.parametrize("days", [1, 14, 90, 365])
def test_the_active_period_round_trips_with_no_confirm(days):
    # A longer or shorter list is not a spend loosening: nothing to confirm.
    result = ai_gate.save_settings({"activeWindowDays": days})
    assert result["ok"] and not result.get("needsConfirm")
    assert stored()["activeWindowDays"] == days
    assert ai_gate.usage_summary()["settings"]["activeWindowDays"] == days
    assert ai_gate.load_settings()["activeWindowDays"] == days


@pytest.mark.parametrize("days", [0, -1, 366, 1.5, "14", None, True, float("nan")])
def test_a_bad_active_period_is_rejected_and_nothing_is_written(days):
    result = ai_gate.save_settings({"activeWindowDays": days}, confirm=True)
    assert result["ok"] is False and any("activeWindowDays" in line for line in result["errors"])
    assert not ai_gate.settings_path().exists()
