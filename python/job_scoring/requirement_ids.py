"""Give each requirement the model extracted a competency id, in code.

ENGINE_CONTRACT.md section 2, step 2. A requirement that names exactly one
term of the skills dictionary (src/data/skillsDictionary.js, shared with the
UI) gets that term's canonical id. Anything else -- no term, or several, as in
"React and Node.js" -- gets a provisional id derived from its own text, so the
same requirement gets the same id on every run and every ad. A provisional
requirement is scored like any other; only the user promotes it later.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from text_utils import fold_accents

DICTIONARY_FILE = Path(__file__).resolve().parents[2] / "src" / "data" / "skillsDictionary.js"

PROVISIONAL_PREFIX = "prov:"

# A requirement of these kinds that names a skill is about that skill ("5+
# years of Python"). A certification, a degree or a spoken language that
# mentions one is a different competency ("AWS Certified Solutions Architect"
# is not AWS), so they always stay provisional.
MAPPED_KINDS = {"skill", "experience", "domain"}

# Terms that are also ordinary English words ("go the extra mile", "express
# ideas clearly") match only as the dictionary spells them.
CASE_SENSITIVE_TERMS = {"Go", "Express", "Swift", "Spark", "Rust", "Ruby", "Flutter"}

_TERM_RE = re.compile(r"'((?:[^'\\]|\\.)*)'")
# What may not touch a term on either side for it to count as a whole term.
_EDGE = r"a-z0-9+#"


def load_dictionary(path: Path = DICTIONARY_FILE) -> list[str]:
    """The terms of the shared skills dictionary, in file order."""
    return [m.group(1).replace("\\'", "'") for m in _TERM_RE.finditer(path.read_text(encoding="utf-8"))]


def canonical_id(term: str) -> str:
    """A dictionary term's id: "C++" is c-plus-plus, "Node.js" is node-js."""
    slug = term.lower().replace("+", "-plus").replace("#", "-sharp")
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def normalize_requirement(text: str) -> str:
    """Lower-cased and whitespace-collapsed: the text a provisional id hashes."""
    return " ".join(str(text or "").split()).lower()


def provisional_id(text: str) -> str:
    digest = hashlib.sha256(normalize_requirement(text).encode("utf-8")).hexdigest()
    return PROVISIONAL_PREFIX + digest[:12]


def _pattern(term: str) -> re.Pattern:
    flags = 0 if term in CASE_SENSITIVE_TERMS else re.IGNORECASE
    body = re.escape(fold_accents(term))
    # An optional plural: "REST APIs" names REST API.
    return re.compile(rf"(?<![{_EDGE}]){body}s?(?![{_EDGE}])", flags)


DICTIONARY = load_dictionary()
_PATTERNS = [(term, _pattern(term)) for term in DICTIONARY]


def dictionary_terms_in(text: str) -> list[str]:
    """The dictionary terms the text names, a shorter one inside a longer dropped.

    "React Native" names React Native, not also React.
    """
    folded = fold_accents(str(text or ""))
    hits = [(m.start(), m.end(), term) for term, pattern in _PATTERNS for m in pattern.finditer(folded)]
    kept = {
        term
        for start, end, term in hits
        if not any(s <= start and end <= e and (e - s) > (end - start) for s, e, _ in hits)
    }
    return sorted(kept)


def assign_id(requirement: dict) -> dict:
    """The requirement with `id` and `provisional` set; the input is not changed."""
    terms = dictionary_terms_in(requirement.get("text")) if requirement.get("kind") in MAPPED_KINDS else []
    if len(terms) == 1:
        return {**requirement, "id": canonical_id(terms[0]), "provisional": False}
    return {**requirement, "id": provisional_id(requirement.get("text")), "provisional": True}
