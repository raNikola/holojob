"""The title filter's vocabulary comes from Settings (package 3). What would hurt: a saved list that is not used, or a bad list that
silently empties the filter (every ad dropped, or every exclusion gone)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "job_discovery" / "providers"))
sys.path.insert(0, str(ROOT / "python" / "llm"))

import ai_gate  # noqa: E402
import role_filter as rf  # noqa: E402


def _store(settings: dict) -> None:
    path = ai_gate.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings))


def test_no_settings_file_is_the_old_vocabulary():
    assert rf.role_tier("Senior Product Manager") == (rf.TARGET, None)
    assert rf.role_tier("Junior Product Manager") == (rf.EXCLUDED, "title_excluded:junior")
    assert rf.role_tier("Chef") == (rf.EXCLUDED, "title_not_matched")


def test_a_saved_list_is_what_the_filter_uses():
    assert ai_gate.save_settings({"roleFilter": {"include": ["chef"], "exclude": []}})["ok"]
    assert rf.role_tier("Head Chef") == (rf.TARGET, None)
    assert rf.role_tier("Junior Product Manager") == (rf.EXCLUDED, "title_not_matched"), "junior left exclude, the product phrases left include"
    assert rf.role_tier("Project Manager") == (rf.NEAR, None), "a list the save did not name keeps its value"


def test_an_empty_include_is_refused_on_save_and_ignored_on_read():
    result = ai_gate.save_settings({"roleFilter": {"include": []}})
    assert not result["ok"] and any("roleFilter.include" in e for e in result["errors"])
    _store({"roleFilter": {"include": [], "exclude": "junior"}})
    lists, warning = ai_gate.role_filter_vocabulary()
    assert lists["include"] == ai_gate.DEFAULT_SETTINGS["roleFilter"]["include"]
    assert lists["exclude"] == ai_gate.DEFAULT_SETTINGS["roleFilter"]["exclude"]
    assert "roleFilter.include" in warning and "roleFilter.exclude" in warning
    assert rf.role_tier("Senior Product Manager") == (rf.TARGET, None)
    assert rf.role_tier("Junior Product Manager")[0] == rf.EXCLUDED


def test_a_phrase_is_folded_like_the_title():
    assert ai_gate.save_settings({"roleFilter": {"near": ["Menadžer  Prodaje"]}})["ok"]
    assert rf.role_tier("Menadzer prodaje") == (rf.NEAR, None)
