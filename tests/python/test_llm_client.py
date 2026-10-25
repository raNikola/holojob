"""Model selection in llm_client: defaults, judge tier and env overrides; deterministic settings."""

import pytest

import json

from llm_client import DETERMINISTIC, PROVIDERS, LlmRefused, complete_json, judge_model, resolve


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("OPENAI", "DEEPSEEK", "GROQ", "LLM"):
        monkeypatch.delenv(f"{name}_MODEL", raising=False)
        monkeypatch.delenv(f"{name}_JUDGE_MODEL", raising=False)


def test_judge_tier_is_stronger_than_the_default_where_the_provider_has_one():
    assert resolve("openai").default_model != judge_model("openai")
    assert resolve("deepseek").default_model != judge_model("deepseek")
    assert judge_model("claude-code") == "sonnet"


def test_provider_without_a_judge_tier_returns_none():
    # complete_json then falls back to the provider's default model.
    assert judge_model("groq") is None
    assert judge_model("openrouter") is None


def test_judge_model_env_override_wins(monkeypatch):
    monkeypatch.setenv("OPENAI_JUDGE_MODEL", "my-model")
    assert judge_model("openai") == "my-model"


def test_model_env_override_wins(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "my-model")
    assert resolve("groq").default_model == "my-model"


def test_no_default_names_a_retired_model():
    retired = {"deepseek-chat", "deepseek-reasoner", "llama-3.3-70b-versatile",
               "llama-3.1-8b-instant", "gpt-4o", "gpt-4o-mini"}
    names = {p.default_model for p in PROVIDERS.values()}
    assert not names & retired


# --- deterministic settings ------------------------------------------------------------

class _Response:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.ok = 200 <= status < 300
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _ok(content='{"a": 1}'):
    return _Response(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


@pytest.fixture
def posts(monkeypatch):
    import requests

    import llm_client

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(llm_client, "_REJECTED", set())
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    calls, replies = [], []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(dict(json))
        return replies.pop(0) if replies else _ok()

    monkeypatch.setattr(requests, "post", post)
    return calls, replies


def test_openai_calls_ask_for_temperature_0_and_a_fixed_seed(posts):
    calls, _ = posts
    complete_json("q", provider="openai", model="m")
    complete_json("q", provider="openai", model="m")
    assert calls[0]["temperature"] == 0 and calls[0]["seed"] == DETERMINISTIC["seed"]
    assert calls[0]["seed"] == calls[1]["seed"]


def test_other_providers_get_no_sampling_settings(posts):
    calls, _ = posts
    complete_json("q", provider="groq", model="m")
    assert "temperature" not in calls[0] and "seed" not in calls[0]


def test_a_model_that_rejects_temperature_is_asked_again_without_it_and_remembered(posts):
    calls, replies = posts
    replies.append(_Response(400, {"error": {"message": "Unsupported value: 'temperature' does not support 0",
                                             "param": "temperature"}}))
    assert complete_json("q", provider="openai", model="reasoner") == {"a": 1}
    assert "temperature" in calls[0] and "temperature" not in calls[1] and calls[1]["seed"] == DETERMINISTIC["seed"]
    complete_json("q", provider="openai", model="reasoner")
    assert "temperature" not in calls[2]  # no second 400 for the same model
    complete_json("q", provider="openai", model="other")
    assert calls[3]["temperature"] == 0  # another model is asked as usual


def test_a_rejected_setting_does_not_use_up_a_retry(posts):
    import llm_client

    calls, replies = posts
    replies += [_Response(400, {"error": {"param": "temperature", "message": "unsupported"}}),
                _Response(400, {"error": {"param": "seed", "message": "unsupported"}})]
    replies += [_Response(503, {})] * (llm_client.HTTP_RETRIES - 1)
    assert complete_json("q", provider="openai", model="m") == {"a": 1}
    assert len(calls) == 2 + llm_client.HTTP_RETRIES


def test_any_other_400_still_fails(posts):
    _, replies = posts
    replies.append(_Response(400, {"error": {"message": "bad messages", "param": "messages"}}))
    with pytest.raises(LlmRefused):
        complete_json("q", provider="openai", model="m")
