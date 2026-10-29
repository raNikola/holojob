"""The one AI provider selection, shared by the browser / Node path and the Python pipeline.

File: data/config/ai-settings.json (CAREER_OS_CONFIG_DIR, or CAREER_OS_AI_SELECTION for the exact file), written
only by save() through the Settings screen (scripts/ai-settings-handler.js -> `ai_gate.py selection-put`).

    { "provider": "openai", "model": "...", "temperature": 0.3, "maxTokens": 2000,
      "baseUrl": "", "features": { "jobAnalysis": true, ... } }

No secret is ever part of it: keys and the base URL a key is pinned to live in data/secrets/ (scripts/secret-store.js).
`baseUrl` here is only for ollama, which has no credential.

There is no default provider. A missing file means nothing is selected and every AI call refuses; an unreadable or
invalid file refuses too. Environment keys never choose a provider. Each side that cannot run the selected provider
refuses it; neither falls back to another one. Validation, the paid / unknown-class confirm rule and the atomic write
are here, the way ai_gate.py holds them for the budget settings.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import ai_gate

ROOT = Path(__file__).resolve().parents[2]

# Every provider that has a row in src/data/aiPricing.json. A path with no implementation for one refuses it.
PROVIDERS = ("claude-code", "mock", "ollama", "openai", "openrouter", "claude", "gemini", "deepseek", "groq")

FEATURES = (
    "jobAnalysis", "resumeEnhancement", "coverLetter", "interviewPrep", "outreach",
    "careerStrategy", "skillGap", "applicationStrategy", "companyIntelligence",
)

DEFAULTS = {
    "provider": None,
    "model": None,
    "temperature": 0.3,
    "maxTokens": 2000,
    "baseUrl": "",
    "features": {name: True for name in FEATURES},
}
KEYS = tuple(DEFAULTS)

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}")
MAX_TOKENS = 200_000
MAX_URL = 300

NOT_SELECTED = "No AI provider selected (Settings > AI Provider). Nothing was sent."


class SelectionError(RuntimeError):
    """No usable selection. The message is fixed text and says what to do."""


def selection_path() -> Path:
    explicit = os.environ.get("CAREER_OS_AI_SELECTION")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("CAREER_OS_CONFIG_DIR") or ROOT / "data" / "config") / "ai-settings.json"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _plain_url(text: str) -> bool:
    try:
        url = urlparse(text)
    except ValueError:
        return False
    return (url.scheme in ("http", "https") and bool(url.hostname) and not url.username and not url.password
            and not url.query and not url.fragment and len(text) <= MAX_URL)


def validate(candidate, *, complete: bool = False) -> list[str]:
    """Errors for a selection (complete=True: the whole object) or a partial patch. Strict: unknown keys are errors."""
    if not isinstance(candidate, dict):
        return ["settings must be a JSON object"]
    errors = [f"unknown setting: {key}" for key in candidate if key not in KEYS]
    if complete:
        for key in ("provider", "model"):
            if candidate.get(key) is None:
                errors.append(f"{key} is required")
    if "provider" in candidate and candidate["provider"] is not None and candidate["provider"] not in PROVIDERS:
        errors.append(f"provider must be one of: {', '.join(PROVIDERS)}")
    if "model" in candidate and candidate["model"] is not None and not (
            isinstance(candidate["model"], str) and _MODEL.fullmatch(candidate["model"])):
        errors.append("model must be 1 to 100 characters: letters, digits and . _ : / @ + -")
    if "temperature" in candidate and not (_number(candidate["temperature"]) and 0 <= candidate["temperature"] <= 2):
        errors.append("temperature must be a number from 0 to 2")
    if "maxTokens" in candidate and not (_integer(candidate["maxTokens"]) and 1 <= candidate["maxTokens"] <= MAX_TOKENS):
        errors.append(f"maxTokens must be a whole number from 1 to {MAX_TOKENS}")
    if "baseUrl" in candidate:
        url = candidate["baseUrl"]
        if not isinstance(url, str) or (url and not _plain_url(url)):
            errors.append("baseUrl must be empty or a plain http(s) URL without credentials, query or fragment")
        elif url and candidate.get("provider", "ollama") != "ollama":
            errors.append("baseUrl is only for ollama; a keyed provider's URL is set with its key in Settings > Privacy")
    if "features" in candidate:
        features = candidate["features"]
        if not isinstance(features, dict):
            errors.append("features must be an object")
        else:
            for key, value in features.items():
                if key not in FEATURES:
                    errors.append(f"unknown setting: features.{key}")
                elif not isinstance(value, bool):
                    errors.append(f"features.{key} must be true or false")
    return errors


def read() -> dict:
    """{"selection": dict | None, "error": str | None}. A missing file is no selection; an unusable one is an error."""
    path = selection_path()
    if not path.exists():
        return {"selection": None, "error": None}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"selection": None, "error": f"{path.name} unreadable: {exc}"}
    errors = validate(stored, complete=True)
    if errors:
        return {"selection": None, "error": f"{path.name} is not valid: {errors[0]}"}
    return {"selection": {**DEFAULTS, **stored, "features": {**DEFAULTS["features"], **stored.get("features", {})}},
            "error": None}


def require() -> dict:
    """The selection, or SelectionError (nothing selected, or the file is unusable). Never a default."""
    result = read()
    if result["selection"] is None:
        raise SelectionError(result["error"] or NOT_SELECTED)
    return result["selection"]


def _target(selection: dict) -> tuple[str, str, str | None]:
    return selection["provider"], selection["model"], selection.get("baseUrl") or None


def describe_class(selection: dict) -> dict:
    provider, model, base_url = _target(selection)
    return ai_gate.classify(provider, model, base_url)


def provider_classes() -> list[dict]:
    return [{"name": name, "class": ai_gate.classify(name)["class"]} for name in PROVIDERS]


def save(patch, confirm: bool = False) -> dict:
    """Apply a (partial) selection. {ok, selection, class} | {ok: False, errors} | {ok: False, needsConfirm, increases}.

    Choosing a different provider / model / base URL whose class is paid or unknown needs confirm=True, as raising a
    budget limit does. Changing temperature, tokens or a toggle never does.
    """
    errors = validate(patch)
    if errors:
        return {"ok": False, "errors": errors}
    with ai_gate._locked():
        current = read()
        if current["error"]:
            return {"ok": False, "errors": [f"{current['error']}; fix or remove the file, it was left as it is"]}
        before = current["selection"]
        merged = {**DEFAULTS, **(before or {}), **patch}
        merged["features"] = {**DEFAULTS["features"], **((before or {}).get("features") or {}), **patch.get("features", {})}
        if merged["provider"] != "ollama" and "baseUrl" not in patch:
            merged["baseUrl"] = ""  # a URL chosen for ollama does not follow a switch to another provider
        errors = validate(merged, complete=True)
        if errors:
            return {"ok": False, "errors": errors}
        price = describe_class(merged)
        changed = before is None or _target(before) != _target(merged)
        increases = []
        if changed and ai_gate.is_paid(price["class"]):
            kind = "has no known price" if price["class"] == "unknown" else "is a paid provider"
            increases.append(f"{merged['provider']} / {merged['model']} {kind} ({price['class']}): "
                             "its calls count against your AI budget")
        if increases and not confirm:
            return {"ok": False, "needsConfirm": True, "increases": increases}
        path = selection_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        ai_gate._atomic_write(path, merged)
    return {"ok": True, "selection": merged, "class": price["class"], "increases": increases}


def get() -> dict:
    """What GET /api/ai/selection answers."""
    result = read()
    out = {"selection": result["selection"], "providers": provider_classes()}
    if result["error"]:
        out["error"] = result["error"]
    if result["selection"]:
        out["class"] = describe_class(result["selection"])["class"]
    return out
