#!/usr/bin/env python3
"""Analyze one CV with the configured LLM provider.

Reads one JSON object on stdin: {"rawText", "fullName", "links"}. Prints one JSON
object. `--preview` prints what a run would send and to whom, and calls nothing.
The text is redacted first (redact.py); the redacted text is the only CV content
that reaches the provider, and the same text is what --preview returns.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("cv_analysis", "job_scoring"):
    path = str(ROOT / "python" / sub)
    if path not in sys.path:
        sys.path.insert(0, path)

from analysis import CV_SCHEMA, PROMPT_VERSION, build_prompt, fingerprint, verify  # noqa: E402
from llm_client import LlmRefused, LlmUnavailable, active_provider, complete_json, judge_model  # noqa: E402
import ai_gate  # noqa: E402 (on the path through llm_client)
from redact import redact_cv_text  # noqa: E402

CACHE_PATH = ROOT / "data" / "cache" / "cv_analysis.json"
LOCAL_PROVIDERS = {"ollama"}
SENT = ["the CV text, with the items below removed"]
NEVER_SENT = ["name", "e-mail addresses", "phone numbers", "links", "the rest of your profile", "questionnaire answers", "salary"]


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a CV with an LLM.")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--force", action="store_true", help="ignore a cached result")
    args = parser.parse_args()

    payload = json.loads(sys.stdin.read() or "{}")
    raw_text = payload.get("rawText") or ""
    if not raw_text.strip():
        print(json.dumps({"ok": False, "error": "The CV has no text to analyze."}))
        return 1

    redacted, removed = redact_cv_text(raw_text, payload.get("fullName") or "", payload.get("links") or [])
    provider = active_provider()
    model = judge_model(provider)
    key = fingerprint(redacted, provider, model)
    cache = _load_cache()
    cached = key in cache and not args.force

    if args.preview:
        print(json.dumps({
            "ok": True,
            "provider": provider,
            "model": model,
            "leavesServer": provider not in LOCAL_PROVIDERS,
            "cached": cached,
            "characters": len(redacted),
            "removed": removed,
            "sentText": redacted,
            "sent": SENT,
            "neverSent": NEVER_SENT,
            "fingerprint": key,
        }, ensure_ascii=False))
        return 0

    if cached:
        ai_gate.record_cache_hit(provider, model, feature="cv-analysis")
        entry = cache[key]
        facts, rejected = entry["facts"], entry["rejected"]
        analyzed_at = entry["analyzedAt"]
    else:
        try:
            with ai_gate.context(feature="cv-analysis"):
                raw = complete_json(build_prompt(redacted), schema=CV_SCHEMA, model=model, provider=provider)
        except (LlmUnavailable, LlmRefused) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1
        facts, rejected = verify(raw, redacted)
        analyzed_at = datetime.now(timezone.utc).isoformat()
        cache[key] = {"facts": facts, "rejected": rejected, "analyzedAt": analyzed_at}
        _save_cache(cache)

    print(json.dumps({
        "ok": True,
        "fromCache": cached,
        "fingerprint": key,
        "provider": provider,
        "model": model,
        "promptVersion": PROMPT_VERSION,
        "analyzedAt": analyzed_at,
        "facts": facts,
        "rejected": rejected,
        "removed": removed,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
