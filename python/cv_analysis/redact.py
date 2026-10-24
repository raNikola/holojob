"""Strip what identifies the candidate from CV text before it leaves the server.

The analysis needs the CV's content, not who wrote it or how to reach them:
the name, e-mail addresses, phone numbers and links are replaced with
placeholders. What this returns is exactly what the provider receives; the
confirmation dialog shows it as it is.
"""

from __future__ import annotations

import re
import unicodedata

_FOLD_MAP = str.maketrans({"đ": "dj", "Đ": "Dj", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L"})

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SCHEME_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
# A domain followed by a path, or a profile on a well-known site. A bare
# "Monday.com" or "Node.js" is a tool name and is left alone.
PATH_URL_RE = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/\S*", re.I)
SOCIAL_RE = re.compile(r"\b(?:linkedin|github|gitlab|bitbucket|behance|dribbble|twitter|x)\.com\b/?\S*", re.I)
PHONE_RE = re.compile(r"\+?\(?\d[\d\s().\-/]{6,}\d")


def _fold_char(ch: str) -> str:
    decomposed = unicodedata.normalize("NFKD", ch.translate(_FOLD_MAP))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _folded_with_map(text: str) -> tuple[str, list[int]]:
    """Folded, lower-cased text plus, for each folded char, its index in `text`."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        folded = _fold_char(ch)
        out.append(folded)
        index.extend([i] * len(folded))
    return "".join(out), index


def _replace_spans(text: str, spans: list[tuple[int, int]], placeholder: str) -> str:
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + placeholder + text[end:]
    return text


def _is_phone(match: str) -> bool:
    digits = re.sub(r"\D", "", match)
    if len(digits) < 8:
        return False
    # "2019 - 2024" and "2019-2024-2026" are date ranges, not numbers.
    return not re.fullmatch(r"(?:(?:19|20)\d{2}\D*){2,}", match.strip())


def _name_spans(text: str, names: list[str]) -> list[tuple[int, int]]:
    folded, index = _folded_with_map(text)
    words = {w for n in names for w in re.findall(r"\w+", _folded_with_map(n)[0]) if len(w) >= 3}
    spans = []
    for word in sorted(words, key=len, reverse=True):
        for m in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", folded):
            spans.append((index[m.start()], index[m.end() - 1] + 1))
    return spans


def redact_cv_text(text: str, full_name: str = "", links: list[str] | None = None) -> tuple[str, dict]:
    """(redacted text, how many of each kind were removed)."""
    removed = {"names": 0, "emails": 0, "phones": 0, "links": 0}
    out = text or ""

    def sub(pattern: re.Pattern, placeholder: str, key: str, accept=lambda s: True) -> None:
        nonlocal out
        spans = [m.span() for m in pattern.finditer(out) if accept(m.group(0))]
        removed[key] += len(spans)
        out = _replace_spans(out, spans, placeholder)

    sub(EMAIL_RE, "[EMAIL]", "emails")
    # Links the profile itself lists go first, so a bare host such as a personal
    # site is caught too; then the general patterns.
    for link in sorted({(l or "").strip() for l in (links or []) if (l or "").strip()}, key=len, reverse=True):
        bare = re.sub(r"^https?://", "", link, flags=re.I).rstrip("/")
        pattern = re.compile(rf"(?:https?://)?{re.escape(bare)}/?\S*", re.I)
        sub(pattern, "[LINK]", "links")
    sub(SCHEME_URL_RE, "[LINK]", "links")
    sub(SOCIAL_RE, "[LINK]", "links")
    sub(PATH_URL_RE, "[LINK]", "links")
    sub(PHONE_RE, "[PHONE]", "phones", accept=_is_phone)

    spans = _name_spans(out, [full_name] if full_name else [])
    removed["names"] = len(spans)
    out = _replace_spans(out, spans, "[NAME]")
    return out, removed
