"""Bridge to the locally installed Claude Code CLI (subscription login, no API key).

Two modes:
- complete()/complete_json(): plain headless text generation (no tools).
- analyze_repo(): agentic run with read-only tools inside a repo, so Claude can
  walk the code and git history itself.

Every caller must handle (None, reason) gracefully — the pipeline falls back to
rule-based generation when Claude Code is missing, not logged in, or refused by
the AI budget gate (ai_gate.py; the CLI is a paid provider).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

import ai_gate

_CV_ANALYSIS = str(Path(__file__).resolve().parents[1] / "cv_analysis")
if _CV_ANALYSIS not in sys.path:
    sys.path.append(_CV_ANALYSIS)

import redact  # noqa: E402

logger = logging.getLogger(__name__)

READONLY_TOOLS = [
    "Read", "Grep", "Glob", "LS",
    # No git log or git shortlog: they print the commit authors' names and e-mail addresses, which would go to the provider.
    "Bash(git diff:*)",
    "Bash(git show:*)", "Bash(git branch:*)", "Bash(ls:*)", "Bash(wc:*)",
    "Bash(find:*)", "Bash(cat:*)",
]

_availability: dict | None = None


def safe_error(text, limit: int = 200) -> str:
    """Provider output that ends up in an error string, the ledger or a stored reason: e-mail addresses, phone numbers
    and links removed (redact.py), one line, cut to `limit`. The model can echo part of what it was sent."""
    cleaned, _ = redact.redact_cv_text(str(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip()[:limit]


def availability() -> dict:
    """{'available': bool, 'reason': str} — cached for the process lifetime.

    Checks the install and the login file only. It used to send a test prompt,
    which is a paid model call; the first real call now finds out the rest.
    """
    global _availability
    if _availability is not None:
        return _availability
    if not shutil.which("claude"):
        _availability = {"available": False, "reason": "claude CLI not installed (npm i -g @anthropic-ai/claude-code)"}
    elif not (Path.home() / ".claude" / ".credentials.json").exists():
        _availability = {"available": False, "reason": "Claude Code is not logged in — run `claude /login` once"}
    else:
        _availability = {"available": True, "reason": ""}
    if not _availability["available"]:
        logger.warning("Claude Code unavailable: %s", _availability["reason"])
    return _availability


def is_available() -> bool:
    return availability()["available"]


def _run(args: list[str], prompt: str, timeout: int, cwd: str | None = None) -> tuple[str | None, str]:
    try:
        ticket = ai_gate.reserve("claude-code", _model_of(args), len(prompt))
    except ai_gate.AiRefused as exc:
        return None, str(exc)
    text, err, usage = _call(args, prompt, timeout, cwd)
    ticket.finish(text is not None, input_tokens=usage.get("input_tokens"),
                  output_tokens=usage.get("output_tokens"), error=err or None,
                  reported_cost_usd=usage.get("reported_cost_usd"))
    return text, err


def _model_of(args: list[str]) -> str | None:
    return args[args.index("--model") + 1] if "--model" in args[:-1] else None


def usage_of(data: dict) -> dict:
    """Token counts (and the CLI's own cost figure) from `claude -p --output-format json`."""
    raw = data.get("usage") or {}
    out: dict = {}
    if isinstance(raw.get("input_tokens"), int) and isinstance(raw.get("output_tokens"), int):
        out["input_tokens"] = raw["input_tokens"] + int(raw.get("cache_read_input_tokens") or 0) \
            + int(raw.get("cache_creation_input_tokens") or 0)
        out["output_tokens"] = raw["output_tokens"]
    if isinstance(data.get("total_cost_usd"), (int, float)):
        out["reported_cost_usd"] = data["total_cost_usd"]
    return out


def _call(args: list[str], prompt: str, timeout: int, cwd: str | None) -> tuple[str | None, str, dict]:
    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json", *args],
            input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return None, f"Claude Code timed out after {timeout}s", {}
    except Exception as exc:
        return None, safe_error(exc), {}
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None, f"Unparseable Claude Code output: {safe_error(proc.stdout)}", {}
    if data.get("is_error"):
        return None, safe_error(data.get("result")) or "Claude Code error", usage_of(data)
    return data.get("result") or "", "", usage_of(data)


def complete(prompt: str, *, timeout: int = 240) -> tuple[str | None, str]:
    """Plain text generation. Returns (text, '') or (None, reason)."""
    if not is_available():
        return None, availability()["reason"]
    return _run(["--tools", ""], prompt, timeout)


def extract_json(text: str):
    """Pull the first JSON object out of a model response (handles ``` fences)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    brace = text.find("{")
    if brace >= 0:
        candidates.append(text[brace: text.rfind("}") + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def complete_json(prompt: str, *, timeout: int = 240) -> tuple[dict | None, str]:
    """Generation that must return a JSON object. Returns (dict, '') or (None, reason)."""
    text, err = complete(prompt, timeout=timeout)
    if text is None:
        return None, err
    data = extract_json(text)
    if data is None:
        return None, f"No JSON object in response: {safe_error(text)}"
    return data, ""


def analyze_repo(repo_path: str, prompt: str, *, timeout: int = 600) -> tuple[dict | None, str]:
    """Agentic repo analysis: Claude Code explores the repo with read-only tools.

    The prompt must ask for a JSON object as the final answer.
    """
    if not is_available():
        return None, availability()["reason"]
    args = ["--allowed-tools", ",".join(READONLY_TOOLS)]
    text, err = _run(args, prompt, timeout, cwd=repo_path)
    if text is None:
        return None, err
    data = extract_json(text)
    if data is None:
        return None, f"No JSON object in response: {safe_error(text)}"
    return data, ""
