"""Whether a string is shaped like a keyword or a skill, and not like prose.

The ATS keyword bank holds skills and role names. A sentence, a bullet or a whole paragraph of a CV is not one, and cannot be
matched against an ad: it only inflates what the bank could earn. The same rule is in
src/modules/intelligence/keywordShape.js; tests/fixtures/keyword-shape.json is run by both.
"""

from __future__ import annotations

import re

MAX_WORDS = 6
MAX_CHARS = 48

# Sentence punctuation: a comma or semicolon or colon anywhere, or a full stop / ! / ? that ends a word ("Node.js" and "C++" stay).
_PROSE_PUNCTUATION = re.compile(r"[,;:]|[.!?](\s|$)")
_BULLET_START = re.compile(r"^\s*([-*•●–—]|\d+[.)])\s")


def is_keyword_shaped(value) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > MAX_CHARS or "\n" in text or "\r" in text:
        return False
    if len(text.split()) > MAX_WORDS:
        return False
    return not (_PROSE_PUNCTUATION.search(text) or _BULLET_START.match(text))
