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
    re.compile(r"(?<![\w+])(?<!\d[\s.\-/])1[\s.\-]?\([2-9]\d{2}\)[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),  # 1(555) 123-4567, 1 (555) 123 4567 (before the next one, which would leave the 1)
    re.compile(r"(?<![\w+])\(\d{2,5}\)[\s.\-]?\d{3,4}(?:[\s.\-]?\d{2,4}){1,2}(?!\d)"),  # (011) 234-5678
    re.compile(r"(?<![\w+])(?<!\d[\s.\-/])0[1-9]\d{0,2}[\s./\-]\d{3}(?:[\s.\-]?\d{2,4}){1,2}(?!\d)"),  # national: 011 234 5678, 064/123-4567 (a trunk 0 first)
    re.compile(r"(?i)\b(?:tel|phone|mobile|mob|call|whatsapp|fax)\b\.?:?\s*(\+?\d[\d\s().\-/]{6,}\d)"),  # a labelled number
    # North American: 555-123-4567, 555.123.4567, 1-800-555-1234 (the area code starts 2-9). Real numbers in US ads (an accommodation line); masked, so the ad is kept.
    re.compile(r"(?<![\w+])(?<!\d[\s.\-/])(?:1[\s.\-])?[2-9]\d{2}[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)"),
)
_DATE_LIKE = re.compile(r"\d{1,2}[./\-]\d{1,2}[./\-](?:19|20)\d{2}|(?:19|20)\d{2}[./\-]\d{1,2}[./\-]\d{1,2}")


def _ad_phone(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    return 8 <= len(digits) <= 15 and not _DATE_LIKE.fullmatch(text.strip())


def mask_ad_contacts(text: str) -> tuple[str, dict]:
    """(text, {"emails": n, "phones": n}): the e-mail addresses and phone numbers an AD carries, replaced by [EMAIL] / [PHONE].

    For public ad text only (a recruiter's contact line); the owner-identifier scan is not loosened and still runs on the result.
    Real phone shapes are masked (AD_PHONE_RES, then any run `_phone_in_ad` still reads as a phone); numbers in requirements, pay, dates, versions and ids stay as they are."""
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
    # Whatever else of the ad still reads as a phone (`_phone_in_ad`: a trunk-0 run, separated groups nothing excuses, a number after a phone word) is a
    # third party's: masked, so the ad is sent without it instead of refused. The owner's own number is never "let through" by this: the fill checks the
    # raw ad text for the owner's identifiers first (prelabel.owner_in_text) and refuses an ad that carries one.
    spans = [m.span() for m in _AD_RUN_RE.finditer(text)
             if _phone_in_ad(m.group(0), text[max(0, m.start() - 40): m.start()], text[m.end(): m.end() + 8])]
    phones += len(spans)
    text = _replace_spans(text, spans, "[PHONE]")
    return text, {"emails": emails, "phones": phones}


# --- the phone check of an outgoing prompt that carries an AD (owner_leaks) ---------------------------------------------------------------
# An ad is full of digit runs that are not phones: requisition and job numbers, dates, pay ranges, amounts, ZIP+4. PHONE_RE cannot tell them
# from a phone, so a prompt with one of them was refused (measured 2026-11-21: 20 of 21 plannable Strong ads). `_phone_in_ad` reads each run
# with its shape and the words before it. It is used ONLY for a prompt with ad text (find_leaks(..., ad_text=True)); CV redaction and every
# other caller keep the strict `_is_phone`. The owner's own number is caught separately and unchanged (prelabel.owner_leaks, literal digits).
_AD_RUN_RE = re.compile(r"\+?\(?\d[\d \t ().\-/]{6,}\d")  # PHONE_RE, but never across a line break
# A phone word directly before the run ("Tel:", "call us on", "WhatsApp number -"), not anywhere earlier in the sentence.
_PHONE_WORD_RE = re.compile(
    r"(?i)\b(?:tel|telephone|telefon|phone|mobile|mob|cell|call|whatsapp|viber|fax)\b\.?\W{0,4}(?:(?:us|me)\W{1,3})?(?:(?:no|nr|number|on|at)\b\.?\W{0,4})?$")
_CURRENCY_RE = re.compile(r"(?i)[$€£]|\b(?:eur|usd|rsd|chf|gbp|cad|aud|sek|pln|czk|din)\b")
_DATE_ANY_RE = re.compile(r"\d{1,2}[./\-]\d{1,2}[./\-](?:19|20)\d{2}|(?:19|20)\d{2}[./\-]\d{1,2}[./\-]\d{1,2}")
_RANGE_SPLIT_RE = re.compile(r"\s[-–—]\s")
_AMOUNT_PART_RE = re.compile(r"[1-9][\d .,]*\d|[1-9]")
_THOUSANDS_RE = re.compile(r"[1-9]\d{0,2}(?:[ . ]\d{3})+")


def _phone_in_ad(run: str, before: str, after: str) -> bool:
    """Whether one digit run of an ad reads as a phone number. Ambiguous separated groups count as a phone (fail closed); what is excused is
    listed here: dates, year ranges, amounts (currency, thousands groups, a range of two amounts), ZIP+4, an id of two long groups, and a plain digit
    run (a requisition or job number) unless a phone word stands before it, it starts with + or 00 (11+ digits) or with one trunk 0 (9-11 digits)."""
    s = run.strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 8:
        return False
    if sum(c.isdigit() for c in _DATE_ANY_RE.sub(" ", s)) < 8:
        return False  # dates and ranges of dates
    if not _is_phone(s):
        return False  # a year range
    if _CURRENCY_RE.search(before[-6:]) or _CURRENCY_RE.search(after[:6]):
        return False
    if re.search(r"\d,$", before) or re.match(r",\d", after):
        return False  # a piece of a number grouped with commas ("120,000.00 - 150,000.00"): a phone is never written that way
    if re.fullmatch(r"\d{1,4}(?:\.\d{1,4}){3,}", s):
        return False  # a version or an IP address ("3.14.159.2653"): four or more dotted groups; a dotted phone has three (555.123.4567)
    if _PHONE_WORD_RE.search(before[-30:].rsplit("\n", 1)[-1]):
        return True
    if s.startswith("+") or re.match(r"\(\d{2,5}\)", s):
        return True
    if re.fullmatch(r"\d+", s):
        if s.startswith("00"):
            return len(digits) >= 11
        return s.startswith("0") and 9 <= len(digits) <= 11
    if _THOUSANDS_RE.fullmatch(s) or re.fullmatch(r"\d{5}-\d{4}", s) or re.fullmatch(r"[1-9]\d{3,}-\d{4,}", s):
        return False
    parts = _RANGE_SPLIT_RE.split(s)
    if len(parts) == 2 and all(_AMOUNT_PART_RE.fullmatch(p.strip()) for p in parts):
        return False  # "120 000 - 150 000", "100.00 - 130"
    return True


def _has_phone_in_ad(text: str) -> bool:
    return any(_phone_in_ad(m.group(0), text[max(0, m.start() - 40): m.start()], text[m.end(): m.end() + 8]) for m in _AD_RUN_RE.finditer(text))


def find_leaks(text: str, name: str = "", links: list[str] | None = None, *, ad_text: bool = False) -> list[str]:
    """What of the owner's is still in `text` after redaction; empty when it is clean.

    The final check of every caller that sends redacted text: it fails closed, so a pattern the redaction missed
    stops the call instead of reaching the provider. `ad_text=True` is for a prompt that carries a job ad: its digit runs are read by
    `_phone_in_ad` instead of the strict `_is_phone`."""
    leaks = []
    if EMAIL_RE.search(text):
        leaks.append("an e-mail address")
    if _has_phone_in_ad(text) if ad_text else any(_is_phone(m.group(0)) for m in PHONE_RE.finditer(text)):
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
