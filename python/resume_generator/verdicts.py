"""The fact gate's verdict on a generated document, kept on the server next to the file.

A verdict is a small file `.<name>.verdict.json` in the same folder as the document it judges: whether the gate passed, why not,
and the sha256 of the document as it was judged. The application store reads it when a document is attached to an application
(`scripts/document-verdicts.js`, the same format), so a document that was never judged, failed, or was changed afterwards cannot
be attached. Nothing in the browser can set it: the only writers are the tailoring run and the accept step in Python.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from atomic_write import PRIVATE_FILE_MODE, write_text_atomic

# Bump when the gate's rules change in a way that should invalidate earlier verdicts.
GATE_VERSION = 1


# What an application can attach: the generated CV and cover letter files (never a verdict file, a draft or anything hidden).
DOCUMENT_RE = re.compile(r"^(?!\.)(?:tailored_resume\.(?:md|html)|cover_letter\.md|ai_cover_letter\.md|.+_(?:Resume|CoverLetter)\.(?:pdf|docx|json))$")


def is_document(file_name: str) -> bool:
    return bool(DOCUMENT_RE.match(file_name))


def verdict_path(folder: Path, file_name: str) -> Path:
    return folder / f".{file_name}.verdict.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_verdict(folder: Path, file_name: str, sha256: str, passed: bool, issues: list[str]) -> None:
    """Write the verdict for the file as it had the given hash when it was judged. A file that differs now simply does not match."""
    body = {
        "file": file_name,
        "sha256": sha256,
        "passed": bool(passed),
        "issues": list(issues),
        "gateVersion": GATE_VERSION,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    write_text_atomic(verdict_path(folder, file_name), json.dumps(body, indent=2), new_file_mode=PRIVATE_FILE_MODE)


def record_verdicts(folder: Path, file_names: list[str], passed: bool, issues: list[str]) -> list[str]:
    """Write a verdict for each of the named files that exists in `folder`; returns the names written."""
    written = []
    for name in file_names:
        file = folder / name
        if not file.is_file():
            continue
        write_verdict(folder, name, file_sha256(file), passed, issues)
        written.append(name)
    return written


def read_verdict(folder: Path, file_name: str) -> dict | None:
    """The verdict for the file as it is now: None when there is none, it is unreadable, or the file changed since."""
    file = folder / file_name
    try:
        body = json.loads(verdict_path(folder, file_name).read_text(encoding="utf-8"))
        if body.get("file") == file_name and body.get("sha256") == file_sha256(file):
            return body
    except (OSError, ValueError, AttributeError):
        pass
    return None


def status(folder: Path, file_name: str) -> str:
    """'verified', 'failed' (the gate refused it), 'changed' (the file differs from what was judged), 'old_gate' or 'missing'."""
    try:
        body = json.loads(verdict_path(folder, file_name).read_text(encoding="utf-8"))
        current = file_sha256(folder / file_name)
    except (OSError, ValueError):
        return "missing"
    if not isinstance(body, dict) or body.get("file") != file_name or body.get("sha256") != current:
        return "changed"
    if not isinstance(body.get("gateVersion"), int) or body["gateVersion"] < GATE_VERSION:
        return "old_gate"
    return "verified" if body.get("passed") is True else "failed"
