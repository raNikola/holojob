"""gpt-6-luna service tiers (standard / flex): price lookup, cost math, the tier sent, the tier recorded, flex without fallback.

Mocked responses only: requests.post is replaced in every test (the conftest tripwire fails any real POST).
The prices are the shipped src/data/aiPricing.json ones.
"""

import json

import pytest
import requests

import ai_gate
import llm_client
from conftest import select_provider

MODEL = "gpt-6-luna"


class _Response:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.ok = 200 <= status < 300
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _answer(*, tier="default", prompt=200_000, cached=0, completion=100_000):
    body = {"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "prompt_tokens_details": {"cached_tokens": cached}}}
    if tier is not None:
        body["service_tier"] = tier
    return _Response(200, body)


@pytest.fixture
def api(tmp_path, monkeypatch):
    (tmp_path / "ai").mkdir(exist_ok=True)
    (tmp_path / "ai" / "settings.json").write_text(json.dumps({"dailyLimit": 10, "monthlyLimit": 25}))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    sent, replies = [], []

    def post(url, headers=None, json=None, timeout=None):
        sent.append(dict(json))
        return replies.pop(0)

    monkeypatch.setattr(requests, "post", post)

    def choose(tier=None, **more):
        extra = {"serviceTier": tier} if tier else {}
        select_provider(tmp_path, monkeypatch, "openai", MODEL, **extra, **more)

    return sent, replies, choose


def _result():
    return [r for r in ai_gate.read_ledger() if r["type"] == "result"][-1]


def _call():
    return [r for r in ai_gate.read_ledger() if r["type"] == "call"][-1]


# --- price lookup ---------------------------------------------------------------

def test_price_lookup_per_tier():
    standard = ai_gate.classify("openai", MODEL, tier="standard")
    flex = ai_gate.classify("openai", MODEL, tier="flex")
    assert (standard["inputPerMTok"], standard["cachedInputPerMTok"], standard["outputPerMTok"]) == (0.10, 0.01, 0.50)
    assert (flex["inputPerMTok"], flex["cachedInputPerMTok"], flex["outputPerMTok"]) == (0.05, 0.005, 0.25)
    assert standard["priceKnown"] and flex["priceKnown"] and standard["maxInputTokens"] == 272000
    assert standard["source"].startswith("https://developers.openai.com/api/docs/pricing")
    assert standard["checkedAt"] == "2026-11-09"


def test_no_tier_means_standard_and_an_unlisted_tier_is_unpriced():
    assert ai_gate.classify("openai", MODEL)["tier"] == "standard"
    assert ai_gate.classify("openai", MODEL, tier="fast")["priceKnown"] is False
    # Other gpt models stay unpriced.
    assert ai_gate.classify("openai", "gpt-6.1-sol", tier="standard")["priceKnown"] is False


# --- cost math ------------------------------------------------------------------

def test_cost_math_with_cached_tokens():
    flex = ai_gate.classify("openai", MODEL, tier="flex")
    # 200k prompt of which 80k cached, 100k out: 120k * 0.05 + 80k * 0.005 + 100k * 0.25 (per 1M)
    assert ai_gate._cost(flex, 200_000, 100_000, 80_000) == pytest.approx(0.006 + 0.0004 + 0.025)
    standard = ai_gate.classify("openai", MODEL, tier="standard")
    assert ai_gate._cost(standard, 200_000, 100_000, 0) == pytest.approx(0.07)
    assert ai_gate._cost(standard, 1000, 10, 5000) == pytest.approx(1000 * 0.01 / 1e6 + 10 * 0.5 / 1e6)  # cached capped


def test_long_context_has_no_cost():
    standard = ai_gate.classify("openai", MODEL, tier="standard")
    assert ai_gate._cost(standard, 272_000, 10) is not None
    assert ai_gate._cost(standard, 272_001, 10) is None


# --- the request ------------------------------------------------------------------

def test_standard_is_the_default_and_is_sent_as_default(api):
    sent, replies, choose = api
    choose()
    replies.append(_answer())
    llm_client.complete_json("q")
    assert sent[0]["service_tier"] == "default"
    assert _call()["serviceTierRequested"] == "standard"


def test_flex_is_sent_when_selected(api):
    sent, replies, choose = api
    choose("flex")
    replies.append(_answer(tier="flex"))
    llm_client.complete_json("q")
    assert sent[0]["service_tier"] == "flex"


def test_the_selection_rejects_an_unknown_tier():
    import ai_selection
    assert ai_selection.validate({"serviceTier": "fast"})
    assert not ai_selection.validate({"serviceTier": "flex"})
    assert ai_selection.DEFAULTS["serviceTier"] == "standard"


def test_other_providers_get_no_tier(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setenv("GROQ_API_KEY", "test")
    (tmp_path / "ai").mkdir(exist_ok=True)
    (tmp_path / "ai" / "settings.json").write_text(json.dumps({"dailyLimit": 10, "monthlyLimit": 25}))
    pricing = tmp_path / "p.json"
    pricing.write_text(json.dumps({"currency": "USD", "entries": [
        {"provider": "groq", "model": "*", "class": "paid", "inputPerMTok": 1, "outputPerMTok": 1, "source": "t"}]}))
    monkeypatch.setenv("HOLOJOB_AI_PRICING", str(pricing))
    monkeypatch.setattr(requests, "post", lambda *a, json=None, **k: sent.append(json) or _answer(tier=None))
    llm_client.complete_json("q", provider="groq", model="m")
    assert "service_tier" not in sent[0] and "serviceTierRequested" not in _call()


# --- the ledger: actual tier, cached tokens, cost --------------------------------------

def test_cost_is_computed_from_the_actual_tier_not_the_requested_one(api):
    sent, replies, choose = api
    choose("flex")
    replies.append(_answer(tier="default", prompt=200_000, cached=0, completion=100_000))  # served as standard
    llm_client.complete_json("q")
    row = _result()
    assert row["serviceTierActual"] == "default" and row["costTier"] == "standard"
    assert _call()["serviceTierRequested"] == "flex"
    assert row["cost"] == pytest.approx(0.07)  # standard, not the 0.035 flex would cost


def test_flex_served_records_flex_tokens_and_cost(api):
    sent, replies, choose = api
    choose("flex")
    replies.append(_answer(tier="flex", prompt=200_000, cached=80_000, completion=100_000))
    llm_client.complete_json("q")
    row = _result()
    assert (row["inputTokens"], row["cachedInputTokens"], row["outputTokens"]) == (200_000, 80_000, 100_000)
    assert row["serviceTierActual"] == "flex" and row["costTier"] == "flex"
    assert row["cost"] == pytest.approx(0.0314)
    assert row["tokensAreEstimate"] is False
    merged = ai_gate._calls(ai_gate.read_ledger())[-1]
    assert merged["serviceTierActual"] == "flex" and merged["cachedInputTokens"] == 80_000
    assert ai_gate.totals()["today"]["cost"] == pytest.approx(0.0314)  # the budget uses the tier-correct cost


@pytest.mark.parametrize("reported", [None, "priority", "fast"])
def test_a_tier_we_do_not_price_leaves_the_cost_unpriced(api, reported):
    sent, replies, choose = api
    choose("standard")
    replies.append(_answer(tier=reported))
    llm_client.complete_json("q")
    row = _result()
    assert row["cost"] is None and row["costTier"] is None
    assert ai_gate.totals()["today"]["unpricedPaidCalls"] == 1


def test_a_call_that_ran_over_the_short_context_limit_is_unpriced_and_flagged(api):
    sent, replies, choose = api
    choose("standard")
    replies.append(_answer(prompt=300_000))
    llm_client.complete_json("q")
    row = _result()
    assert row["cost"] is None and row["longContextUnpriced"] is True


# --- flex unavailable: clear error, no fallback --------------------------------------

@pytest.mark.parametrize("status", [429, 503])
def test_flex_unavailable_is_an_error_with_no_retry_and_no_standard_fallback(api, status):
    sent, replies, choose = api
    choose("flex")
    replies.extend([_Response(status, {"error": {"message": "Resource Unavailable"}}), _answer()])
    with pytest.raises(llm_client.FlexUnavailable, match="not switched to standard"):
        llm_client.complete_json("q")
    assert len(sent) == 1 and sent[0]["service_tier"] == "flex"
    row = _result()
    assert row["ok"] is False and row["flexUnavailable"] is True
    assert "flex processing is unavailable" in row["error"]


def test_a_429_on_standard_keeps_the_normal_retry(api):
    sent, replies, choose = api
    choose("standard")
    replies.extend([_Response(429, {}), _answer()])
    llm_client.complete_json("q")
    assert [b["service_tier"] for b in sent] == ["default", "default"]


# --- refusals --------------------------------------------------------------------

def test_a_tier_without_a_price_is_refused_before_any_call(api):
    sent, replies, choose = api
    choose()
    with pytest.raises(Exception, match="price unknown"):
        llm_client.complete_json("q", provider="openai", model="gpt-6.1-sol")
    assert sent == []


def test_a_prompt_over_the_short_context_limit_is_refused(api):
    sent, replies, choose = api
    choose()
    with pytest.raises(Exception, match="long-context prices"):
        llm_client.complete_json("x" * (272_000 * 4 + 8))
    assert sent == []
    assert _call()["decision"] == "refused"


def test_subscription_class_is_unchanged(tmp_path):
    row, price = ai_gate._call_row("claude-code", None, 400, None, "jobAnalysis", None, None, None,
                                   {"claudeCodeSubscription": {"enabled": True, "features": ["jobAnalysis"],
                                                               "maxCallsDaily": 5}}, None)
    assert price["class"] == "subscription" and row["cost"] == 0 and "serviceTierRequested" not in row


def test_tier_mapping_matches_the_node_side():
    """Standard goes out as "default", flex as "flex"; the same table as API_SERVICE_TIER in openaiProvider.js."""
    assert ai_gate.API_TIER == {"standard": "default", "flex": "flex"}
    assert ai_gate.api_tier("standard") == "default" and ai_gate.api_tier("flex") == "flex"
    assert ai_gate.api_tier("fast") is None and ai_gate.api_tier(None) is None


# --- rejected key: the provider's reason is kept (masked), one request, statuses recorded -------------------

def test_a_rejected_key_keeps_the_providers_reason_without_the_key_and_makes_one_request(api):
    sent, replies, choose = api
    choose("standard")
    replies.extend([
        _Response(401, {"error": {"message": "Incorrect API key provided: sk-proj-********abcd. Contact a@b.example.",
                                  "code": "invalid_api_key"}}),
        _answer(),
    ])
    with pytest.raises(llm_client.LlmUnavailable) as caught:
        llm_client.complete_json("q")
    text = str(caught.value)
    assert "rejected the key (401)" in text and "Incorrect API key provided" in text and "invalid_api_key" in text
    assert "sk-proj" not in text and "abcd" not in text and "a@b.example" not in text
    assert len(sent) == 1
    row = _result()
    assert row["ok"] is False and row["httpStatuses"] == [401]
    assert "abcd" not in row["error"] and "a@b.example" not in row["error"]


def test_a_missing_scope_message_is_kept(api):
    sent, replies, choose = api
    choose()
    replies.append(_Response(403, {"error": "You have insufficient permissions. Missing scopes: api.model.read."}))
    with pytest.raises(llm_client.LlmUnavailable, match="Missing scopes: api.model.read"):
        llm_client.complete_json("q")


def test_every_http_request_of_a_call_is_recorded(api):
    sent, replies, choose = api
    choose("standard")
    replies.extend([_Response(429, {}), _Response(500, {}), _answer()])
    llm_client.complete_json("q")
    assert _result()["httpStatuses"] == [429, 500, 200]
    assert _result()["attempts"] == 3


# --- gpt-6-luna request body: the parameters a reasoning model accepts -------------------------------

SCHEMA = {"name": "facts", "strict": True, "schema": {"type": "object", "properties": {}, "additionalProperties": False}}
NEVER_SENT = ("temperature", "seed", "max_tokens", "top_p", "tools", "tool_choice", "stop", "logprobs", "top_logprobs", "n",
              "presence_penalty", "frequency_penalty", "prediction", "verbosity", "stream", "user", "metadata",
              "safety_identifier", "store", "prompt_cache_key")


def test_the_luna_body_has_exactly_the_accepted_fields(api):
    sent, replies, choose = api
    choose("standard")
    replies.append(_answer())
    llm_client.complete_json("q", schema=SCHEMA)
    body = sent[0]
    assert set(body) == {"model", "messages", "response_format", "service_tier", "reasoning_effort", "max_completion_tokens"}
    assert body["model"] == MODEL and body["service_tier"] == "default"
    assert body["reasoning_effort"] == "low" and body["max_completion_tokens"] == 8000
    assert body["response_format"] == {"type": "json_schema", "json_schema": SCHEMA}
    assert not any(name in body for name in NEVER_SENT)


def test_flex_is_sent_as_flex_in_the_same_body(api):
    sent, replies, choose = api
    choose("flex")
    replies.append(_answer(tier="flex"))
    llm_client.complete_json("q")
    assert sent[0]["service_tier"] == "flex" and "temperature" not in sent[0] and "seed" not in sent[0]


def test_luna_needs_no_retry_without_a_sampling_setting(api):
    sent, replies, choose = api
    choose()
    replies.append(_answer())
    llm_client.complete_json("q")
    assert len(sent) == 1 and _result()["attempts"] == 1
    assert llm_client._REJECTED == set()


def test_token_cap_and_effort_come_from_the_selection_with_a_floor(api):
    sent, replies, choose = api
    choose(maxTokens=12000, reasoningEffort="medium")
    replies.extend([_answer(), _answer()])
    llm_client.complete_json("q")
    assert sent[0]["max_completion_tokens"] == 12000 and sent[0]["reasoning_effort"] == "medium"
    choose(maxTokens=2000)  # below the floor
    llm_client.complete_json("q")
    assert sent[1]["max_completion_tokens"] == 8000


def test_the_selection_validates_reasoning_effort():
    import ai_selection
    assert ai_selection.validate({"reasoningEffort": "extreme"})
    assert not ai_selection.validate({"reasoningEffort": "high"})
    assert ai_selection.DEFAULTS["reasoningEffort"] == "low"
    assert ai_selection.REASONING_MIN_COMPLETION_TOKENS == 8000


def test_other_openai_models_keep_the_sampling_settings_and_the_rejection_fallback(api, tmp_path, monkeypatch):
    from conftest import permissive_ai_budget
    sent, replies, choose = api
    choose()
    permissive_ai_budget(tmp_path, monkeypatch)  # a priced table for the legacy model
    replies.extend([_Response(400, {"error": {"message": "Unsupported value: 'seed'", "param": "seed"}}), _answer()])
    llm_client.complete_json("q", provider="openai", model="gpt-4o-legacy")
    assert sent[0]["temperature"] == 0 and "seed" in sent[0]
    assert "seed" not in sent[1] and "reasoning_effort" not in sent[0]


# --- HTTP errors: the provider's message is logged (masked); a failed request spends nothing -------------

def test_a_400_keeps_its_message_masked_and_spends_nothing(api):
    sent, replies, choose = api
    choose()
    replies.append(_Response(400, {"error": {"message": "Bad request near 'jane.roe@corp.example' key sk-proj-AAAA****zzzz",
                                              "code": "invalid_request_error"}}))
    with pytest.raises(llm_client.LlmRefused, match="rejected the request"):
        llm_client.complete_json("q")
    row = _result()
    assert row["httpStatuses"] == [400] and row["httpErrors"][0]["status"] == 400
    message = row["httpErrors"][0]["message"]
    assert "Bad request" in message and "invalid_request_error" in message
    assert "jane.roe@corp.example" not in json.dumps(row) and "sk-proj" not in json.dumps(row) and "zzzz" not in json.dumps(row)
    assert row["notBilled"] is True and row["cost"] == 0.0 and row["inputTokens"] == 0 and row["outputTokens"] == 0
    assert ai_gate.totals()["today"]["cost"] == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_no_non_2xx_response_consumes_budget(api, status):
    sent, replies, choose = api
    choose()
    replies.extend([_Response(status, {"error": {"message": "nope"}})] * 3)
    with pytest.raises(Exception):
        llm_client.complete_json("q")
    assert ai_gate.totals()["today"]["cost"] == 0
    assert _result()["notBilled"] is True


def test_a_dropped_connection_keeps_the_estimate_because_billing_is_unknown(api, monkeypatch):
    sent, replies, choose = api
    choose()
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    def boom(url, headers=None, json=None, timeout=None):
        raise requests.ConnectionError("reset")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(Exception):
        llm_client.complete_json("x" * 40_000)
    row = _result()
    assert "notBilled" not in row and row["cost"] > 0


def test_the_pre_call_check_still_refuses_over_budget(api, tmp_path):
    sent, replies, choose = api
    choose()
    (tmp_path / "ai" / "settings.json").write_text(json.dumps({"dailyLimit": 0.0000001, "monthlyLimit": 25}))
    with pytest.raises(Exception, match="budget"):
        llm_client.complete_json("q")
    assert sent == []


def test_the_gate_cli_finish_from_node_records_the_error_and_spends_nothing(api, monkeypatch, capsys):
    """Node reports a failed request as httpStatuses / httpErrors through `ai_gate.py finish`."""
    import io
    sent, replies, choose = api
    choose()
    ticket = ai_gate.reserve("openai", MODEL, 4000, base_url="https://api.openai.com/v1", service_tier="standard")
    payload = {"id": ticket.id, "ok": False, "error": "Bad request jane@corp.example sk-proj-AAAA****zz",
               "baseUrl": "https://api.openai.com/v1", "httpStatuses": [400],
               "httpErrors": [{"status": 400, "message": "Bad request jane@corp.example sk-proj-AAAA****zz"}]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert ai_gate._cli(["finish"]) == 0
    row = _result()
    assert row["notBilled"] is True and row["cost"] == 0.0 and row["httpStatuses"] == [400]
    assert "jane@corp.example" not in json.dumps(row) and "sk-proj" not in json.dumps(row)
    assert ai_gate.totals()["today"]["cost"] == 0
