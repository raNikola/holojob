"""LLM access for job-fact extraction.

Extraction asks one question -- "give me this JSON about this ad" -- and the
provider answering it is a configuration choice. Everything except the Claude
Code CLI speaks the OpenAI chat-completions shape, so a provider is a table
row (address, key variable, default model, how it enforces JSON) rather than
a code path.

Choosing one:

    HOLOJOB_LLM_PROVIDER=deepseek

Without it, the first provider whose key is present wins, and the CLI is the
fallback. Every provider reads three optional overrides, so a new endpoint
needs no code:

    <PROVIDER>_API_KEY     <PROVIDER>_MODEL     <PROVIDER>_BASE_URL

Keys are read from the environment only. They are never arguments, never
logged, and never written to the jobs file.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

CLI_MODEL = "haiku"
CLI_TIMEOUT = 240

HTTP_TIMEOUT = 90
HTTP_RETRIES = 3

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


class LlmUnavailable(RuntimeError):
    """The provider could not be reached, timed out, or is not configured."""


class LlmRefused(RuntimeError):
    """The provider answered, but not with something usable."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_env: str
    default_model: str
    # "schema" enforces our JSON schema, "object" only guarantees valid JSON,
    # "none" leaves it to the prompt. _loose_json and _coerce cover all three.
    json_mode: str


# Model names last checked 2026-10-22 against each provider's own docs (OpenAI
# also against its models API). Compare against that date at the next check.
# Defaults, not promises: model names move. Override with <PROVIDER>_MODEL.
PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        name="openai",
        base_url="https://api.openai.com/v1",
        key_env="OPENAI_API_KEY",
        default_model="gpt-6-luna",
        json_mode="schema",
    ),
    "deepseek": Provider(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-flash",
        json_mode="object",
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
        default_model="qwen/qwen-2.5-72b-instruct",
        json_mode="object",
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        default_model="openai/gpt-oss-120b",
        json_mode="object",
    ),
    "ollama": Provider(
        name="ollama",
        base_url="http://localhost:11434/v1",
        key_env="OLLAMA_API_KEY",  # unused by Ollama; kept for uniformity
        default_model="qwen2.5:7b",
        json_mode="object",
    ),
    # Point this one anywhere with LLM_BASE_URL / LLM_API_KEY / LLM_MODEL.
    "custom": Provider(
        name="custom",
        base_url="",
        key_env="LLM_API_KEY",
        default_model="",
        json_mode="object",
    ),
}

# Fit judgement weighs an ad against a candidate, which is harder than reading
# facts out of an ad, so it gets a stronger model where the provider has one.
# Override with <PROVIDER>_JUDGE_MODEL; providers not listed use their _MODEL.
JUDGE_MODELS = {
    "claude-code": "sonnet",
    "openai": "gpt-6.1-sol",
    "deepseek": "deepseek-v4-pro",
}

KEYLESS = {"ollama", "claude-code"}

# Order used when nothing is configured: cheapest capable first.
PREFERENCE = ("deepseek", "openrouter", "groq", "openai", "ollama")


def _env(provider: str, suffix: str) -> str | None:
    return os.environ.get(f"{provider.upper().replace('-', '_')}_{suffix}")


def resolve(name: str) -> Provider:
    base = PROVIDERS.get(name)
    if base is None:
        raise LlmUnavailable(
            f"unknown provider {name!r}; known: {', '.join(sorted(PROVIDERS))}, claude-code"
        )
    prefix = "LLM" if name == "custom" else name
    return Provider(
        name=base.name,
        base_url=(_env(prefix, "BASE_URL") or base.base_url).rstrip("/"),
        key_env=base.key_env,
        default_model=_env(prefix, "MODEL") or base.default_model,
        json_mode=base.json_mode,
    )


def active_provider() -> str:
    chosen = (os.environ.get("HOLOJOB_LLM_PROVIDER") or "").strip().lower()
    if chosen:
        return chosen
    for name in PREFERENCE:
        if name in KEYLESS:
            continue
        if os.environ.get(PROVIDERS[name].key_env):
            return name
    return "claude-code"


def judge_model(provider: str) -> str | None:
    """The model used for fit judgement; None means the provider default."""
    name = provider.lower()
    if name in ("claude", "cli"):
        name = "claude-code"
    prefix = "LLM" if name == "custom" else name
    return _env(prefix, "JUDGE_MODEL") or JUDGE_MODELS.get(name)


def describe_available() -> list[str]:
    """Which providers are configured right now -- for diagnostics only."""
    ready = []
    for name, provider in PROVIDERS.items():
        if name in KEYLESS or os.environ.get(provider.key_env):
            if name == "custom" and not _env("LLM", "BASE_URL"):
                continue
            ready.append(name)
    return ready + ["claude-code"]


# --- claude-code CLI -------------------------------------------------------


def _cli_json(prompt: str, model: str) -> dict:
    args = ["claude", "-p", "--output-format", "json", "--tools", ""]
    if model:
        args += ["--model", model]

    try:
        proc = subprocess.run(
            args, input=prompt, capture_output=True, text=True, timeout=CLI_TIMEOUT
        )
    except FileNotFoundError as exc:
        raise LlmUnavailable("claude CLI not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise LlmUnavailable(f"claude CLI timed out after {CLI_TIMEOUT}s") from exc

    if not proc.stdout.strip():
        raise LlmUnavailable(proc.stderr.strip()[:300] or "claude CLI returned nothing")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LlmUnavailable(f"unparseable CLI output: {proc.stdout[:200]}") from exc

    if payload.get("is_error"):
        raise LlmRefused(
            payload.get("result") or "claude CLI error -- run `claude` and /login once"
        )

    return _loose_json(payload.get("result") or "")


def _loose_json(text: str) -> dict:
    """Recover one JSON object from a reply that may be fenced or prefaced."""
    text = _FENCE_RE.sub("", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LlmRefused(f"no JSON object in reply: {text[:200]}")


# --- OpenAI-compatible HTTP ------------------------------------------------


def _http_json(provider: Provider, prompt: str, schema: dict | None, model: str) -> dict:
    import requests

    if not provider.base_url:
        raise LlmUnavailable(
            f"{provider.name}: no base URL -- set {provider.name.upper()}_BASE_URL"
        )

    key = os.environ.get(provider.key_env)
    if not key and provider.name not in KEYLESS:
        raise LlmUnavailable(f"{provider.key_env} is not set in the container")

    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if schema and provider.json_mode == "schema":
        body["response_format"] = {"type": "json_schema", "json_schema": schema}
    elif provider.json_mode in ("schema", "object"):
        body["response_format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    url = f"{provider.base_url}/chat/completions"
    last_error = ""

    for attempt in range(HTTP_RETRIES):
        try:
            response = requests.post(
                url, headers=headers, json=body, timeout=HTTP_TIMEOUT
            )
        except requests.RequestException as exc:
            last_error = str(exc)[:200]
            time.sleep(2.0 * (attempt + 1))
            continue

        if response.status_code in (401, 403):
            raise LlmUnavailable(f"{provider.name} rejected the key ({response.status_code})")
        if response.status_code == 400:
            # A body the endpoint will not accept is our bug, not a blip.
            raise LlmRefused(f"{provider.name} rejected the request: {response.text[:300]}")
        if response.status_code in (408, 429, 500, 502, 503, 529):
            last_error = f"HTTP {response.status_code}"
            time.sleep(2.0 * (attempt + 1))
            continue
        if not response.ok:
            raise LlmUnavailable(
                f"{provider.name} HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LlmRefused("reply was cut off before the JSON ended")
        content = (choice.get("message") or {}).get("content") or ""
        if not content.strip():
            raise LlmRefused(f"{provider.name} returned an empty message")
        return _loose_json(content)

    raise LlmUnavailable(
        f"{provider.name} unreachable after {HTTP_RETRIES} tries: {last_error}"
    )


# --- public ----------------------------------------------------------------


def complete_json(
    prompt: str,
    schema: dict | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """Ask for one JSON object.

    `schema` is enforced by providers that can and ignored by the rest, so
    callers pass it unconditionally and validate the result either way.
    """
    name = (provider or active_provider()).lower()

    if name in ("claude-code", "claude", "cli"):
        return _cli_json(prompt, model or CLI_MODEL)

    resolved = resolve(name)
    return _http_json(resolved, prompt, schema, model or resolved.default_model)