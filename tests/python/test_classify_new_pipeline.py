"""Package 14: classify_new inside the pipeline (confirmed, caps, the gate's trigger) with the data layer stubbed. Nothing under data/ is touched."""

from __future__ import annotations

import json

import ai_gate
import classify_new
import pipeline_lock
import role_class
from test_classify_new import AD, PROFILE, Guard, row


class FakeLock:
    def release(self):
        pass


def drive_main(monkeypatch, tmp_path, *, trigger, refuse):
    """classify_new.main with --confirm: returns (exit code, run records written, the trigger the gate saw)."""
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(PROFILE))
    seen, records = {}, []
    monkeypatch.setattr(pipeline_lock, "acquire", lambda: FakeLock())
    monkeypatch.setattr(role_class, "store_path", lambda: tmp_path / "fit3.json")
    monkeypatch.setattr(classify_new, "scoring_rows", lambda *a: [row("n1"), row("n2", description=AD + " two")])
    monkeypatch.setattr(classify_new, "write_run_record", records.append)
    monkeypatch.setattr(classify_new, "merge_into_store", lambda path, entries: len(entries))
    monkeypatch.setattr(ai_gate, "record_refused", lambda *a, **k: None)

    def fake_estimate(todo, profile, roles, comps, max_ads, max_usd):
        return {"send": todo, "privacyRefused": [], "beyondAdLimit": 0, "provider": "p", "model": "m", "priceKnown": True, "inputOnlyUsd": 0.001,
                "worstCaseUsd": 0.01, "maxUsd": max_usd, "budget": {"dailyLimit": 1, "monthlyLimit": 5, "dailySpent": 0, "monthlySpent": 0}}

    def fake_preflight(*a, **k):
        seen["trigger"] = ai_gate.current_trigger()
        return type("D", (), {"allowed": not refuse, "reason": "automatic AI tasks are off"})()

    def fake_run(send, *a, **k):
        return {"entries": {key: {"reply": {}, "answers": None} for key, _ in send}, "failed": {}, "stopped": None, "left": 0, "calls": len(send)}

    monkeypatch.setattr(classify_new, "estimate", fake_estimate)
    monkeypatch.setattr(classify_new, "preflight", fake_preflight)
    monkeypatch.setattr(classify_new.enrich_jobs, "make_guard", lambda cap, p, m: type("G", (), {"cap": cap, "price": {}, "max_output": 1})())
    monkeypatch.setattr(classify_new, "Guard", lambda *a: Guard())  # the real one reads the AI ledger under data/
    monkeypatch.setattr(classify_new, "run", fake_run)
    if trigger:
        monkeypatch.setenv(ai_gate.TRIGGER_ENV, trigger)
    else:
        monkeypatch.delenv(ai_gate.TRIGGER_ENV, raising=False)
    code = classify_new.main(["--profile", str(profile), "--confirm"])
    return code, records, seen


def summary_line(capsys):
    out = capsys.readouterr().out
    assert any(l.startswith("{") for l in out.splitlines()), out
    return json.loads(next(l for l in out.splitlines() if l.startswith("{")))


def test_inside_the_pipeline_the_gate_sees_an_automatic_task_and_its_refusal_is_counted(monkeypatch, tmp_path, capsys):
    code, records, seen = drive_main(monkeypatch, tmp_path, trigger="automation", refuse=True)
    summary = summary_line(capsys)
    assert code == 0 and seen["trigger"] == "automation"
    assert summary["classified"] == 0 and summary["left"] == 2 and summary["stopped"].startswith("stopped: AI gate refused")
    assert records and records[0]["left"] == 2


def test_a_standalone_run_is_a_manual_task_and_classifies(monkeypatch, tmp_path, capsys):
    code, records, seen = drive_main(monkeypatch, tmp_path, trigger=None, refuse=False)
    summary = summary_line(capsys)
    assert code == 0 and seen["trigger"] == "manual" and summary["classified"] == 2 and summary["left"] == 0


def test_the_default_caps_are_the_owner_decision():
    assert (classify_new.DEFAULT_MAX_USD, classify_new.DEFAULT_MAX_ADS) == (0.05, 100)
