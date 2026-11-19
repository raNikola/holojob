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


def identity_of(profile: dict | None) -> tuple[str, list[str]]:
    """(full name, links) the profile names as the candidate's own: what
    redact_cv_text needs, besides its patterns, to strip the name and a bare
    personal site. Every caller sending profile-derived text reads them here."""
    profile = profile or {}
    name = str((profile.get("basicProfile") or {}).get("fullName") or "")
    links = (((profile.get("resume") or {}).get("parsedData")) or {}).get("links")
    return name, [str(l).strip() for l in links if str(l or "").strip()] if isinstance(links, list) else []


# Phone shapes an ad's contact line really has. Deliberately narrower than PHONE_RE (the owner-data scan, which stays broad and fail-closed):
# a salary range ("120 000 - 150 000"), years, experience counts, ids and dates are never masked.
_SEP = r"[\s().\-/]"
AD_PHONE_RES = (
    re.compile(r"(?<![\w+])\+\s?\d{1,3}" + _SEP + r"{0,3}\d(?:" + _SEP + r"{0,2}\d){6,13}"),  # +381 11 234 5678, +1 (555) 123-4567
    re.compile(r"(?<![\w+])(?<!\d[\s.\-/])00[1-9]\d{0,2}" + _SEP + r"{0,3}\d(?:" + _SEP + r"{0,2}\d){6,12}"),  # 00381 11 234 5678
    re.compile(r"(?<![\w+])\(\d{2,5}\)[\s.\-]?\d{3,4}(?:[\s.\-]?\d{2,4}){1,2}(?!\d)"),  # (011) 234-5678
    re.compile(r"(?<![\w+])(?<!\d[\s.\-/])0[1-9]\d{0,2}[\s./\-]\d{3}(?:[\s.\-]?\d{2,4}){1,2}(?!\d)"),  # national: 011 234 5678, 064/123-4567 (a trunk 0 first)
    re.compile(r"(?i)\b(?:tel|phone|mobile|mob|call|whatsapp|fax)\b\.?:?\s*(\+?\d[\d\s().\-/]{6,}\d)"),  # a labelled number
)
_DATE_LIKE = re.compile(r"\d{1,2}[./\-]\d{1,2}[./\-](?:19|20)\d{2}|(?:19|20)\d{2}[./\-]\d{1,2}[./\-]\d{1,2}")


def _ad_phone(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    return 8 <= len(digits) <= 15 and not _DATE_LIKE.fullmatch(text.strip())


def mask_ad_contacts(text: str) -> tuple[str, dict]:
    """(text, {"emails": n, "phones": n}): the e-mail addresses and phone numbers an AD carries, replaced by [EMAIL] / [PHONE].

    For public ad text only (a recruiter's contact line); the owner-identifier scan is not loosened and still runs on the result.
    Only real phone shapes are masked (AD_PHONE_RES); numbers in requirements, pay and dates stay as they are."""
    emails = len(EMAIL_RE.findall(text))
    text = EMAIL_RE.sub("[EMAIL]", text)
    phones = 0

    def phone(m):
        nonlocal phones
        number = m.group(1) if m.re.groups else m.group(0)
        if not _ad_phone(number):
            return m.group(0)
        phones += 1
        return m.group(0).replace(number, "[PHONE]") if m.re.groups else "[PHONE]"

    for pattern in AD_PHONE_RES:
        text = pattern.sub(phone, text)
    return text, {"emails": emails, "phones": phones}


def find_leaks(text: str, name: str = "", links: list[str] | None = None) -> list[str]:
    """What of the owner's is still in `text` after redaction; empty when it is clean.

    The final check of every caller that sends redacted text: it fails closed, so a pattern the redaction missed
    stops the call instead of reaching the provider."""
    leaks = []
    if EMAIL_RE.search(text):
        leaks.append("an e-mail address")
    if any(_is_phone(m.group(0)) for m in PHONE_RE.finditer(text)):
        leaks.append("a phone number")
    if name and _name_spans(text, [name]):
        leaks.append("the owner's name")
    for link in links or []:
        bare = re.sub(r"^https?://", "", (link or "").strip(), flags=re.I).rstrip("/").lower()
        if bare and bare in text.lower():
            leaks.append("a profile link")
            break
    return leaks


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
