"""Heading and label vocabulary for CV text, read from src/data/sectionHeadings.json.

The same file feeds the JS extractor (src/utils/headingVocabulary.js). A language
is a block in that file; nothing here names one. Phrases are compared after
folding: lower case, Cyrillic to Latin, diacritics removed, so a Latin entry also
covers its upper-case, unaccented and Cyrillic spellings.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_FILE = Path(__file__).resolve().parents[2] / "src" / "data" / "sectionHeadings.json"
_DATA = json.loads(_FILE.read_text(encoding="utf-8"))
_LANGUAGES = list(_DATA["languages"].values())
_TRANSLIT = {**_DATA["transliteration"]["cyrillicToLatin"], **_DATA["transliteration"]["extra"]}


def fold_text(text: str) -> str:
    """Lower case, Cyrillic to Latin, diacritics removed."""
    out = "".join(_TRANSLIT.get(ch, ch) for ch in str(text or "").lower())
    return "".join(c for c in unicodedata.normalize("NFD", out) if not unicodedata.combining(c))


_CONJUNCTIONS = {fold_text(w) for lang in _LANGUAGES for w in lang["conjunctions"]}


def normalize_phrase(text: str) -> str:
    """The comparison form of a heading or label: folded, brackets and punctuation gone, "&" / "i" / "and" alike."""
    text = re.sub(r"\([^)]*\)", " ", fold_text(text)).replace("&", " and ")
    words = re.sub(r"[^a-z\- ]", " ", text).split()
    return " ".join("and" if w in _CONJUNCTIONS else w for w in words)


def _index(pairs) -> dict[str, str]:
    index: dict[str, str] = {}
    for key, phrases in pairs:
        for phrase in phrases:
            index[normalize_phrase(phrase)] = key
    return index


SECTION_OF = _index(pair for lang in _LANGUAGES for pair in lang["sections"].items())
UNPLACED_HEADERS = {
    normalize_phrase(p) for lang in _LANGUAGES for p in lang["unplacedSections"]
}
LABEL_OF = _index(pair for lang in _LANGUAGES for pair in lang["fieldLabels"].items())
LEVEL_OF = _index(pair for lang in _LANGUAGES for pair in lang["languageLevels"].items())
CONTACT_LABELS = set(LABEL_OF)
_LABELLED_LINE = re.compile(r"^([^:]{2,40}):\s*(.*)$")


def labeled_field(line: str) -> tuple[str, str] | None:
    """(field, value) for a "Label: value" line whose label the vocabulary knows, else None."""
    match = _LABELLED_LINE.match(line.strip())
    if not match:
        return None
    field = LABEL_OF.get(normalize_phrase(match.group(1)))
    return (field, match.group(2).strip()) if field else None


def ends_with_label(prefix: str, field: str) -> bool:
    """True when `prefix` ends with a label for `field` followed by only separators ("Telefon: ", "Tel.")."""
    folded = re.sub(r"[\s:.\-–]+$", "", fold_text(prefix))
    if not folded:
        return False
    return any(
        folded.endswith(label) and not re.search(r"[a-z]$", folded[: -len(label)] or " ")
        for label, kind in LABEL_OF.items()
        if kind == field and label
    )
