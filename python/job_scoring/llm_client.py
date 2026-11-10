"""LLM access for job-fact extraction.

Extraction asks one question -- "give me this JSON about this ad" -- and the
provider answering it is a configuration choice. Everything except the Claude
Code CLI speaks the OpenAI chat-completions shape, so a provider is a table
row (address, key variable, default model, how it enforces JSON) rather than
a code path.

Choosing one: Settings > AI Provider. The choice is stored once, in data/config/ai-settings.json, and the
browser path reads the same file (llm/ai_selection.py). Nothing else picks a provider: no environment key, no
HOLOJOB_LLM_PROVIDER, no CLI fallback. With no usable selection a call refuses. Every provider reads three
optional overrides, so a new endpoint needs no code:

    <PROVIDER>_API_KEY     <PROVIDER>_MODEL     <PROVIDER>_BASE_URL

Keys: the selected provider's key and pinned base URL come from the server secret store (data/secrets/, read-only
here, llm/secret_store.py; set in Settings > Privacy). Only when the store has no key for that provider does the
environment variable (OPENAI_API_KEY, ...) apply. A key is never an argument, never copied into os.environ, never
logged, never in an error or ledger row (exact-value masking), and never written to the jobs file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

_LLM_DIR = str(Path(__file__).resolve().parents[1] / "llm")
if _LLM_DIR not in sys.path:
    sys.path.insert(0, _LLM_DIR)
import ai_gate  # noqa: E402  the AI budget gate; every call below goes through it
import ai_selection  # noqa: E402  the one provider selection, shared with the Node path
import claude_code  # noqa: E402
import secret_store  # noqa: E402  read-only view of data/secrets/ (the Node store is the only writer)
from secret_store import Credential  # noqa: E402

log = logging.getLogger("llm_client")


class _MaskFilter(logging.Filter):
    """A resolved key never reaches a log line, whatever text a caller formats into it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = secret_store.mask(record.getMessage()), ()
        return True


log.addFilter(_MaskFilter())

CLI_MODEL = "haiku"
CLI_TIMEOUT = 240

HTTP_TIMEOUT = 90
HTTP_RETRIES = 3

# Sampling settings sent to OpenAI (ENGINE_CONTRACT.md section 6: "deterministic
# settings where the provider allows"). OpenAI's determinism is best effort, not
# a guarantee: the same seed and temperature 0 make repeated answers far more
# alike, but a backend change can still alter one. So this narrows the drift the
# stability test measures (match_engine/stability.py); it does not remove it,
# and nothing may depend on two answers being byte-identical.
DETERMINISTIC = {"temperature": 0, "seed": 20261025}
DETERMINISTIC_PROVIDERS = {"openai"}
# (provider, model, setting) a 400 has shown the model rejects, e.g. reasoning
# models that take no temperature; later calls leave it out.
_REJECTED: set[tuple[str, str, str]] = set()

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


class LlmUnavailable(RuntimeError):
    """The provider could not be reached, timed out, or is not configured."""


class LlmRefused(RuntimeError):
    """The provider answered, but not with something usable."""


class GuardrailRefused(LlmUnavailable):
    """The AI budget gate refused the call before it was made (ai_gate.py). Recorded; never retry it.

    A subclass of LlmUnavailable, so a caller that only knows "no answer" still
    degrades instead of crashing; batch callers catch it first and stop sending.
    """

    def __init__(self, reason: str):
        super().__init__(f"AI call refused: {reason}")
        self.reason = reason


class CredentialRefused(LlmUnavailable):
    """The selected provider has no usable key, or the secret store file cannot be trusted. Nothing is sent."""


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


def credential_for(provider: Provider) -> Credential | None:
    """The key for the selected provider and nothing else: the store first, then that provider's own variable.

    A store file that cannot be trusted refuses; the variable is no fallback for that. No key at all refuses too,
    and no other provider is tried. Ollama and the CLI need none.
    """
    if provider.name in KEYLESS:
        return None
    try:
        found = secret_store.get_credential(provider.name)
    except secret_store.SecretStoreError as exc:
        raise CredentialRefused(str(exc)) from None
    if found:
        return found
    value = (os.environ.get(provider.key_env) or "").strip()
    if value:
        secret_store.register(value)
        return Credential(api_key=value, base_url=None, source="env")
    raise CredentialRefused(
        f"No API key for {provider.name}: set it in Settings > Privacy (or {provider.key_env} in .env). Nothing was sent."
    )


def resolve_call(name: str) -> tuple[Provider, Credential | None]:
    """The provider and its credential for one call. A stored key goes only to its pinned base URL, else to the
    provider's own address; the *_BASE_URL variable moves a key from .env, never one from the store."""
    provider = resolve(name)
    credential = credential_for(provider)
    if credential is not None and credential.source == "store":
        provider = replace(provider, base_url=(credential.base_url or PROVIDERS[name].base_url).rstrip("/"))
    return provider, credential


# Providers this module can run. The selection may name others (claude, gemini, mock are browser / Node only);
# those are refused here, never swapped for one that works.
RUNNABLE = set(PROVIDERS) | {"claude-code"}


class NoProviderSelected(LlmUnavailable):
    """Nothing is selected, the selection is unusable, or this path cannot run the selected provider."""


def active_provider() -> str:
    """The provider the owner selected in Settings (data/config/ai-settings.json); the same file the browser path reads.

    No environment key, no HOLOJOB_LLM_PROVIDER and no claude-code fallback picks one. When there is no usable
    selection, or this pipeline cannot run the selected provider, the refusal is logged and written to the ledger
    and NoProviderSelected is raised.
    """
    try:
        selected = ai_selection.require()
    except ai_selection.SelectionError as exc:
        _refuse_selection("", None, str(exc))
    name = selected["provider"]
    if name not in RUNNABLE:
        _refuse_selection(name, selected["model"],
                          f"{name} is selected but the Python pipeline cannot run it; select another provider in Settings. "
                          "Nothing was sent.")
    return name


def peek_provider() -> str:
    """The selected provider, or "" when there is none. Never raises, logs or records: for work that makes no call
    (a local re-score re-applies cached judgements keyed by provider)."""
    try:
        return ai_selection.require()["provider"]
    except ai_selection.SelectionError:
        return ""


def _refuse_selection(provider: str, model: str | None, reason: str):
    log.error("AI call refused: %s", reason)
    try:
        ai_gate.refuse(provider, model, reason)
    except OSError as exc:  # the ledger is unwritable; the refusal still stands
        log.error("could not record the refusal: %s", exc)
    raise NoProviderSelected(reason)


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


def _cli_json(prompt: str, model: str, usage: dict | None = None) -> dict:
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

    if usage is not None:
        usage.update(claude_code.usage_of(payload))
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


def _rejected_setting(error_text: str, body: dict) -> str | None:
    """The DETERMINISTIC setting a 400 names, when the body carries it."""
    try:
        error = json.loads(error_text).get("error") or {}
    except (json.JSONDecodeError, AttributeError):
        error = {}
    named = f"{error.get('param') or ''} {error.get('message') or ''}".lower()
    return next((k for k in DETERMINISTIC if k in body and k in named), None)


class FlexUnavailable(LlmUnavailable):
    """Flex processing had no capacity (HTTP 429 / 503). Never retried and never moved to standard: changing the tier
    is the owner's choice (Settings > AI Provider)."""


def service_tier_for(provider_name: str, explicit: str | None = None) -> str | None:
    """The tier to request: the caller's, else the stored selection's serviceTier (standard when unset). Only OpenAI
    has tiers; every other provider gets None."""
    if provider_name != "openai":
        return None
    if explicit:
        return explicit
    try:
        return ai_selection.read()["selection"].get("serviceTier") or ai_gate.DEFAULT_TIER
    except (AttributeError, KeyError, TypeError):
        return ai_gate.DEFAULT_TIER


def _http_json(provider: Provider, prompt: str, schema: dict | None, model: str,
               usage: dict | None = None, credential: Credential | None = None,
               service_tier: str | None = None) -> dict:
    import requests

    if not provider.base_url:
        raise LlmUnavailable(
            f"{provider.name}: no base URL -- set {provider.name.upper()}_BASE_URL"
        )

    key = credential.api_key if credential else None
    safe = secret_store.mask

    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if schema and provider.json_mode == "schema":
        body["response_format"] = {"type": "json_schema", "json_schema": schema}
    elif provider.json_mode in ("schema", "object"):
        body["response_format"] = {"type": "json_object"}
    if provider.name == "openai" and service_tier:
        if ai_gate.api_tier(service_tier) is None:
            raise LlmRefused(f"unknown service tier {service_tier!r}")
        body["service_tier"] = ai_gate.api_tier(service_tier)
    if provider.name in DETERMINISTIC_PROVIDERS:
        body.update({k: v for k, v in DETERMINISTIC.items() if (provider.name, model, k) not in _REJECTED})

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    url = f"{provider.base_url}/chat/completions"
    last_error = ""

    # A rejected DETERMINISTIC setting is asked again without it; that is not
    # one of the HTTP_RETRIES, which are for transient failures.
    attempt = 0
    while attempt < HTTP_RETRIES:
        if usage is not None:
            usage["attempts"] = usage.get("attempts", 0) + 1
        try:
            response = requests.post(
                url, headers=headers, json=body, timeout=HTTP_TIMEOUT
            )
        except requests.RequestException as exc:
            last_error = safe(str(exc))[:200]
            attempt += 1
            time.sleep(2.0 * attempt)
            continue

        if response.status_code in (401, 403):
            raise LlmUnavailable(f"{provider.name} rejected the key ({response.status_code})")
        if response.status_code == 400 and (rejected := _rejected_setting(response.text, body)):
            # The model takes no such setting: ask again without it, and remember.
            _REJECTED.add((provider.name, model, rejected))
            body.pop(rejected)
            continue
        if response.status_code == 400:
            # A body the endpoint will not accept is our bug, not a blip.
            raise LlmRefused(safe(f"{provider.name} rejected the request: {response.text[:300]}"))
        if service_tier == "flex" and response.status_code in (429, 503):
            if usage is not None:
                usage["flex_unavailable"] = True
            raise FlexUnavailable(
                f"{provider.name} flex processing is unavailable right now (HTTP {response.status_code}, no charge). "
                "Not retried and not switched to standard; choose the standard tier in Settings to continue.")
        if response.status_code in (408, 429, 500, 502, 503, 529):
            last_error = f"HTTP {response.status_code}"
            attempt += 1
            time.sleep(2.0 * attempt)
            continue
        if not response.ok:
            raise LlmUnavailable(safe(f"{provider.name} HTTP {response.status_code}: {response.text[:200]}"))

        data = response.json()
        if usage is not None:
            counted = data.get("usage") or {}
            if isinstance(counted.get("prompt_tokens"), int) and isinstance(counted.get("completion_tokens"), int):
                usage.update(input_tokens=counted["prompt_tokens"], output_tokens=counted["completion_tokens"])
                cached = (counted.get("prompt_tokens_details") or {}).get("cached_tokens")
                if isinstance(cached, int) and not isinstance(cached, bool):
                    usage["cached_input_tokens"] = cached
            if service_tier:
                usage["service_tier_actual"] = data.get("service_tier")
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
    name, model, resolved, credential = _target(provider, model)
    if name == "claude-code":
        return _gated(name, model, None, prompt, lambda usage: _cli_json(prompt, model, usage))

    tier = service_tier_for(name)
    return _gated(name, model, resolved.base_url, prompt,
                  lambda usage: _http_json(resolved, prompt, schema, model, usage, credential, tier), tier)


def _target(provider: str | None, model: str | None) -> tuple[str, str, Provider | None, Credential | None]:
    """One resolution per call: the gate is told the same base URL the request is sent to. A missing key or an
    untrusted store file is a refusal: logged, a ledger row, and the call is never reserved or made."""
    name = (provider or active_provider()).lower()
    if name in ("claude-code", "claude", "cli"):
        return "claude-code", model or CLI_MODEL, None, None
    refusal = None
    try:
        resolved, credential = resolve_call(name)
    except CredentialRefused as exc:
        refusal = str(exc)
    if refusal is not None:  # outside the except block: the refusal chains nothing
        _refuse_selection(name, model, refusal)
    return name, model or resolved.default_model, resolved, credential


def call_target(provider: str | None = None, model: str | None = None) -> tuple[str, str, str | None]:
    """(provider, model, base URL) a complete_json call with these arguments would use; for the budget gate."""
    name, model, resolved, _ = _target(provider, model)
    return name, model, resolved.base_url if resolved else None


def preflight(prompt_chars: int, provider: str | None = None, model: str | None = None):
    """ai_gate.check() for a batch about to call complete_json with these arguments; records nothing."""
    name, model, base_url = call_target(provider, model)
    return ai_gate.check(name, model, prompt_chars, base_url=base_url, service_tier=service_tier_for(name))


def _gated(provider: str, model: str, base_url: str | None, prompt: str, call, service_tier: str | None = None) -> dict:
    """Ask the budget gate first, then make the call once and record what it used.

    The HTTP retries inside one call are one ledger entry (`attempts` counts them).
    """
    try:
        ticket = ai_gate.reserve(provider, model, len(prompt), base_url=base_url, service_tier=service_tier)
    except ai_gate.AiRefused as exc:
        raise GuardrailRefused(exc.reason) from exc
    usage: dict = {}
    try:
        result = call(usage)
    except Exception as exc:
        ticket.finish(False, input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                      error=secret_store.mask(str(exc)), attempts=usage.get("attempts"),
                      reported_cost_usd=usage.get("reported_cost_usd"), **_tier_usage(usage))
        raise
    ticket.finish(True, input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                  attempts=usage.get("attempts"), reported_cost_usd=usage.get("reported_cost_usd"),
                  **_tier_usage(usage))
    return result


def _tier_usage(usage: dict) -> dict:
    return {"cached_input_tokens": usage.get("cached_input_tokens"),
            "service_tier_actual": usage.get("service_tier_actual"),
            "flex_unavailable": bool(usage.get("flex_unavailable"))}