"""The text of a generated document, read from the file's own bytes, so it can be checked without regenerating it.

Uses libraries the project already pins (beautifulsoup4, python-docx, pypdf). Returns None when a file cannot be read, which the
caller treats as "could not be checked", never as a pass.
"""

from __future__ import annotations

import io
import json
import re

# A JSON Resume file writes the dates the profile gave in words ("May 2020") as ISO dates ("2020-05"): code-made, not claims.
ISO_DATE_RE = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")


def _json_strings(value):
    if isinstance(value, str):
        if not ISO_DATE_RE.match(value.strip()):
            yield value
    elif isinstance(value, list):
        for v in value:
            yield from _json_strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _json_strings(v)


def _docx_text(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts += [cell.text for cell in row.cells]
    for section in doc.sections:
        parts += [p.text for p in section.header.paragraphs] + [p.text for p in section.footer.paragraphs]
    return "\n".join(parts)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text(file_name: str, data: bytes) -> str | None:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    try:
        if ext == "md":
            return data.decode("utf-8", errors="replace")
        if ext == "html":
            from bs4 import BeautifulSoup

            return BeautifulSoup(data.decode("utf-8", errors="replace"), "html.parser").get_text("\n")
        if ext == "json":
            return "\n".join(_json_strings(json.loads(data.decode("utf-8"))))
        if ext == "docx":
            return _docx_text(data)
        if ext == "pdf":
            return _pdf_text(data)
    except Exception:  # an unreadable file is "could not be checked", whatever the library says
        return None
    return None
