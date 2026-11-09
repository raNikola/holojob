#!/usr/bin/env python3
"""Read JSON stdin { before, after } (two profiles), print { ok: true, impact } or { ok: false, code }. Read-only; fixed codes only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_REQUEST_CHARS = 20_000_000


def main() -> int:
    try:
        from impact import impact_from_disk

        payload = json.loads(sys.stdin.read(MAX_REQUEST_CHARS) or "{}")
        before, after = payload.get("before"), payload.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("invalid_request")
        result = {"ok": True, "impact": impact_from_disk(before, after)}
    except Exception as error:  # noqa: BLE001 - the answer is a fixed code, never the cause
        result = {"ok": False, "code": "invalid_request" if isinstance(error, ValueError) and str(error) == "invalid_request" else "impact_failed"}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
