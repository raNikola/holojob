"""A normalized company key: one string per employer, whatever spelling a board uses (package 3, owner plan 2026-11-25).

Stored as `companyKey` on ledger entries (`job_history.found_ad`) and on `filtered_ads.json` records when they are written; a row
written before package 3 has none, so a reader takes `key_of(row)`: the stored value, else one computed from the company name
(career-ops `detect-reposts.mjs` `companyKey`, same fallback order). Stdlib only, pure. Nothing reads it for dedup or scoring yet:
`dedupe_jobs._crosspost_key` is unchanged, the repost counter (package 7) is its first user.

Rule (career-ops `invite-match.mjs` `normalizeCompanyName`, with two holojob additions):
1. NFKC, lower case, Serbian Latin diacritics folded ("Nordeus d.o.o." and "NORDEUS DOO" give the same key);
2. text in parentheses removed, "&" read as "and", every character that is not a letter or digit (any script) becomes a space;
3. legal-form suffixes stripped from the end, repeatedly ("acme holdings inc ltd" -> "acme holdings");
4. a trailing country name stripped, as `dedupe_jobs._company_name` does ("Fivetran Serbia" -> "fivetran"; "Bank of Serbia" stays);
5. then one generic descriptor ("group", "technologies", ...) stripped once, never chained, and never down to nothing.
A name that folds to nothing keys on its lowered raw text, so two all-symbol names never share the empty key.
"""

from __future__ import annotations

import importlib.util
import re
import unicodedata
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_company_key_geography", Path(__file__).with_name("geography.py"))
_geography = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_geography)

VERSION = 1

# career-ops tracker-utils.mjs LEGAL_SUFFIXES, verbatim (it already holds the Serbian "doo").
LEGAL_SUFFIXES = (
    "incorporated", "inc", "corporation", "corp", "company", "co",
    "limited", "ltd", "llc", "llp", "lp", "plc", "pc", "apc",
    "gmbh", "ag", "kgaa", "mbh", "ug",
    "sas", "sarl", "eurl", "snc", "scs", "sca", "sa",
    "spa", "srl", "ltda", "saa", "sl", "sll", "slu",
    "bv", "nv", "cv",
    "ab", "as", "oy", "oyj", "kf", "sf", "aps", "se",
    "jsc", "pjsc", "zao", "ooo", "doo", "kft", "rt", "zrt",
    "pty", "pte", "pvt", "sdn", "bhd",
)
# career-ops GENERIC_DESCRIPTORS without "canada" (a country: step 4 handles countries, for every country).
GENERIC_DESCRIPTORS = ("group", "holdings", "technologies", "technology", "solutions", "international")

_FOLD = str.maketrans({"š": "s", "ž": "z", "č": "c", "ć": "c", "đ": "d", "ß": "ss"})
_PARENS = re.compile(r"\([^)]*\)")
_NOT_WORD = re.compile(r"[^\w ]|_")
# "d.o.o." becomes "d o o" in step 2; joined back so the suffix rule sees "doo". Same for "s.r.l.", "a.s." and the like.
_SPLIT_FORM = re.compile(r"(?:^| )((?:[a-z] ){1,3}[a-z])$")


def _letters(name: str) -> str:
    text = unicodedata.normalize("NFKC", str(name or "")).lower().translate(_FOLD)
    text = _PARENS.sub(" ", text).replace("&", " and ")
    return " ".join(_NOT_WORD.sub(" ", text).split())


def company_key(name) -> str:
    """The key of one company name ('' only for an empty name)."""
    raw = " ".join(str(name or "").split())
    key = _letters(raw)
    split = _SPLIT_FORM.search(key)
    if split and split.group(1).replace(" ", "") in LEGAL_SUFFIXES:
        key = key[: split.start(1)] + split.group(1).replace(" ", "")
    changed = True
    while changed:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if key.endswith(" " + suffix):
                key = key[: -len(suffix) - 1].strip()
                changed = True
    words = key.split()
    for size in (2, 1):
        if len(words) > size and _geography.country_of_name(" ".join(words[-size:])):
            rest = words[:-size]
            if rest[-1] not in ("of", "in", "for", "de", "du"):
                words = rest
                break
    if len(words) > 1 and words[-1] in GENERIC_DESCRIPTORS:
        words = words[:-1]
    key = " ".join(words)
    return key or raw.lower()


def key_of(row: dict) -> str:
    """A row's key: the stored `companyKey`, else computed from its company (the ledger's ad snapshot `job.company`, or `company`)."""
    stored = row.get("companyKey")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    company = row.get("company")
    if company is None and isinstance(row.get("job"), dict):
        company = row["job"].get("company")
    return company_key(company)
