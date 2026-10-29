"""The one AI provider selection (python/llm/ai_selection.py): validation, the confirm rule, and one reader for both paths."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ai_gate
import ai_selection
import llm_client
from conftest import select_provider

GATE = Path(__file__).resolve().parents[2] / "python" / "llm" / "ai_gate.py"


def stored(tmp_path):
    return json.loads((tmp_path / "config" / "ai-settings.json").read_text())


def test_a_missing_file_is_no_selection_and_never_a_default():
    assert ai_selection.read() == {"selection": None, "error": None}
    with pytest.raises(ai_selection.SelectionError, match="No AI provider selected"):
        ai_selection.require()


@pytest.mark.parametrize("patch, fragment", [
    ({"apiKey": "sk-secret-0123456789"}, "unknown setting: apiKey"),
    ({"key": "x"}, "unknown setting: key"),
    ({"provider": "skynet"}, "provider must be one of"),
    ({"provider": 3}, "provider must be one of"),
    ({"model": "has space"}, "model must be"),
    ({"model": "x" * 101}, "model must be"),
    ({"temperature": 2.5}, "temperature must be"),
    ({"temperature": -0.1}, "temperature must be"),
    ({"temperature": True}, "temperature must be"),
    ({"temperature": float("nan")}, "temperature must be"),
    ({"maxTokens": 0}, "maxTokens must be"),
    ({"maxTokens": 200001}, "maxTokens must be"),
    ({"maxTokens": 10.5}, "maxTokens must be"),
    ({"maxTokens": True}, "maxTokens must be"),
    ({"baseUrl": "ftp://x"}, "baseUrl must be"),
    ({"baseUrl": "http://user:pw@localhost:11434"}, "baseUrl must be"),
    ({"baseUrl": "http://localhost:11434/?key=abc"}, "baseUrl must be"),
    ({"features": {"nope": True}}, "unknown setting: features.nope"),
    ({"features": {"outreach": "yes"}}, "features.outreach must be"),
    ({"features": []}, "features must be an object"),
])
def test_validation_is_strict(tmp_path, patch, fragment):
    result = ai_selection.save({"provider": "ollama", "model": "m", **patch})
    assert result["ok"] is False
    assert any(fragment in e for e in result["errors"]), result
    assert not (tmp_path / "config" / "ai-settings.json").exists()


def test_a_base_url_is_only_for_ollama(tmp_path):
    bad = ai_selection.save({"provider": "openai", "model": "m", "baseUrl": "https://proxy.example/v1"}, confirm=True)
    assert bad["ok"] is False and "only for ollama" in bad["errors"][0]
    ok = ai_selection.save({"provider": "ollama", "model": "llama3.2", "baseUrl": "http://localhost:11434"})
    assert ok["ok"] is True and stored(tmp_path)["baseUrl"] == "http://localhost:11434"


def test_the_first_selection_needs_a_provider_and_a_model(tmp_path):
    assert ai_selection.save({"temperature": 0.5})["ok"] is False
    assert ai_selection.save({"provider": "ollama"})["errors"] == ["model is required"]


def test_a_paid_provider_needs_confirm_and_nothing_is_written_without_it(tmp_path):
    result = ai_selection.save({"provider": "openai", "model": "gpt-x"})
    assert result["ok"] is False and result["needsConfirm"] is True
    assert "paid" in result["increases"][0] and "openai" in result["increases"][0]
    assert not (tmp_path / "config" / "ai-settings.json").exists()
    assert ai_selection.save({"provider": "openai", "model": "gpt-x"}, confirm=True)["ok"] is True
    assert stored(tmp_path)["provider"] == "openai"


def test_claude_code_is_paid_class_and_needs_confirm_too():
    assert ai_selection.save({"provider": "claude-code", "model": "sonnet"})["needsConfirm"] is True


def test_free_and_local_providers_need_no_confirm():
    assert ai_selection.save({"provider": "mock", "model": "mock"})["ok"] is True
    assert ai_selection.save({"provider": "ollama", "model": "llama3.2"})["ok"] is True


def test_an_ollama_on_someone_elses_machine_is_unknown_and_needs_confirm():
    result = ai_selection.save({"provider": "ollama", "model": "m", "baseUrl": "https://gpu.example.com"})
    assert result["needsConfirm"] is True and "unknown" in result["increases"][0]


def test_a_provider_missing_from_the_price_table_is_unknown_and_needs_confirm(tmp_path, monkeypatch):
    table = tmp_path / "pricing.json"
    table.write_text(json.dumps({"currency": "USD", "entries": []}))
    monkeypatch.setenv("HOLOJOB_AI_PRICING", str(table))
    result = ai_selection.save({"provider": "gemini", "model": "m"})
    assert result["needsConfirm"] is True and "no known price" in result["increases"][0]


def test_only_a_change_of_target_needs_confirm_again(tmp_path):
    ai_selection.save({"provider": "openai", "model": "gpt-x"}, confirm=True)
    assert ai_selection.save({"temperature": 0.9, "maxTokens": 500, "features": {"outreach": False}})["ok"] is True
    assert stored(tmp_path)["temperature"] == 0.9 and stored(tmp_path)["features"]["outreach"] is False
    assert stored(tmp_path)["features"]["skillGap"] is True
    assert ai_selection.save({"model": "gpt-y"})["needsConfirm"] is True
    assert ai_selection.save({"provider": "openrouter"})["needsConfirm"] is True
    assert stored(tmp_path)["model"] == "gpt-x"  # refused changes did not touch the file
    # Moving back to a free provider is never a loosening.
    assert ai_selection.save({"provider": "mock", "model": "mock"})["ok"] is True


def test_the_file_is_written_atomically_and_carries_no_secret(tmp_path):
    ai_selection.save({"provider": "mock", "model": "mock"})
    assert [p.name for p in (tmp_path / "config").iterdir()] == ["ai-settings.json"]
    assert set(stored(tmp_path)) == set(ai_selection.KEYS)


def test_an_unreadable_or_invalid_file_refuses_and_is_never_overwritten(tmp_path, monkeypatch):
    path = select_provider(tmp_path, monkeypatch, "mock", "mock")
    for text in ("{broken", json.dumps({"provider": "mock", "model": "m", "apiKey": "x"}), "[]"):
        path.write_text(text)
        assert ai_selection.read()["selection"] is None and ai_selection.read()["error"]
        with pytest.raises(ai_selection.SelectionError):
            ai_selection.require()
        result = ai_selection.save({"provider": "mock", "model": "mock"})
        assert result["ok"] is False and "left as it is" in result["errors"][0]
        assert path.read_text() == text


def test_get_lists_every_provider_with_its_class_and_the_current_one(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "ollama", "llama3.2")
    out = ai_selection.get()
    classes = {p["name"]: p["class"] for p in out["providers"]}
    assert classes["openai"] == "paid" and classes["mock"] == "free" and classes["ollama"] == "local"
    assert out["selection"]["provider"] == "ollama" and out["class"] == "local"
    assert "apiKey" not in json.dumps(out)


def _gate_cli(command, env_extra, payload=None):
    env = {**os.environ, **env_extra}
    proc = subprocess.run([sys.executable, str(GATE), command], input=json.dumps(payload or {}), env=env,
                          capture_output=True, text=True, timeout=60)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_node_path_and_the_python_pipeline_read_the_same_selection(tmp_path, monkeypatch):
    """Node asks `ai_gate.py selection-get`; Python calls llm_client.active_provider(). One file, one answer."""
    select_provider(tmp_path, monkeypatch, "openrouter", "some/model")
    env = {k: os.environ[k] for k in ("HOLOJOB_AI_SELECTION", "HOLOJOB_AI_DIR")}
    from_node = _gate_cli("selection-get", env)["selection"]
    assert from_node["provider"] == "openrouter" and from_node["model"] == "some/model"
    assert llm_client.active_provider() == from_node["provider"]
    # A change through the route Node uses is seen by Python at once.
    saved = _gate_cli("selection-put", env, {"settings": {"provider": "ollama", "model": "llama3.2"}})
    assert saved["ok"] is True
    assert llm_client.active_provider() == "ollama"
    assert _gate_cli("selection-get", env)["selection"]["provider"] == "ollama"


def test_selection_put_through_the_cli_applies_the_confirm_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLOJOB_AI_SELECTION", str(tmp_path / "config" / "ai-settings.json"))
    env = {k: os.environ[k] for k in ("HOLOJOB_AI_SELECTION", "HOLOJOB_AI_DIR")}
    plain = _gate_cli("selection-put", env, {"settings": {"provider": "openai", "model": "m"}})
    assert plain["needsConfirm"] is True
    assert _gate_cli("selection-put", env, {"settings": {"provider": "openai", "model": "m"}, "confirm": "true"})["needsConfirm"] is True
    assert _gate_cli("selection-put", env, {"settings": {"provider": "openai", "model": "m"}, "confirm": True})["ok"] is True
