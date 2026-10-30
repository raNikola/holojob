"""Opt-in sources (Joberty): off unless the owner switched them on with consent, stored server-side."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import run_discovery
import source_settings
from providers.provider_registry import PROVIDER_CLASSES
from source_definitions import PROVIDER_GROUPS, SOURCE_DEFINITIONS, opt_in_names

SERBIA = PROVIDER_GROUPS["serbia"]
T1 = "2026-10-30T10:00:00+00:00"
T2 = "2026-10-30T11:00:00+00:00"
T3 = "2026-10-30T12:00:00+00:00"


def path():
    return source_settings.sources_path()


def on_disk():
    return json.loads(path().read_text())


def joberty_row(result):
    return next(b for b in result["boards"] if b["name"] == "joberty")


def enable(at=T1):
    return source_settings.save({"joberty": {"active": True, "consentAccepted": True}}, now=at)


# --- definitions -----------------------------------------------------------

def test_every_registered_provider_has_a_definition_and_joberty_is_the_opt_in_one():
    assert set(SOURCE_DEFINITIONS) == set(PROVIDER_CLASSES)
    assert opt_in_names() == ["joberty"]
    assert all(d.opt_in is False for n, d in SOURCE_DEFINITIONS.items() if n != "joberty")


def test_no_opt_in_source_is_in_any_group():
    assert not any(set(opt_in_names()) & set(members) for members in PROVIDER_GROUPS.values())


# --- default off -----------------------------------------------------------

def test_with_no_settings_file_joberty_is_off_and_not_in_the_standard_run():
    assert not path().exists()
    assert joberty_row(source_settings.get())["active"] is False
    assert run_discovery.effective_provider_names("serbia") == SERBIA
    assert run_discovery.effective_provider_names(None) == SERBIA
    assert not path().exists(), "reading must not create the file"


def test_off_even_when_the_request_names_it():
    assert run_discovery.effective_provider_names("joberty") == []
    assert run_discovery.effective_provider_names("serbia,joberty") == SERBIA
    assert run_discovery.effective_provider_names("jobspy,joberty") == ["jobspy"]


def test_an_entry_without_consent_is_off_even_if_it_says_active():
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps({"version": 1, "boards": {"joberty": {"active": True, "consentAcceptedAt": None}}}))
    assert run_discovery.effective_provider_names("serbia,joberty") == SERBIA


@pytest.mark.parametrize("content", ["{not json", json.dumps({"version": 99, "boards": {}}), json.dumps([1])])
def test_an_unusable_file_means_off_and_is_left_as_it_is(content):
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(content)
    assert run_discovery.effective_provider_names("serbia,joberty") == SERBIA
    assert "error" in source_settings.get()
    assert source_settings.save({"joberty": {"active": False}})["ok"] is False
    assert enable()["ok"] is False
    assert path().read_text() == content


# --- consent and switching -------------------------------------------------

def test_turning_on_without_consent_is_refused_and_writes_nothing():
    result = source_settings.save({"joberty": {"active": True}})
    assert result == {"ok": False, "needsConsent": ["joberty"]}
    assert not path().exists()


def test_enabled_joberty_joins_the_standard_run():
    assert enable()["ok"] is True
    assert run_discovery.effective_provider_names("serbia") == SERBIA + ["joberty"]
    assert run_discovery.effective_provider_names("joberty") == ["joberty"]
    # A run that lists names only gets those names.
    assert run_discovery.effective_provider_names("jobspy") == ["jobspy"]


def test_consent_is_stored_server_side_with_the_server_time_and_a_private_file():
    enable(T1)
    entry = on_disk()["boards"]["joberty"]
    assert entry["active"] is True and entry["consentAcceptedAt"] == T1
    assert entry["history"] == [{"at": T1, "event": "enabled", "consentAcceptedAt": T1}]
    assert stat.S_IMODE(os.stat(path()).st_mode) == 0o600


def test_a_consent_time_sent_by_the_client_is_ignored():
    source_settings.save({"joberty": {"active": True, "consentAccepted": True, "consentAcceptedAt": "1999-01-01"}}, now=T1)
    assert on_disk()["boards"]["joberty"]["consentAcceptedAt"] == T1


def test_turning_off_keeps_the_consent_time_and_history_and_turning_on_again_asks_again():
    enable(T1)
    assert source_settings.save({"joberty": {"active": False}}, now=T2)["ok"]
    entry = on_disk()["boards"]["joberty"]
    assert entry["active"] is False and entry["consentAcceptedAt"] == T1 and entry["disabledAt"] == T2
    assert [h["event"] for h in entry["history"]] == ["enabled", "disabled"]
    assert run_discovery.effective_provider_names("serbia") == SERBIA

    assert source_settings.save({"joberty": {"active": True}}, now=T3) == {"ok": False, "needsConsent": ["joberty"]}
    enable(T3)
    entry = on_disk()["boards"]["joberty"]
    assert entry["consentAcceptedAt"] == T3
    assert [h["event"] for h in entry["history"]] == ["enabled", "disabled", "enabled"]


def test_saving_an_already_enabled_source_keeps_its_consent():
    enable(T1)
    assert source_settings.save({"joberty": {"active": True}}, now=T2)["ok"]
    assert on_disk()["boards"]["joberty"]["consentAcceptedAt"] == T1


@pytest.mark.parametrize("boards", [{"jobspy": {"active": False}}, {"nonsense": {"active": True}},
                                    {"joberty": {"active": "yes"}}, {}, None])
def test_invalid_changes_are_refused(boards):
    assert source_settings.save(boards)["ok"] is False
    assert not path().exists()


# --- legacy migration ------------------------------------------------------

@pytest.mark.parametrize("value", [None, {}, {"includeJoberty": False}, {"includeJoberty": "true"}, "x"])
def test_migration_never_switches_joberty_on_by_itself(value):
    result = source_settings.migrate_legacy(value, now=T1)
    assert result["ok"] and result["migrated"] is False
    assert run_discovery.effective_provider_names("serbia") == SERBIA


def test_a_ticked_old_checkbox_is_moved_once_with_the_migration_time_as_consent():
    result = source_settings.migrate_legacy({"includeJoberty": True}, now=T1)
    assert result["migrated"] is True
    entry = on_disk()["boards"]["joberty"]
    assert entry["active"] is True and entry["consentAcceptedAt"] == T1
    assert entry["migratedFrom"] == "job-dashboard-discovery-options"
    assert "checkbox" in entry["history"][0]["note"]
    assert on_disk()["migrations"]["job-dashboard-discovery-options"] == T1
    assert run_discovery.effective_provider_names("serbia") == SERBIA + ["joberty"]

    # Once: after the owner switched it off, a second hand-over changes nothing.
    source_settings.save({"joberty": {"active": False}}, now=T2)
    assert source_settings.migrate_legacy({"includeJoberty": True}, now=T3)["migrated"] is False
    assert on_disk()["boards"]["joberty"]["active"] is False


def test_migration_does_not_override_a_decision_the_server_already_holds():
    enable(T1)
    source_settings.save({"joberty": {"active": False}}, now=T2)
    assert source_settings.migrate_legacy({"includeJoberty": True}, now=T3)["migrated"] is False
    assert on_disk()["boards"]["joberty"]["active"] is False


# --- the CLI the Node API runs ---------------------------------------------

def cli(command, payload=None):
    script = Path(source_settings.__file__)
    done = subprocess.run([sys.executable, str(script), command], input=json.dumps(payload) if payload else "",
                          capture_output=True, text=True, env={**os.environ}, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_cli_reads_writes_and_never_reads_a_consent_time_from_the_request():
    assert joberty_row(cli("get"))["active"] is False
    assert cli("put", {"boards": {"joberty": {"active": True}}}) == {"ok": False, "needsConsent": ["joberty"]}
    saved = cli("put", {"boards": {"joberty": {"active": True, "consentAccepted": True, "consentAcceptedAt": "1999"}}})
    assert joberty_row(saved)["active"] is True
    assert joberty_row(saved)["consentAcceptedAt"].startswith("20") and joberty_row(saved)["consentAcceptedAt"] != "1999"
    assert cli("migrate-legacy", {"value": {"includeJoberty": True}})["migrated"] is False
    assert cli("put", "not an object")["ok"] is False


def test_discovery_applies_the_switches_before_it_runs_any_provider():
    source = Path(run_discovery.__file__).read_text()
    main = source[source.index("def main()"):]
    assert "provider_names = effective_provider_names(args.providers)" in main
    assert "resolve_providers(args.providers)" not in main
