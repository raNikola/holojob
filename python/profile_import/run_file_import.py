#!/usr/bin/env python3
"""Read a file's bytes on stdin (the source id is argv[1]), print { ok: true, draft } or { ok: false, code }.

The answer never carries the file: a failure prints only a fixed code, and nothing is written to stderr or to disk.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_DIR))

MAX_BYTES = 60 * 1024 * 1024


def main() -> int:
    warnings.simplefilter("ignore")
    try:
        from profile_import.docx_reader import MAX_DOCX_BYTES, docx_to_text
        from profile_import.text_parser import TextImportError, parse_text

        source = sys.argv[1] if len(sys.argv) > 1 else ""
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if source == "resume_docx":
            if len(data) > MAX_DOCX_BYTES:
                raise TextImportError("too_large")
            text, notes = docx_to_text(data)
            draft = parse_text(text, "resume_docx")
            draft["warnings"] = [*draft["warnings"], *notes]
        else:
            raise TextImportError("invalid_request")
        result = {"ok": True, "draft": draft}
    except Exception as error:  # noqa: BLE001 - the answer is a fixed code, never the cause
        code = getattr(error, "code", None)
        result = {"ok": False, "code": code if isinstance(code, str) else "parse_failed"}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
