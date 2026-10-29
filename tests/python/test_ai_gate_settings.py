"""Editing the AI budget gate's settings and price table (ai_gate.save_settings / save_pricing_overrides).

Every test runs against the tmp data/ai the autouse fixture in conftest.py sets up.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ai_gate

ROOT = Path(__file__).resolve().parents[2]
NOON = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
OK_SOURCE = "https://example.test/pricing (checked by owner)"


def stored():
    return json.loads(ai_gate.settings_path().read_text())


@pytest.mark.parametrize("patch", [
    {"dailyLimit": -1}, {"dailyLimit": True}, {"dailyLimit": "5"}, {"dailyLimit": float("nan")},
    {"dailyLimit": float("inf")}, {"monthlyLimit": None}, {"maxCallsDaily": -3}, {"maxCallsDaily": 1.5},
    {"maxCallsMonthly": "x"}, {"maxCallsDaily": False}, {"estimatedOutputTokens": -1},
    {"estimatedOutputTokens": 2.5}, {"currency": "usd"}, {"currency": "DOLLARS"}, {"currency": 5},
    {"timezone": "Mars/Base"}, {"timezone": "../etc/passwd"}, {"timezone": ""}, {"timezone": 3},
    {"automation": {"enabled": "yes"}}, {"automation": {"enabled": 1}}, {"automation": True},
    {"automation": {"enabled": True, "extra": 1}},
    {"apiKey": "sk-abc"}, {"unknown": 1}, "not an object", None, [],
])
def test_bad_input_is_rejected_and_nothing_is_written(patch):
    result = ai_gate.save_settings(patch, confirm=True)
    assert result["ok"] is False and result["errors"]
    assert not ai_gate.settings_path().exists()


def test_round_trip_and_defaults():
    assert ai_gate.usage_summary()["settings"] == ai_gate.DEFAULT_SETTINGS
    patch = {"dailyLimit": 1.5, "monthlyLimit": 20, "maxCallsDaily": 10, "maxCallsMonthly": None,
             "estimatedOutputTokens": 800, "timezone": "Europe/Belgrade", "currency": "USD",
             "automation": {"enabled": True}}
    first = ai_gate.save_settings(patch)
    assert first["needsConfirm"] and any("automatic" in line for line in first["increases"])
    assert not ai_gate.settings_path().exists()
    saved = ai_gate.save_settings(patch, confirm=True)
    assert saved["ok"]
    assert ai_gate.usage_summary()["settings"] == stored() == saved["settings"] == {**ai_gate.DEFAULT_SETTINGS, **patch}
    assert ai_gate.load_settings()["dailyLimit"] == 1.5


def test_lowering_needs_no_confirm_and_raising_does():
    ai_gate.save_settings({"dailyLimit": 5, "monthlyLimit": 50, "maxCallsDaily": 10}, confirm=True)
    assert ai_gate.save_settings({"dailyLimit": 2, "maxCallsDaily": 5, "monthlyLimit": 50})["ok"]
    for patch in ({"dailyLimit": 3}, {"monthlyLimit": 51}, {"maxCallsDaily": 6}, {"maxCallsDaily": None},
                  {"estimatedOutputTokens": 10}, {"timezone": "Asia/Tokyo"}, {"automation": {"enabled": True}}):
        before = stored()
        result = ai_gate.save_settings(patch)
        assert result["needsConfirm"] is True, patch
        assert stored() == before, patch


def test_a_partial_patch_keeps_the_other_settings():
    ai_gate.save_settings({"dailyLimit": 5, "monthlyLimit": 50, "timezone": "Europe/Belgrade"}, confirm=True)
    ai_gate.save_settings({"automation": {"enabled": True}}, confirm=True)
    assert stored()["dailyLimit"] == 5 and stored()["timezone"] == "Europe/Belgrade"
    ai_gate.save_settings({"automation": {"enabled": False}})
    assert stored()["automation"] == {"enabled": False} and stored()["monthlyLimit"] == 50


def test_unreadable_file_counts_as_budget_0_for_the_confirm():
    ai_gate.ai_dir().mkdir(parents=True)
    ai_gate.settings_path().write_text("{not json")
    result = ai_gate.save_settings({"dailyLimit": 1, "monthlyLimit": 1})
    assert result["needsConfirm"]
    assert ai_gate.save_settings({"dailyLimit": 1, "monthlyLimit": 1}, confirm=True)["ok"]
    assert "error" not in ai_gate.load_settings()


def test_hand_edited_unknown_keys_do_not_reach_the_response():
    ai_gate.ai_dir().mkdir(parents=True)
    ai_gate.settings_path().write_text(json.dumps({"dailyLimit": 1, "monthlyLimit": 1, "apiKey": "sk-secret-value"}))
    assert "apiKey" not in ai_gate.usage_summary()["settings"]
    assert "sk-secret-value" not in json.dumps(ai_gate.usage_summary())
    ai_gate.save_settings({"dailyLimit": 1})
    assert "apiKey" not in stored()


def test_currency_mismatch_with_the_price_table_warns():
    result = ai_gate.save_settings({"currency": "EUR"}, confirm=True)
    assert result["ok"] and any("refused" in w for w in result["warnings"])


def test_write_leaves_no_temp_files():
    ai_gate.save_settings({"dailyLimit": 1, "monthlyLimit": 1}, confirm=True)
    assert sorted(p.name for p in ai_gate.ai_dir().iterdir() if p.name != ".ledger.lock") == ["settings.json"]


def test_a_failed_write_keeps_the_old_file(monkeypatch):
    ai_gate.save_settings({"dailyLimit": 1, "monthlyLimit": 1}, confirm=True)
    before = ai_gate.settings_path().read_bytes()
    monkeypatch.setattr(ai_gate.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        ai_gate.save_settings({"dailyLimit": 0})
    assert ai_gate.settings_path().read_bytes() == before
    assert [p.name for p in ai_gate.ai_dir().iterdir() if p.name.endswith(".tmp")] == []


# --- price table ---------------------------------------------------------------


def entry(cls="paid", **kw):
    return {"provider": "openai", "model": "gpt-x", "class": cls, "inputPerMTok": 1, "outputPerMTok": 2,
            "source": OK_SOURCE, **kw}


@pytest.mark.parametrize("bad", [
    entry(source=None), entry(source="  "), entry(cls="free", inputPerMTok=0, outputPerMTok=0, source=None),
    entry(cls="local", inputPerMTok=None, outputPerMTok=None, source=""),
    entry(inputPerMTok=-1), entry(outputPerMTok=None), entry(inputPerMTok=True), entry(cls="cheap"),
    entry(cls="free", inputPerMTok=1, outputPerMTok=1), entry(cls="unknown", source=None),
    entry(provider="Bad Name!"), entry(extra=1), entry(inputPerMTok=float("nan")),
])
def test_price_entries_need_a_source_and_sane_prices(bad):
    result = ai_gate.save_pricing_overrides([bad], confirm=True)
    assert result["ok"] is False and result["errors"]
    assert not ai_gate.pricing_overrides_path().exists()


def test_paid_without_a_price_needs_no_source_and_stays_refused():
    result = ai_gate.save_pricing_overrides(
        [entry(inputPerMTok=None, outputPerMTok=None, source=None)])
    assert result["ok"]


def test_pricing_round_trip_merges_over_the_shipped_table():
    first = ai_gate.save_pricing_overrides([entry()])
    assert first["needsConfirm"]
    assert ai_gate.save_pricing_overrides([entry()], confirm=True)["ok"]
    price = ai_gate.classify("openai", "gpt-x")
    assert price["priceKnown"] and price["inputPerMTok"] == 1 and price["source"] == OK_SOURCE
    assert ai_gate.classify("openai", "other")["priceKnown"] is False  # the "*" entry is unchanged
    table = {(e["provider"], e["model"]): e["origin"] for e in ai_gate.usage_summary()["pricing"]["entries"]}
    assert table[("openai", "gpt-x")] == "override" and table[("openai", "*")] == "default"
    assert ai_gate.save_pricing_overrides([])["ok"]  # restoring the shipped table loosens nothing
    assert ai_gate.classify("openai", "gpt-x")["priceKnown"] is False


def test_unknown_stays_paid_whatever_is_edited():
    assert ai_gate.classify("neverheard")["class"] == "unknown"
    assert ai_gate.is_paid("unknown")
    ai_gate.save_pricing_overrides([entry(provider="neverheard", model="*", cls="unknown",
                                          inputPerMTok=None, outputPerMTok=None, source=None)])
    assert ai_gate.is_paid(ai_gate.classify("neverheard", "m")["class"])


def test_setting_a_model_free_needs_confirm():
    free = entry(cls="free", inputPerMTok=0, outputPerMTok=0)
    result = ai_gate.save_pricing_overrides([free])
    assert result["needsConfirm"] and "paid" in result["increases"][0]


# --- the ledger is append-only and settings changes do not rewrite history -------


def test_settings_and_pricing_changes_cannot_undo_an_existing_refusal():
    with pytest.raises(ai_gate.AiRefused):
        ai_gate.reserve("openai", "gpt-x", 400, feature="jobAnalysis", now=NOON)
    ledger_before = ai_gate.ledger_path().read_bytes()
    refused_before = ai_gate.totals(NOON)["today"]["refused"]
    assert refused_before == 1

    assert ai_gate.save_settings({"dailyLimit": 100, "monthlyLimit": 1000, "automation": {"enabled": True}},
                                 confirm=True)["ok"]
    assert ai_gate.save_pricing_overrides(
        [entry(cls="free", inputPerMTok=0, outputPerMTok=0)], confirm=True)["ok"]

    ledger_after = ai_gate.ledger_path().read_bytes()
    assert ledger_after.startswith(ledger_before) and ledger_after == ledger_before  # nothing appended or rewritten
    totals = ai_gate.totals(NOON)
    assert totals["today"]["refused"] == 1 and totals["thisMonth"]["refused"] == 1
    row = ai_gate.recent_rows()[0]
    assert row["decision"] == "refused" and row["class"] == "paid"  # the class it had when it was refused
    ai_gate.reserve("openai", "gpt-x", 400, now=NOON)  # a new call is judged by the new rules
    assert ai_gate.ledger_path().read_bytes().startswith(ledger_before)


def test_recent_rows_are_the_last_50_newest_first_and_hide_secrets():
    ai_gate.save_settings({"dailyLimit": 100, "monthlyLimit": 1000}, confirm=True)
    ai_gate.save_pricing_overrides([entry(provider="ollama", model="m", cls="local", inputPerMTok=0,
                                          outputPerMTok=0)], confirm=True)
    for _ in range(55):
        ai_gate.reserve("ollama", "m", 40, now=NOON).finish(True, error="failed with sk-abcdefghij12345 key")
    rows = ai_gate.usage_summary(NOON)["recent"]
    assert len(rows) == 50
    assert rows[0]["ts"] >= rows[-1]["ts"]
    assert "sk-abcdefghij12345" not in json.dumps(rows)
    assert "api" not in " ".join(ai_gate.usage_summary()["settings"]).lower()


def test_no_gate_function_edits_or_deletes_a_ledger_row():
    public = {n for n in dir(ai_gate) if not n.startswith("_")}
    assert not {n for n in public if any(w in n for w in ("delete", "clear", "truncate", "purge", "edit"))}
    source = (ROOT / "python" / "llm" / "ai_gate.py").read_text()
    assert source.count("open(ledger_path()") == 1 and 'open(ledger_path(), "a"' in source  # one writer, append mode


def test_cli_settings_put_round_trip():
    env_dir = str(ai_gate.ai_dir())
    import os
    env = {**os.environ, "CAREER_OS_AI_DIR": env_dir}
    run = subprocess.run([sys.executable, str(ROOT / "python" / "llm" / "ai_gate.py"), "settings-put"],
                         input=json.dumps({"settings": {"dailyLimit": -1}}), capture_output=True, text=True, env=env)
    assert run.returncode == 0 and json.loads(run.stdout)["errors"]
    run = subprocess.run([sys.executable, str(ROOT / "python" / "llm" / "ai_gate.py"), "settings-put"],
                         input=json.dumps({"settings": {"dailyLimit": 1}, "confirm": "true"}),
                         capture_output=True, text=True, env=env)
    assert json.loads(run.stdout)["needsConfirm"] is True  # only a real true counts
