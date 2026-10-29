"""Python reads AI keys from the server secret store (BROWSER_STORAGE_POLICY 11c). No real call is made."""

import json
import os
import sys

import pytest
import requests
from conftest import select_provider, write_secret_store

import ai_gate
import llm_client
import secret_store

CANARY = "sk-canary-STORE-0123456789abcdef"
ENV_CANARY = "sk-canary-ENV-0123456789abcdef"
OTHER_CANARY = "sk-canary-OTHER-0123456789abcdef"
PINNED = "https://proxy.example.test/v1"


class _Response:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text
        self.ok = status < 400

    def json(self):
        return self._payload


def _ok():
    return _Response(200, {"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]})


@pytest.fixture
def sent(monkeypatch, tmp_path, open_ai_budget):
    """Selected openai, a recording stand-in for requests.post. Yields (calls, replies)."""
    select_provider(tmp_path, monkeypatch, "openai")
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm_client, "_REJECTED", set())
    calls, replies = [], []

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": dict(headers or {})})
        reply = replies.pop(0) if replies else _ok()
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(requests, "post", post)
    return calls, replies


def _ledger_text(tmp_path):
    path = tmp_path / "ai" / "usage-ledger.jsonl"
    return path.read_text() if path.exists() else ""


def _ledger(tmp_path):
    return [json.loads(line) for line in _ledger_text(tmp_path).splitlines() if line]


def test_the_stored_key_and_pinned_url_are_used(sent, tmp_path):
    calls, _ = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY, "baseUrl": PINNED + "/", "setAt": "x"}})
    assert llm_client.complete_json("hi") == {"a": 1}
    assert calls[0]["headers"]["Authorization"] == f"Bearer {CANARY}"
    assert calls[0]["url"] == f"{PINNED}/chat/completions"
    assert llm_client.call_target()[2] == PINNED  # the gate is told the host the request goes to


def test_the_gate_is_handed_the_url_the_request_is_sent_to(sent, tmp_path, monkeypatch):
    calls, _ = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY, "baseUrl": PINNED}})
    handed = []
    real = ai_gate.reserve
    monkeypatch.setattr(ai_gate, "reserve", lambda *a, **k: handed.append(k.get("base_url")) or real(*a, **k))
    llm_client.complete_json("hi")
    assert handed == [PINNED] and calls[0]["url"].startswith(PINNED)


def test_a_stored_key_without_a_pinned_url_goes_to_the_provider_address_not_to_an_env_url(sent, tmp_path, monkeypatch):
    calls, _ = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY}})
    monkeypatch.setenv("OPENAI_BASE_URL", "https://elsewhere.example.test/v1")
    llm_client.complete_json("hi")
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"


def test_the_store_wins_over_env(sent, tmp_path, monkeypatch):
    calls, _ = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY}})
    monkeypatch.setenv("OPENAI_API_KEY", ENV_CANARY)
    llm_client.complete_json("hi")
    assert calls[0]["headers"]["Authorization"] == f"Bearer {CANARY}"


@pytest.mark.parametrize("entries", [None, {}, {"openrouter": {"key": OTHER_CANARY}}, {"openai": {"key": ""}}])
def test_env_is_used_only_when_the_store_has_no_key_for_the_provider(sent, tmp_path, monkeypatch, entries):
    calls, _ = sent
    if entries is not None:
        write_secret_store(tmp_path, entries)
    monkeypatch.setenv("OPENAI_API_KEY", ENV_CANARY)
    llm_client.complete_json("hi")
    assert calls[0]["headers"]["Authorization"] == f"Bearer {ENV_CANARY}"
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"


def test_another_providers_key_is_never_used_and_the_call_refuses_and_logs(sent, tmp_path, caplog):
    calls, _ = sent
    write_secret_store(tmp_path, {"openrouter": {"key": OTHER_CANARY}})
    with caplog.at_level("ERROR", logger="llm_client"), pytest.raises(llm_client.LlmUnavailable):
        llm_client.complete_json("hi")
    assert calls == []
    rows = _ledger(tmp_path)
    assert rows[-1]["decision"] == "refused" and rows[-1]["provider"] == "openai"
    assert "No API key for openai" in caplog.text
    assert OTHER_CANARY not in caplog.text + _ledger_text(tmp_path)


def test_a_key_in_the_environment_for_another_provider_is_not_used(sent, tmp_path, monkeypatch):
    calls, _ = sent
    monkeypatch.setenv("OPENROUTER_API_KEY", OTHER_CANARY)
    monkeypatch.setenv("GROQ_API_KEY", OTHER_CANARY)
    with pytest.raises(llm_client.LlmUnavailable):
        llm_client.complete_json("hi")
    assert calls == []


def test_the_store_is_not_opened_for_a_provider_it_cannot_hold(tmp_path, monkeypatch):
    write_secret_store(tmp_path, {"openai": {"key": CANARY}}, mode=0o644)  # would refuse if it were read
    assert secret_store.get_credential("groq") is None
    assert secret_store.get_credential("deepseek") is None
    assert secret_store.get_credential("ollama") is None


def test_the_key_never_reaches_logs_ledger_errors_or_the_environment(sent, tmp_path, monkeypatch, caplog):
    calls, replies = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY}})
    replies.append(_Response(400, text=f'{{"error": {{"message": "bad key {CANARY}"}}}}'))
    with caplog.at_level("DEBUG"), pytest.raises(llm_client.LlmRefused) as caught:
        llm_client.complete_json("hi")
    replies.append(_Response(502, text="x"))
    replies.extend([requests.ConnectionError(f"cannot reach with {CANARY}")] * 3)
    with caplog.at_level("DEBUG"), pytest.raises(llm_client.LlmUnavailable) as caught_two:
        llm_client.complete_json("hi")
    llm_client.log.error("a caller formats %s", CANARY)
    for exc in (caught.value, caught_two.value):
        seen = exc
        while seen is not None:
            assert CANARY not in str(seen) and CANARY not in repr(seen)
            seen = seen.__cause__ or seen.__context__
    assert CANARY not in caplog.text
    assert CANARY not in _ledger_text(tmp_path)
    assert CANARY not in json.dumps(ai_gate.recent_rows())
    assert CANARY not in "".join(os.environ.values())
    assert [c["headers"]["Authorization"] for c in calls][0] == f"Bearer {CANARY}"  # it was used, and only there


def test_the_credential_object_does_not_show_the_key():
    assert CANARY not in repr(secret_store.Credential(api_key=CANARY, base_url=None, source="store"))


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_a_loose_permission_file_refuses_without_a_call_or_env_fallback(sent, tmp_path, monkeypatch, mode):
    calls, _ = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY}}, mode=mode)
    monkeypatch.setenv("OPENAI_API_KEY", ENV_CANARY)
    with pytest.raises(llm_client.LlmUnavailable) as caught:
        llm_client.complete_json("hi")
    assert calls == []
    assert CANARY not in str(caught.value) and str(tmp_path) not in str(caught.value)
    assert _ledger(tmp_path)[-1]["decision"] == "refused"
    assert CANARY not in _ledger_text(tmp_path)


@pytest.mark.parametrize("text", ["{not json", "[]", '"a string"', "\xff\xfe"])
def test_a_malformed_file_refuses_and_its_text_is_not_chained(sent, tmp_path, monkeypatch, text):
    calls, _ = sent
    path = write_secret_store(tmp_path, {})
    path.write_bytes(text.encode("latin-1") if text.startswith("\xff") else text.encode())
    monkeypatch.setenv("OPENAI_API_KEY", ENV_CANARY)
    with pytest.raises(llm_client.LlmUnavailable) as caught:
        llm_client.complete_json("hi")
    assert calls == []
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "{not json" not in str(caught.value)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_file_refuses(sent, tmp_path):
    calls, _ = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY}}, mode=0o000)
    with pytest.raises(llm_client.LlmUnavailable):
        llm_client.complete_json("hi")
    assert calls == []


def test_a_symlinked_file_refuses(sent, tmp_path):
    calls, _ = sent
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"openai": {"key": CANARY}}))
    real.chmod(0o600)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "ai.json").symlink_to(real)
    with pytest.raises(llm_client.LlmUnavailable):
        llm_client.complete_json("hi")
    assert calls == []


def test_a_bad_pinned_url_refuses(sent, tmp_path):
    calls, _ = sent
    write_secret_store(tmp_path, {"openai": {"key": CANARY, "baseUrl": "ftp://nope"}})
    with pytest.raises(llm_client.LlmUnavailable):
        llm_client.complete_json("hi")
    assert calls == []


def test_the_selected_provider_decides_not_the_key(tmp_path, monkeypatch, open_ai_budget):
    """Only an openrouter key is stored, openai is selected: no silent switch to openrouter."""
    select_provider(tmp_path, monkeypatch, "openai")
    write_secret_store(tmp_path, {"openrouter": {"key": OTHER_CANARY}})
    assert llm_client.active_provider() == "openai"
    with pytest.raises(llm_client.LlmUnavailable):
        llm_client.call_target()


def test_the_store_is_read_only_and_never_creates_the_directory(tmp_path):
    assert secret_store.get_credential("openai") is None
    assert not (tmp_path / "secrets").exists()


def test_status_cli_shows_source_and_last4_only(tmp_path, capsys):
    write_secret_store(tmp_path, {"openai": {"key": CANARY}})
    assert secret_store.main(["status", "openai"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"set": True, "source": "store", "last4": CANARY[-4:], "baseUrl": None}
    assert CANARY not in out


def test_the_standard_library_secrets_module_is_not_shadowed():
    import secrets

    assert len(secrets.token_hex(4)) == 8
    assert "python/llm" not in (getattr(secrets, "__file__", "") or "")
    assert "secrets" in sys.modules
