"""The one text normalization quotes are compared under (contract section 5.2)."""

from __future__ import annotations

import unicodedata

from text_utils import fold_accents


def normalize(text: str | None) -> str:
    """NFKC, diacritics folded as text_utils folds them, whitespace collapsed, case folded."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    return " ".join(fold_accents(text).split()).casefold()


def quote_in(quote: str | None, source: str | None) -> bool:
    """True when the quote, normalized, is a non-empty substring of the normalized source."""
    needle = normalize(quote)
    return bool(needle) and needle in normalize(source)
