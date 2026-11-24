"""The Jobs list page size (owner decision 2026-11-24): a Settings field, whole ads 1..1000, its default written once in ai_gate.DEFAULT_SETTINGS.

Runs against the tmp data/ai the autouse fixture in conftest.py sets up.
"""

import json

import pytest

import ai_gate


def stored():
    return json.loads(ai_gate.settings_path().read_text())


def test_the_page_size_has_one_default_and_it_is_the_one_the_server_reports():
    assert isinstance(ai_gate.DEFAULT_SETTINGS["jobsPageSize"], int)
    assert ai_gate.usage_summary()["settings"]["jobsPageSize"] == ai_gate.DEFAULT_SETTINGS["jobsPageSize"]


@pytest.mark.parametrize("size", [1, 25, 100, 1000])
def test_the_page_size_round_trips_with_no_confirm(size):
    # A page size is not a spend loosening: nothing to confirm.
    result = ai_gate.save_settings({"jobsPageSize": size})
    assert result["ok"] and not result.get("needsConfirm")
    assert stored()["jobsPageSize"] == size
    assert ai_gate.usage_summary()["settings"]["jobsPageSize"] == size
    assert ai_gate.load_settings()["jobsPageSize"] == size


@pytest.mark.parametrize("size", [0, -1, 1001, 1.5, "100", None, True, float("nan")])
def test_a_bad_page_size_is_rejected_and_nothing_is_written(size):
    result = ai_gate.save_settings({"jobsPageSize": size}, confirm=True)
    assert result["ok"] is False and any("jobsPageSize" in line for line in result["errors"])
    assert not ai_gate.settings_path().exists()
