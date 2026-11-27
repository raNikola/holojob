"""Round 2 text rules (package 4, owner plan 2026-11-25): what an ad's own text says about language, years, on-site only, visa and
employment type, as labels with a class.

Classes (closed decision): hard drops, soft continues with a label, unknown (no usable text, or no signal) continues with nothing.
Every rule below is SOFT: years, seniority and domain are labels only (owner decision); a visa the candidate lacks is shown, never
removed (`.claude/rules/markets-and-data-source.md`); language, on-site and employment type are judged by scoring, and a phrase match
in free text is too loose to drop an ad on. `TEXT_RULE_CLASSES` is the one place a rule's class is written; HARD is supported by
`role_filter.assess` (drop reason `text_rule:<label>`, never pins dedup) but no rule uses it. To promote a rule, change its class here
and add a test.

Text is folded like titles (lower case, Serbian diacritics folded). Matching is on word boundaries. No model call.
"""

from __future__ import annotations

import re

HARD = "hard"
SOFT = "soft"
UNKNOWN = "unknown"

TEXT_RULE_CLASSES = {
    "language": SOFT,
    "years": SOFT,
    "onsite": SOFT,
    "visa": SOFT,
    "employment": SOFT,
}

# Languages other than English that an ad may require. Serbian and its neighbours are left out: the owner speaks them.
_LANGUAGES = ("german", "french", "dutch", "italian", "spanish", "polish", "portuguese", "swedish", "norwegian", "danish", "finnish",
              "czech", "hungarian", "romanian", "greek", "turkish", "russian", "arabic", "chinese", "japanese")
_LEVEL = r"(?:fluent|fluency|native|proficien\w+|business[- ]level|advanced|c1|c2|mother tongue)"
_LANGUAGE = re.compile(
    rf"\b(?:{_LEVEL}\s+(?:in\s+|level\s+of\s+)?(?P<a>{'|'.join(_LANGUAGES)})|(?P<b>{'|'.join(_LANGUAGES)})\s*\(?\s*{_LEVEL})\b")
_YEARS = re.compile(r"\b(\d{1,2})\s*(?:\+|-\s*\d{1,2})?\s*\+?\s*(?:years|yrs|godina|godine)\b")
_YEARS_NEAR = re.compile(r"experience|iskustv|minimum|at least|min\.")
_ONSITE = re.compile(r"\b(?:on-?site only|onsite only|fully on-?site|100% on-?site|no remote|not remote|office[- ]based only|"
                     r"must work from the office|remote work is not possible|rad iskljucivo iz kancelarije)\b")
_REMOTE_SIGNAL = re.compile(r"\b(?:remote-?friendly|fully remote|100% remote|hybrid|work from home|remote or|or remote|remote option|"
                            r"rad od kuce)\b")
_VISA_NO = re.compile(r"\b(?:no visa sponsorship|unable to sponsor|cannot sponsor|can ?not provide (?:visa )?sponsorship|"
                      r"without (?:the need for )?sponsorship|must (?:already )?have (?:the )?(?:legal )?right to work|"
                      r"work permit (?:is )?required|eligible to work in)\b")
_VISA_YES = re.compile(r"\b(?:visa sponsorship (?:is )?(?:available|provided|offered)|we sponsor visas?|relocation (?:support|package|assistance)|"
                       r"we (?:will )?sponsor)\b")
_EMPLOYMENT = (
    ("internship", re.compile(r"\b(?:internship|intern position|praksa|pripravnicki staz)\b")),
    ("part_time", re.compile(r"\b(?:part-?time|skraceno radno vreme)\b")),
    ("contract", re.compile(r"\b(?:fixed[- ]term|contractor|freelance|contract position|contract role|b2b contract|ugovor o delu)\b")),
    ("full_time", re.compile(r"\b(?:full-?time|puno radno vreme)\b")),
)


FOLD = str.maketrans({"š": "s", "ž": "z", "č": "c", "ć": "c", "đ": "d"})


def fold(text) -> str:
    """Lower case with the Serbian diacritics folded: the text `evaluate` expects. The one definition (`role_filter._fold` uses it)."""
    return (text or "").lower().translate(FOLD)


def evaluate(folded_text: str) -> list[tuple[str, str, str]]:
    """(rule, class, label) for every text rule that fires on already-folded ad text. An empty list is "unknown": no signal."""
    text = folded_text or ""
    if not text.strip():
        return []
    out: list[tuple[str, str, str]] = []

    languages = sorted({m.group("a") or m.group("b") for m in _LANGUAGE.finditer(text)})
    out += [("language", TEXT_RULE_CLASSES["language"], f"language:{lang}") for lang in languages]

    years = [int(m.group(1)) for m in _YEARS.finditer(text)
             if _YEARS_NEAR.search(text[max(0, m.start() - 60): m.end() + 60]) and 1 <= int(m.group(1)) <= 30]
    if years:
        out.append(("years", TEXT_RULE_CLASSES["years"], f"years:{max(years)}"))

    # An on-site-only phrase next to a remote or hybrid signal is a mixed ad: unknown, no label.
    if _ONSITE.search(text) and not _REMOTE_SIGNAL.search(text):
        out.append(("onsite", TEXT_RULE_CLASSES["onsite"], "onsite:only"))

    if _VISA_NO.search(text):
        out.append(("visa", TEXT_RULE_CLASSES["visa"], "visa:no_sponsorship"))
    elif _VISA_YES.search(text):
        out.append(("visa", TEXT_RULE_CLASSES["visa"], "visa:sponsorship"))

    types = [name for name, pattern in _EMPLOYMENT if pattern.search(text)]
    out += [("employment", TEXT_RULE_CLASSES["employment"], f"employment:{name}") for name in types]
    return out
