"""Model selection in llm_client: defaults, judge tier and env overrides."""

import pytest

from llm_client import PROVIDERS, judge_model, resolve


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
