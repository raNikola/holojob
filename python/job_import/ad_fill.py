#!/usr/bin/env python3
"""Fill from ad: read one job page for the Add job form. Writes nothing; no candidate data comes in.

    ad_fill.py fetch        stdin {"url": ...}             ->  the fields the page's JSON-LD states, what is missing, the page text
    ad_fill.py ai-preview   stdin {"pageText", "want": [...]}  ->  exactly what an AI step would send, and whether the gate allows it (no call)
    ad_fill.py ai-extract   stdin {"pageText", "want": [...]}  ->  the missing fields Claude Code read out of the (redacted) text; only after the caller's confirm

A fetch that fails or finds no readable ad answers {"ok": false, "error": <code>, "message": ...}; the form then changes
nothing. Prints one JSON object to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ad_reader  # noqa: E402
import safe_fetch  # noqa: E402


def fetch(payload: dict) -> dict:
    try:
        page = safe_fetch.fetch_page(str(payload.get("url") or ""))
    except safe_fetch.FetchRefused as exc:
        # The code and the HTTP status only; nothing from the page itself.
        return {"ok": False, "error": exc.code, "status": exc.status, "message": exc.message}
    ad = ad_reader.read_ad(page.html)
    if not ad["readable"]:
        # No posting data and next to no text, but scripts: the content is drawn by JavaScript, which is not run here.
        scripted = "<script" in page.html.lower()
        return {"ok": False, "error": "js_only" if scripted else "unreadable", "message": "No job posting could be read from this page."}
    return {"ok": True, "finalUrl": page.url, **ad}


def _profile():
    import os

    import ad_ai

    return ad_ai.load_profile(Path(os.environ.get("HOLOJOB_PROFILE_PATH") or ad_ai.PROFILE_PATH))


def _ai(run):
    import ad_ai

    try:
        return run(ad_ai)
    except ad_ai.Refused as exc:
        return {"ok": False, "error": exc.code, "message": exc.message}


def ai_preview(payload: dict) -> dict:
    return _ai(lambda ai: ai.preview(str(payload.get("pageText") or ""), payload.get("want") or [], _profile()))


def ai_extract(payload: dict) -> dict:
    return _ai(lambda ai: ai.extract(str(payload.get("pageText") or ""), payload.get("want") or [], _profile()))


COMMANDS = {"fetch": fetch, "ai-preview": ai_preview, "ai-extract": ai_extract}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command = COMMANDS.get(argv[0]) if argv else None
    if command is None:
        print(json.dumps({"ok": False, "error": "usage", "message": "unknown command"}))
        return 2
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    print(json.dumps(command(payload if isinstance(payload, dict) else {})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
