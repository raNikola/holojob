#!/usr/bin/env python3
"""Read JSON stdin { text }, print { ok: true, draft } or { ok: false, code }.

The answer never carries the text: a failure prints only a fixed code, and nothing is
written to stderr or to disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_REQUEST_CHARS = 2_000_000


def main() -> int:
    try:
        from text_parser import TextImportError, parse_text

        payload = json.loads(sys.stdin.read(MAX_REQUEST_CHARS) or "{}")
        if not isinstance(payload, dict):
            raise TextImportError("invalid_request")
        result = {"ok": True, "draft": parse_text(payload.get("text"))}
    except Exception as error:  # noqa: BLE001 - the answer is a fixed code, never the cause
        code = getattr(error, "code", None)
        result = {"ok": False, "code": code if isinstance(code, str) else "parse_failed"}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
