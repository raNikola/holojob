"""Per-source on/off switches for the sources that follow the provider groups (and the one-off "not this time")."""

import json
import sys

import pytest
import requests

import run_discovery
import run_log
import source_settings
from providers import ashby_provider, lever_provider
from source_definitions import PROVIDER_GROUPS, SOURCE_DEFINITIONS

SERBIA = PROVIDER_GROUPS["serbia"]
T1 = "2026-11-09T10:00:00+00:00"
T2 = "2026-11-09T11:00:00+00:00"
GROUP_SOURCES = [n for n, d in SOURCE_DEFINITIONS.items() if not d.opt_in]


def on_disk():
    return json.loads(source_settings.sources_path().read_text())


def row(result, name):
    return next(b for b in result["boards"] if b["name"] == name)


def test_every_group_source_is_on_by_default_and_reading_creates_no_file():
    result = source_settings.get()
    assert all(row(result, n)["active"] is True for n in GROUP_SOURCES)
    assert not source_settings.sources_path().exists()


@pytest.mark.parametrize("name", GROUP_SOURCES)
def test_each_group_source_can_be_switched_off_and_on_without_consent(name):
    saved = source_settings.save({name: {"active": False}}, now=T1)
    assert saved["ok"] and row(saved, name)["active"] is False
    assert on_disk()["boards"][name]["active"] is False
    assert all(row(saved, n)["active"] for n in GROUP_SOURCES if n != name)
    again = source_settings.save({name: {"active": True}}, now=T2)
    assert again["ok"] and row(again, name)["active"] is True
    assert [h["event"] for h in on_disk()["boards"][name]["history"]] == ["disabled", "enabled"]


def test_saving_the_current_state_changes_nothing_and_writes_no_entry():
    assert source_settings.save({"jobspy": {"active": True}}, now=T1)["ok"]
    assert "jobspy" not in on_disk()["boards"]


def test_a_group_source_switch_leaves_joberty_consent_alone():
    source_settings.save({"joberty": {"active": True, "consentAccepted": True}}, now=T1)
    source_settings.save({"jobspy": {"active": False}}, now=T2)
    assert on_disk()["boards"]["joberty"]["consentAcceptedAt"] == T1


def test_a_switched_off_source_is_skipped_with_its_reason_and_the_others_run():
    source_settings.save({"jobspy": {"active": False}}, now=T1)
    kept, skipped = run_discovery.apply_owner_skips(list(SERBIA), [])
    assert kept == [n for n in SERBIA if n != "jobspy"]
    assert skipped == [("jobspy", source_settings.SKIP_SWITCH)]
    assert "skipped by owner" in skipped[0][1]


def test_the_one_off_exclude_skips_without_saving():
    kept, skipped = run_discovery.apply_owner_skips(list(SERBIA), ["jobspy"])
    assert "jobspy" not in kept and skipped == [("jobspy", source_settings.SKIP_THIS_RUN)]
    assert not source_settings.sources_path().exists()


def test_unreadable_settings_switch_nothing_off(tmp_path):
    source_settings.sources_path().parent.mkdir(parents=True, exist_ok=True)
    source_settings.sources_path().write_text("{not json")
    kept, skipped = run_discovery.apply_owner_skips(list(SERBIA), [])
    assert kept == SERBIA and skipped == []


# --- a run: skipped is not empty, not failed, and closes nothing ---------------------------------------------------


class Answer:
    def __init__(self, body):
        self.body, self.status_code = body, 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


ASHBY = lambda i: {"id": str(i), "title": f"Product Manager {i}", "location": "Remote", "jobUrl": f"https://a.example/{i}", "descriptionPlain": "Own the roadmap. " * 30}  # noqa: E731
LEVER = {"id": "1", "text": "Product Manager", "categories": {"location": "Remote"}, "hostedUrl": "https://l.example/1", "descriptionPlain": "Own the roadmap. " * 30}


def run(root, monkeypatch, *extra):
    monkeypatch.setattr(run_discovery, "ROOT", root)
    intelligence = root / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": ["product manager"], "locationFilters": ["Remote"], "remoteFilters": ["remote"]}}))
    providers = {"ashby": ashby_provider.AshbyProvider(), "lever": lever_provider.LeverProvider()}
    monkeypatch.setattr(ashby_provider.AshbyProvider, "_load_companies", lambda self: ["acme"])
    monkeypatch.setattr(lever_provider.LeverProvider, "_load_companies", lambda self: ["acme"])
    monkeypatch.setattr(requests, "get", lambda url, params=None, **_: Answer(
        {"jobs": [ASHBY(1)], "apiVersion": "1"} if "ashby" in url else ([] if params else [LEVER])))
    monkeypatch.setattr(run_discovery, "get_provider", lambda name: providers[name])
    monkeypatch.setattr(run_discovery, "effective_provider_names", lambda spec: list(providers))
    monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--providers", "x", "--intelligence", str(intelligence), *extra])
    before = set(run_log.runs_dir().iterdir()) if run_log.runs_dir().exists() else set()
    code = run_discovery.main()
    (new,) = [p for p in run_log.runs_dir().iterdir() if run_log.is_record_name(p.name) and p not in before]  # this run's record
    return code, json.loads(new.read_text()), json.loads((root / "data/jobs/job_history.json").read_text())


@pytest.mark.parametrize("how", ["switch", "one-off"])
def test_a_skipped_source_is_recorded_as_skipped_and_its_ads_stay_open(tmp_path, monkeypatch, how):
    root = tmp_path / "root"
    root.mkdir()
    code, _, first = run(root, monkeypatch)
    assert code == 0 and len(first["jobs"]) == 2
    extra = ()
    if how == "switch":
        source_settings.save({"lever": {"active": False}}, now=T1)
    else:
        extra = ("--exclude", "lever")
    for _ in range(3):
        code, record, ledger = run(root, monkeypatch, *extra)
        assert code == 0
        lever = next(s for s in record["sources"] if s["name"] == "lever")
        assert lever["status"] == "skipped" and lever["readClass"] == "skipped" and "skipped by owner" in lever["skipReason"]
        assert next(s for s in record["sources"] if s["name"] == "ashby")["status"] == "ok"
        assert record["status"] == "ok", "a skipped source does not make the run partial or failed"
        assert not any(e["closedAt"] or e.get("absentRuns") for e in ledger["jobs"].values()), "a skipped source closes and counts nothing"
    assert len(ledger["jobs"]) == 2
    view = json.loads((root / "data/jobs/discovered_jobs.json").read_text())
    assert len(view["jobs"]) == 2 and not any(j.get("isClosed") or j.get("isAbsent") for j in view["jobs"])


def test_every_source_switched_off_stops_with_a_clear_message_and_changes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    run(root, monkeypatch)
    before = (root / "data/jobs/job_history.json").read_text()
    source_settings.save({"ashby": {"active": False}, "lever": {"active": False}}, now=T1)
    code, record, _ = run(root, monkeypatch)
    assert code == 1 and "switched off" in json.dumps(record["issues"])
    assert (root / "data/jobs/job_history.json").read_text() == before


# --- files saved by older code: nothing the owner saved is reset, a missing key is on for that source only ----------

OLD_FILE = {
    "version": 1, "updatedAt": "2026-10-30T12:00:00+00:00",
    "boards": {
        "joberty": {"active": True, "consentAcceptedAt": "2026-10-30T12:00:00+00:00", "disabledAt": None,
                    "history": [{"at": "2026-10-30T12:00:00+00:00", "event": "enabled"}]},
        "infostud": {"active": False, "disabledAt": "2026-11-01T08:00:00+00:00"},  # an explicit owner switch
        "somefuturesource": {"active": False},                                      # an unknown key
    },
    "migrations": {"job-dashboard-discovery-options": "2026-10-30T12:00:00+00:00"},
}


def write_old(data=None):
    path = source_settings.sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(OLD_FILE if data is None else data))


def test_a_partial_old_file_turns_only_the_missing_sources_on():
    write_old()
    result = source_settings.get()
    assert row(result, "infostud")["active"] is False
    assert row(result, "joberty")["active"] is True
    assert all(row(result, n)["active"] for n in GROUP_SOURCES if n != "infostud")
    assert "somefuturesource" not in [b["name"] for b in result["boards"]]
    kept, skipped = run_discovery.apply_owner_skips(list(SERBIA), [])
    assert [n for n, _ in skipped] == ["infostud"] and "jobspy" in kept


def test_reading_and_discovery_never_rewrite_the_file():
    write_old()
    before = source_settings.sources_path().read_bytes()
    source_settings.get()
    run_discovery.effective_provider_names("serbia")
    run_discovery.apply_owner_skips(list(SERBIA), ["jobspy"])
    assert source_settings.sources_path().read_bytes() == before


def test_saving_one_source_keeps_every_other_saved_value_unknown_keys_included():
    write_old()
    assert source_settings.save({"jobspy": {"active": False}}, now=T2)["ok"]
    after = on_disk()
    assert after["boards"]["infostud"] == OLD_FILE["boards"]["infostud"]
    assert after["boards"]["joberty"] == OLD_FILE["boards"]["joberty"]
    assert after["boards"]["somefuturesource"] == {"active": False}
    assert after["migrations"] == OLD_FILE["migrations"]
    assert after["boards"]["jobspy"]["active"] is False


def test_saving_a_source_that_is_already_in_the_saved_state_changes_no_other_entry():
    write_old()
    assert source_settings.save({"infostud": {"active": False}, "workable": {"active": True}}, now=T2)["ok"]
    after = on_disk()
    assert after["boards"]["infostud"] == OLD_FILE["boards"]["infostud"] and "workable" not in after["boards"]


@pytest.mark.parametrize("content", ["", "{not json", "[]", "null", '{"version": 1, "boards": []}', '{"version": 99, "boards": {}}',
                                     '{"boards": {}}', b"\xff\xfe\x00bad"])
def test_a_corrupt_file_falls_back_to_defaults_without_crashing_discovery(content):
    path = source_settings.sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.write_bytes if isinstance(content, bytes) else path.write_text)(content)
    kept, skipped = run_discovery.apply_owner_skips(list(SERBIA), [])
    assert kept == SERBIA and skipped == []
    assert run_discovery.effective_provider_names("serbia") == SERBIA
    result = source_settings.get()
    assert result.get("error") and all(row(result, n)["active"] for n in GROUP_SOURCES)
    assert source_settings.save({"jobspy": {"active": False}})["ok"] is False, "a corrupt file is left as it is"


def test_a_directory_in_place_of_the_file_does_not_crash_discovery():
    source_settings.sources_path().mkdir(parents=True)
    assert run_discovery.apply_owner_skips(list(SERBIA), []) == (SERBIA, [])


@pytest.mark.parametrize("entry", [None, True, "off", [], 0])
def test_a_malformed_entry_counts_as_not_saved_and_saving_repairs_it_without_a_crash(entry):
    write_old({**OLD_FILE, "boards": {**OLD_FILE["boards"], "jobspy": entry}})
    assert row(source_settings.get(), "jobspy")["active"] is True
    assert run_discovery.apply_owner_skips(list(SERBIA), [])[1] == [("infostud", source_settings.SKIP_SWITCH)]
    assert source_settings.save({"jobspy": {"active": False}}, now=T2)["ok"]
    assert on_disk()["boards"]["jobspy"]["active"] is False


@pytest.mark.parametrize("bad", [{"history": 5}, {"history": {"a": 1}}, {"history": None}])
def test_a_malformed_history_does_not_stop_a_switch(bad):
    write_old({**OLD_FILE, "boards": {**OLD_FILE["boards"], "infostud": {"active": False, **bad}}})
    assert source_settings.save({"infostud": {"active": True}}, now=T2)["ok"]
    assert on_disk()["boards"]["infostud"]["active"] is True


@pytest.mark.parametrize("migrations", [None, [], "x"])
def test_a_malformed_migrations_value_does_not_crash_the_legacy_move(migrations):
    write_old({**OLD_FILE, "migrations": migrations})
    assert source_settings.migrate_legacy({"includeJoberty": True}, now=T2)["ok"] is True
