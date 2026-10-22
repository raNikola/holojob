"""Text helpers for job scoring."""

from __future__ import annotations

import html
import re
import unicodedata

TOKEN_RE = re.compile(r"[a-z0-9+#.]+", re.I)
TERM_TOKEN_RE = re.compile(r"[a-z0-9+#]+")
TERM_STOPWORDS = frozenset(
    {"and", "or", "of", "the", "to", "for", "in", "with", "a", "an"}
)

# Letters that carry no combining mark, so NFKD leaves them untouched.
_FOLD_MAP = str.maketrans({
    "đ": "d", "Đ": "D",
    "ø": "o", "Ø": "O",
    "ł": "l", "Ł": "L",
    "ß": "ss",
})

def fold_accents(text: str) -> str:
    """Strip diacritics so "Nis" and "Nis" compare equal.

    Job boards spell Serbian place and company names both ways. A location
    that fails to match raises nothing -- it just scores as a mismatch --
    so folding is applied to every comparison rather than case by case.
    """
    decomposed = unicodedata.normalize("NFKD", text.translate(_FOLD_MAP))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

def normalize_text(text: str) -> str:
    if not text:
        return ""
    unescaped = html.unescape(text)
    no_tags = re.sub(r"<[^>]+>", " ", unescaped)
    collapsed = re.sub(r"\s+", " ", no_tags).strip().lower()
    return fold_accents(collapsed)


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in TOKEN_RE.findall(normalize_text(text)) if len(t) > 1}


def contains_any(haystack: str, needles: list[str]) -> bool:
    h = normalize_text(haystack)
    return any(n and normalize_text(n) in h for n in needles)

def singularize(token: str) -> str:
    """Enough stemming to let "stakeholders" match "stakeholder"."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es") and not token.endswith("ses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def term_tokens(text: str) -> set[str]:
    """Tokens used for keyword and corpus comparison."""
    return {
        singularize(token)
        for token in TERM_TOKEN_RE.findall(normalize_text(text))
        if len(token) > 1 and token not in TERM_STOPWORDS
    }
