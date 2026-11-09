"""Plain text from a DOCX resume, for the CV text parser (Wave 7, S4).

Uses python-docx (already a dependency). The file is never stored, never opened by an office program and nothing in it is executed or fetched:
python-docx's XML parser does not resolve entities, and external relationships are not followed. Before python-docx sees the bytes the
package is checked as a zip (member count, declared sizes), macro-enabled and password-protected / old-format files are refused, and
an image-only document is refused as `no_text` (there is no OCR). Errors carry a fixed code and never the cause, which can quote the file.

Reading order is the document's: header text, then paragraphs and tables as they appear. A list paragraph becomes a "- " bullet, a table
row becomes cells joined by " | ", a hyperlink whose address is not already in its text keeps its address. Text boxes are not read
(the caller is told); footers are skipped (page numbers).
"""

from __future__ import annotations

import io
import warnings
import zipfile

from profile_import.text_parser import TextImportError

MAX_DOCX_BYTES = 10 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 25 * 1024 * 1024
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # an old .doc, or a password-protected .docx (Word wraps those in this container)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def check_package(data: bytes) -> None:
    """Refuse what must not reach python-docx. Raises TextImportError with a fixed code."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise TextImportError("empty")
    if len(data) > MAX_DOCX_BYTES:
        raise TextImportError("too_large")
    if data[:8] == _OLE_MAGIC:
        raise TextImportError("encrypted")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            members = package.infolist()
            if len(members) > MAX_MEMBERS or sum(m.file_size for m in members) > MAX_UNPACKED_BYTES or any(m.file_size > MAX_MEMBER_BYTES for m in members):
                raise TextImportError("corrupt_file")
            names = {m.filename for m in members}
            if "word/document.xml" not in names:
                raise TextImportError("unsupported_type")
            if "word/vbaProject.bin" in names:
                raise TextImportError("unsupported_type")
            if any(m.flag_bits & 0x1 for m in members):
                raise TextImportError("encrypted")
    except zipfile.BadZipFile:
        raise TextImportError("corrupt_file") from None


def _is_list(paragraph) -> bool:
    style = (paragraph.style.name if paragraph.style is not None else "") or ""
    properties = paragraph._p.pPr
    return style.lower().startswith("list") or (properties is not None and properties.numPr is not None)


def _paragraph_text(paragraph) -> str:
    text = paragraph.text.replace("\t", " ").strip()
    try:
        addresses = [h.url for h in paragraph.hyperlinks if h.url]
    except Exception:  # noqa: BLE001 - a malformed link is skipped, never fatal
        addresses = []
    for address in addresses:
        if address and address not in text:
            text = f"{text} {address}".strip()
    if text and _is_list(paragraph):
        text = f"- {text}"
    return text


def _table_lines(table) -> list[str]:
    lines = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            if id(cell._tc) in seen:  # a merged cell is returned once per column it spans
                continue
            seen.add(id(cell._tc))
            value = " ".join(cell.text.split())
            if value:
                cells.append(value)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def docx_to_text(data: bytes) -> tuple[str, list[str]]:
    """(text, warnings) for a DOCX file's bytes. Raises TextImportError with a fixed code."""
    check_package(data)
    warnings_out: list[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            document = Document(io.BytesIO(data))
            lines: list[str] = []
            for section in document.sections:
                for paragraph in section.header.paragraphs:
                    text = paragraph.text.strip()
                    if text and text not in lines:
                        lines.append(text)
            for child in document.element.body.iterchildren():
                if child.tag == f"{_W}p":
                    lines.append(_paragraph_text(Paragraph(child, document)))
                elif child.tag == f"{_W}tbl":
                    lines.extend(_table_lines(Table(child, document)))
            if document.element.body.findall(f".//{_W}txbxContent"):
                warnings_out.append("Text boxes in the file were not read. If something is missing, paste the text instead.")
    except TextImportError:
        raise
    except Exception:  # noqa: BLE001 - python-docx and lxml messages can quote the file
        raise TextImportError("corrupt_file") from None
    text = "\n".join(lines).strip()
    if not text:
        raise TextImportError("no_text")
    return text, warnings_out
