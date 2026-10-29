"""Claude Code on the owner's flat subscription (ai_gate setting claudeCodeSubscription).

Default off. When on, only provider claude-code and an allowlisted feature get class `subscription`; everything else
is classified and refused exactly as before. No test makes a call: the gate is asked, nothing more.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import ai_gate
import claude_code

NOON = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
ON = {"claudeCodeSubscription": {"enabled": True, "maxCallsDaily": 2, "features": ["jobAnalysis"]}}


def turn_on(**sub):
    patch = {"claudeCodeSubscription": {**ON["claudeCodeSubscription"], **sub}}
    result = ai_gate.save_settings(patch, confirm=True)
    assert result["ok"], result
    return result


def ask(provider="claude-code", feature="jobAnalysis", model="sonnet", now=NOON, chars=4000):
    return ai_gate.reserve(provider, model, chars, feature=feature, now=now)


def rows():
    return [r for r in ai_gate.read_ledger() if r["type"] == "call"]


def test_default_is_off_and_claude_code_is_refused_at_budget_0():
    assert ai_gate.load_settings()["claudeCodeSubscription"] == {"enabled": False, "maxCallsDaily": 5, "features": ["jobAnalysis"]}
    with pytest.raises(ai_gate.AiRefused, match="AI budget is 0"):
        ask()
    assert rows()[0]["class"] == "paid" and rows()[0]["decision"] == "refused"


def test_enabled_allowlisted_feature_is_allowed_with_budget_0_and_recorded():
    turn_on()
    ticket = ask()
    ticket.finish(True, input_tokens=900, output_tokens=300, reported_cost_usd=0.07, now=NOON)
    call = rows()[0]
    assert call["decision"] == "allowed" and call["class"] == "subscription"
    assert call["cost"] == 0.0 and call["priceKnown"] is True and call["feature"] == "jobAnalysis"
    result = [r for r in ai_gate.read_ledger() if r["type"] == "result"][0]
    assert result["cost"] == 0.0 and result["providerReportedCostUsd"] == 0.07
    day = ai_gate.totals(NOON)["today"]
    assert day["calls"] == 1 and day["subscriptionCalls"] == 1 and day["paidCalls"] == 0 and day["cost"] == 0.0


def test_reported_cost_is_informational_only():
    turn_on(maxCallsDaily=5)
    for _ in range(3):
        ask().finish(True, input_tokens=10, output_tokens=10, reported_cost_usd=999.0, now=NOON)
    assert ai_gate.totals(NOON)["today"]["cost"] == 0.0


@pytest.mark.parametrize("feature", ["tailoring", "job-import", "project-scan", "coverLetter", "chat", "unspecified"])
def test_other_features_of_claude_code_stay_paid_and_refused(feature):
    turn_on()
    with pytest.raises(ai_gate.AiRefused, match="AI budget is 0"):
        ask(feature=feature)
    assert rows()[-1]["class"] == "paid"


def test_the_cli_wrapper_used_by_tailoring_stays_refused(monkeypatch):
    turn_on()
    monkeypatch.setattr(claude_code, "_call", lambda *a, **k: pytest.fail("the CLI must not run"))
    with ai_gate.context(feature="tailoring"):
        text, err = claude_code._run(["--model", "sonnet"], "prompt", 10)
    assert text is None and "AI budget is 0" in err


def test_daily_cap_refuses_the_next_call_and_resets_the_next_day():
    turn_on()
    ask(); ask()
    with pytest.raises(ai_gate.AiRefused, match=r"daily Claude subscription call limit reached \(2\)"):
        ask()
    assert [r["decision"] for r in rows()] == ["allowed", "allowed", "refused"]
    ask(now=NOON + timedelta(days=1))
    assert ai_gate.totals(NOON)["today"]["subscriptionCalls"] == 2


def test_other_providers_are_unchanged():
    turn_on()
    for provider in ("openai", "claude", "someone-new"):
        with pytest.raises(ai_gate.AiRefused, match="AI budget is 0"):
            ask(provider=provider, model="m")
    assert ai_gate.classify("someone-new", "m")["class"] == "unknown"
    assert ai_gate.classify("ollama", "m")["class"] == "local"
    assert ask(provider="ollama", model="m")


def test_paid_budget_does_not_count_subscription_calls():
    turn_on()
    ai_gate.save_settings({"dailyLimit": 5, "monthlyLimit": 50}, confirm=True)
    ask()
    totals = ai_gate.totals(NOON)
    assert totals["today"]["paidCalls"] == 0 and totals["thisMonth"]["cost"] == 0.0


def test_automation_switch_still_applies_first():
    turn_on()
    with pytest.raises(ai_gate.AiRefused, match="automatic AI tasks are off"):
        ai_gate.reserve("claude-code", "sonnet", 100, feature="jobAnalysis", trigger=ai_gate.AUTOMATION, now=NOON)


def test_unusable_or_malformed_settings_mean_off():
    ai_gate.settings_path().parent.mkdir(parents=True, exist_ok=True)
    for bad in ({"enabled": "yes", "maxCallsDaily": 5, "features": ["jobAnalysis"]},
                {"enabled": True, "maxCallsDaily": "5", "features": ["jobAnalysis"]},
                {"enabled": True, "maxCallsDaily": 5, "features": "jobAnalysis"}, "on"):
        ai_gate.settings_path().write_text(json.dumps({"claudeCodeSubscription": bad}))
        with pytest.raises(ai_gate.AiRefused):
            ask()
    ai_gate.settings_path().write_text("{ broken")
    with pytest.raises(ai_gate.AiRefused):
        ask()


# --- settings: validation and the confirm ------------------------------------


@pytest.mark.parametrize("patch", [
    {"claudeCodeSubscription": True}, {"claudeCodeSubscription": {"enabled": 1}},
    {"claudeCodeSubscription": {"maxCallsDaily": 0}}, {"claudeCodeSubscription": {"maxCallsDaily": None}},
    {"claudeCodeSubscription": {"maxCallsDaily": "5"}}, {"claudeCodeSubscription": {"maxCallsDaily": True}},
    {"claudeCodeSubscription": {"features": []}}, {"claudeCodeSubscription": {"features": "jobAnalysis"}},
    {"claudeCodeSubscription": {"features": ["notAFeature"]}}, {"claudeCodeSubscription": {"extra": 1}},
])
def test_bad_subscription_settings_are_rejected(patch):
    result = ai_gate.save_settings(patch, confirm=True)
    assert result["ok"] is False and result["errors"]
    assert not ai_gate.settings_path().exists()


def test_enabling_needs_confirm_with_the_agreed_text_and_writes_nothing_before():
    first = ai_gate.save_settings({"claudeCodeSubscription": {"enabled": True}})
    assert first["needsConfirm"] is True and not ai_gate.settings_path().exists()
    text = " ".join(first["increases"])
    for part in ("Claude Code calls for: jobAnalysis", "flat Claude subscription", "not against the AI budget",
                 "cost 0", "5 calls per day", "shared with your own Claude Code use", "redacted job ad",
                 "to Anthropic", "stay blocked at budget 0"):
        assert part in text
    assert ai_gate.save_settings({"claudeCodeSubscription": {"enabled": True}}, confirm=True)["ok"]


def test_raising_the_cap_or_adding_a_feature_needs_confirm_but_lowering_and_turning_off_do_not():
    turn_on(maxCallsDaily=3)
    up = ai_gate.save_settings({"claudeCodeSubscription": {"maxCallsDaily": 4}})
    assert up["needsConfirm"] and "limit up: 3 -> 4" in up["increases"][0]
    more = ai_gate.save_settings({"claudeCodeSubscription": {"features": ["jobAnalysis", "coverLetter"]}})
    assert more["needsConfirm"] and "coverLetter" in more["increases"][0]
    assert ai_gate.save_settings({"claudeCodeSubscription": {"maxCallsDaily": 1}})["ok"]
    assert ai_gate.save_settings({"claudeCodeSubscription": {"enabled": False}})["ok"]
    assert ai_gate.load_settings()["claudeCodeSubscription"]["enabled"] is False
    assert ai_gate.save_settings({"claudeCodeSubscription": {"enabled": True}})["needsConfirm"]


def test_an_added_feature_is_then_allowed_and_counts_toward_the_same_cap():
    turn_on(features=["jobAnalysis", "coverLetter"], maxCallsDaily=2)
    ask(feature="coverLetter"); ask(feature="jobAnalysis")
    with pytest.raises(ai_gate.AiRefused, match="limit reached"):
        ask(feature="coverLetter")


def test_other_settings_saves_keep_the_subscription_setting():
    turn_on()
    ai_gate.save_settings({"dailyLimit": 0, "timezone": "UTC"})
    assert ai_gate.load_settings()["claudeCodeSubscription"] == ON["claudeCodeSubscription"]


def test_usage_summary_reports_the_setting_and_subscription_calls():
    turn_on()
    ask()
    summary = ai_gate.usage_summary(NOON)
    assert summary["settings"]["claudeCodeSubscription"]["enabled"] is True
    assert summary["today"]["subscriptionCalls"] == 1


def test_a_price_override_cannot_create_the_subscription_class():
    entry = {"provider": "openai", "model": "*", "class": "subscription", "source": "x"}
    result = ai_gate.save_pricing_overrides([entry], confirm=True)
    assert result["ok"] is False
