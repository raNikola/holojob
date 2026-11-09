"""Plain text from a Markdown (or plain text) file, for the CV text parser (Wave 7, S2).

Deterministic and dependency free. It removes the markup that would otherwise sit in front of headings, dates and bullets
(`## Experience`, `**Acme**`, `[site](https://...)`, table pipes, code fences) and keeps every word. List markers stay as they are:
the parser already reads `-`, `*` and `1.` as bullets. A plain text file passes through unchanged, so one source (`text_file`) covers
.txt, .md and .markdown. Nothing is fetched or executed; a link is kept as its label and its address.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*(```|~~~)")
_ATX = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s{0,3}(?:[-*_]\s*){3,}$")
_SETEXT = re.compile(r"^\s{0,3}(?:={2,}|-{2,})\s*$")
_QUOTE = re.compile(r"^\s{0,3}>\s?")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{0,}:?\s*$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(\s*<?([^)\s>]+)>?[^)]*\)")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>")
_HTML = re.compile(r"</?[A-Za-z][^>]*>|<!--.*?-->")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC_STAR = re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])")
_ITALIC_UNDER = re.compile(r"(?<![_\w])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![_\w])")
_CODE = re.compile(r"`+([^`]+)`+")
_STRIKE = re.compile(r"~~(.+?)~~")
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
_PLUS_BULLET = re.compile(r"^(\s*)\+\s+")


def _inline(line: str) -> str:
    line = _IMAGE.sub(lambda m: m.group(1), line)
    line = _LINK.sub(lambda m: m.group(1) if m.group(1) == m.group(2) else f"{m.group(1)} {m.group(2)}", line)
    line = _AUTOLINK.sub(lambda m: m.group(1), line)
    line = _HTML.sub("", line)
    line = _CODE.sub(r"\1", line)
    line = _BOLD.sub(r"\2", line)
    line = _STRIKE.sub(r"\1", line)
    line = _ITALIC_STAR.sub(r"\1", line)
    line = _ITALIC_UNDER.sub(r"\1", line)
    return _ESCAPE.sub(r"\1", line)


def to_plain(text: object) -> object:
    """The text without Markdown markup. A value that is not a string is returned as it is (the parser refuses it)."""
    if not isinstance(text, str):
        return text
    out: list[str] = []
    in_fence = False
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, raw in enumerate(lines):
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(raw)
            continue
        if _RULE.match(raw) or (_SETEXT.match(raw) and i > 0 and lines[i - 1].strip()):
            continue  # a horizontal rule, or the underline of a Setext heading (the heading text above it stays)
        heading = _ATX.match(raw)
        if heading:
            out.append(_inline(heading.group(1)))
            continue
        line = _QUOTE.sub("", raw)
        if _TABLE_SEPARATOR.match(line):
            continue
        if _TABLE_ROW.match(line):
            cells = [_inline(c.strip()) for c in line.strip().strip("|").split("|")]
            out.append(" | ".join(c for c in cells if c))
            continue
        out.append(_PLUS_BULLET.sub(r"\1- ", _inline(line)))
    return "\n".join(out)
