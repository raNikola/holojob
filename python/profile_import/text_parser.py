"""Deterministic parser for pasted CV text.

Turns plain text into an import draft: the existing profile fields plus what was
found but could not be placed. Nothing is invented and nothing is dropped: a line
that fits no field goes to `unplaced`, and the full text is always kept in `rawText`.

Contact details (e-mail, phone, links) are moved into their own fields and removed
from every free-text field, so a bullet or an unplaced block never carries them.
Headings and field labels come from the vocabulary in `src/data/sectionHeadings.json` (see `vocabulary.py`),
so a new language is a data change there; role words are in `role_words.json`.

Every regular expression runs on one line or one token of bounded length, so a
hostile input of a single huge line cannot make the parse quadratic.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from cv_analysis.redact import EMAIL_RE, PHONE_RE, SCHEME_URL_RE, SOCIAL_RE
from cv_analysis.redact import _is_phone as _looks_like_phone_number

MAX_TEXT_BYTES = 200 * 1024
MAX_LINE_CHARS = 2000
MAX_TOKEN_CHARS = 2048
MAX_ENTRIES = 60
MAX_SKILLS = 80
MAX_LINKS = 30

from profile_import.vocabulary import (  # noqa: E402
    CONTACT_LABELS as _CONTACT_LABELS,
    LEVEL_OF as _LEVEL_OF,
    SECTION_OF as _SECTION_OF,
    UNPLACED_HEADERS as _UNPLACED_HEADERS,
    ends_with_label,
    labeled_field,
    normalize_phrase as _norm_phrase,
)

_ROLE_WORDS = set(json.loads(Path(__file__).with_name("role_words.json").read_text(encoding="utf-8"))["roleWords"])
_EDU = json.loads(Path(__file__).with_name("education_words.json").read_text(encoding="utf-8"))
_DEGREE_WORDS = set(_EDU["degreeWords"])
_INSTITUTION_WORDS = set(_EDU["institutionWords"])
_CERT_WORDS = set(_EDU["certificateWords"])
_REMOTE_WORDS = set(_EDU["remoteWords"])

SOURCES = ("paste", "resume_pdf", "linkedin_pdf")
# Section headings only a LinkedIn profile PDF uses; they are a mode of the one parser, not a second parser.
_LINKEDIN_SECTIONS = {"top skills": "skills"}
_PAGE_FOOTER = re.compile(r"^page\s+\d+\s+of\s+\d+$", re.I)


class TextImportError(Exception):
    """A refusal with a fixed code; the message never carries the text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‍⁠﻿]")
_BULLET = re.compile(r"^(?:[•●▪◦‣∙·*]|[-–—](?=\s)|\d{1,2}[.)](?=\s))\s*")
_DECORATION = re.compile(r"^[^\w]*$")
_TRAILING = ".,;:!?)]}>\"'"
_SEPARATORS = r"[|•·;]"

_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_YEAR = r"(?:19|20)\d{2}"
_DATE = rf"(?:{_MONTH}\s+{_YEAR}|\d{{1,2}}[/.]{_YEAR}|{_YEAR})"
_PRESENT = r"(?:present|current|now|today|ongoing)"
_RANGE = re.compile(rf"(?<![\w/])({_DATE})\s*(?:-|–|—|to|until|till)\s*({_DATE}|{_PRESENT})(?!\w)", re.I)
# A host without a scheme counts as a link only when it is written in lowercase and its last label is
# not a language or framework suffix, so "Node.js/React" and "ASP.NET/C#" in a skills line stay text.
_BARE_LINK_RE = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.([a-z]{2,})/\S*")
_NOT_A_TLD = {"js", "ts", "py", "rb", "rs", "go", "cs", "sh", "md", "ex"}
_THOUSANDS = re.compile(r"\d{1,3}(?:[ .,]\d{3}){2,}")
_PLACE = re.compile(r"^(?:[^\W\d_]|[.'’\- ]){2,31}(?:,\s*(?:[^\W\d_]|[.'’\- ]){2,31}){1,2}$")
_DOMAIN = re.compile(r"^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.([a-z]{2,10})$")
_YEARS_STATED = (
    re.compile(r"\b(\d{1,2})\s*\+\s*(?:years?|yrs?)\b", re.I),
    re.compile(r"\b(?:over|more than)\s+(\d{1,2})\s*(?:years?|yrs?)\b", re.I),
    re.compile(r"\b(\d{1,2})\s*(?:years?|yrs?)\s+of(?:\s+[a-z-]+){0,2}\s+(?:experience|expertise)\b", re.I),
)
_GROUP_LINE = re.compile(r"^([^\W\d_][\w &/+.#-]{1,40}):\s*(.+)$")
_DURATION = re.compile(r"\(?\s*\b\d+\s*(?:years?|yrs?)\b(?:\s+\d+\s*(?:months?|mos?)\b)?\s*\)?|\(?\s*\b\d+\s*(?:months?|mos?)\b\s*\)?", re.I)
_LANGUAGE = re.compile(r"^([^\W\d_]+(?: [^\W\d_]+)?)\s*(?:\(([^)]*)\)|[:\-–—]\s*(.+))?$")


def clean_text(text: object) -> str:
    """Validated, normalised text: UTF-8 without BOM or control characters, LF line ends."""
    if not isinstance(text, str):
        raise TextImportError("invalid_request")
    data = text.encode("utf-8", "replace")
    if len(data) > MAX_TEXT_BYTES:
        raise TextImportError("too_large")
    out = data.decode("utf-8")
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n").replace(" ", "\n")
    out = out.replace("\xa0", " ").replace("\t", " ")
    out = _CONTROL.sub("", out).strip()
    if not out:
        raise TextImportError("empty")
    return out


def _scrub_token(token: str, found: dict[str, list[str]]) -> str:
    if "@" in token:
        found["emails"].extend(m.group(0).rstrip(_TRAILING) for m in EMAIL_RE.finditer(token))
        token = EMAIL_RE.sub("", token)
    if "." in token or "://" in token:
        for pattern in (SCHEME_URL_RE, SOCIAL_RE):
            found["links"].extend(m.group(0).rstrip(_TRAILING) for m in pattern.finditer(token))
            token = pattern.sub("", token)
        for match in list(_BARE_LINK_RE.finditer(token)):
            if match.group(1) not in _NOT_A_TLD:
                found["links"].append(match.group(0).rstrip(_TRAILING))
                token = token.replace(match.group(0), "", 1)
    return token


def _tidy(text: str) -> str:
    text = re.sub(rf"(?:\s*(?:{_SEPARATORS}|,)\s*){{2,}}", " | ", text)
    text = re.sub(rf"^[\s|•·;,:–—-]+|[\s|•·;,:–—(\[-]+$", "", text)
    return " ".join(text.split())


def _tidy_keeping_bullet(text: str) -> str:
    marker = _BULLET.match(text)
    prefix = text[: marker.end()] if marker else ""
    return prefix + _tidy(text[len(prefix):])


def _scrub_line(line: str, found: dict[str, list[str]]) -> tuple[str, bool]:
    """The line without e-mail addresses and links, and whether anything was removed."""
    changed = False
    parts = []
    for part in re.split(r"(\s+)", line):
        if part and not part.isspace() and len(part) <= MAX_TOKEN_CHARS:
            cleaned = _scrub_token(part, found)
            changed = changed or cleaned != part
            part = cleaned
        parts.append(part)
    text = "".join(parts)
    return (_tidy_keeping_bullet(text) if changed else text), changed


def _labelled(line: str, start: int) -> bool:
    """True when a phone label ("Phone:", "Telefon", "Tel") ends right before `start`."""
    return ends_with_label(line[:start], "phone")


def _plausible_phone(value: str) -> bool:
    if not _looks_like_phone_number(value) or re.search(r"\b\d{1,2}[/.]\d{4}\b", value):
        return False
    return len(re.sub(r"\D", "", value)) <= 15


def _phone_spans(line: str) -> list[tuple[str, tuple[int, int]]]:
    if len(line) > MAX_LINE_CHARS:
        return []
    return [(m.group(0).strip(), m.span()) for m in PHONE_RE.finditer(line) if _plausible_phone(m.group(0))]


def _header(line: str) -> tuple[str, str, str] | None:
    """(kind, key or label, text after a colon) when the line is a heading."""
    if len(line) > 60 or _BULLET.match(line):
        return None
    mark = r"^[#*_>=\s]+|[*_=\s]+$"
    head, colon, rest = line.partition(":")
    for candidate, inline in ((head, rest.strip()), (line, "")) if colon else ((line, ""),):
        stripped = re.sub(mark, "", candidate).rstrip(":").strip()
        phrase = _norm_phrase(stripped)
        if len(phrase) > 40 or not phrase:
            continue
        if phrase in _SECTION_OF:
            return "section", _SECTION_OF[phrase], inline
        if phrase in _UNPLACED_HEADERS:
            return "unplaced", stripped, inline
    return None


def _has_role_word(text: str) -> bool:
    return any(word in _ROLE_WORDS for word in re.findall(r"[a-z]+", text.lower()))


def _is_place(text: str) -> bool:
    """"City, Country" (letters of any script, 2-3 comma parts) or a word like "Remote"."""
    text = text.strip()
    if not text or len(text) > 80 or _has_role_word(text):
        return False
    if text.lower().strip("() ") in _REMOTE_WORDS:
        return True
    return text[0].isupper() and bool(_PLACE.match(text))


def _name_words(text: str, low: int, high: int) -> bool:
    """True for low..high words, each alphabetic and capitalised (so all-caps and Title Case both pass)."""
    words = text.split()
    if not low <= len(words) <= high or len(text) > 50 or _has_role_word(text):
        return False
    if re.search(r"resume|curriculum|vitae|\bcv\b", text, re.I):
        return False
    return all(w[0].isupper() and all(c.isalpha() or c in "'’.-" for c in w) for w in words)


def _is_name(text: str) -> bool:
    return _name_words(text, 2, 4) and not _is_place(text)


def _is_name_part(text: str) -> bool:
    """One line of a name split over two lines ("FIRSTNAME" / "LASTNAME")."""
    return _name_words(text, 1, 2) and not _is_place(text) and not _header(text) and _norm_phrase(text) not in _CONTACT_LABELS


def _title_case_name(text: str) -> str:
    """An all-caps name written as a name; a name already in mixed case is kept as written."""
    if not text.isupper():
        return text
    return re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), text.lower())


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line, count=1).strip()


def _groups(lines: list[str]) -> list[str]:
    """One string per blank-line separated block; one per line when the section has no blank lines."""
    while lines and not lines[0]:
        lines = lines[1:]
    while lines and not lines[-1]:
        lines = lines[:-1]
    blocks: list[list[str]] = [[]]
    for line in lines:
        if line:
            blocks[-1].append(_strip_bullet(line))
        elif blocks[-1]:
            blocks.append([])
    blocks = [b for b in blocks if b]
    if len(blocks) == 1 and len(blocks[0]) > 1 and "" not in lines:
        return blocks[0]
    return [" — ".join(b) for b in blocks]


def _split_items(text: str) -> list[str]:
    return [p.strip(" .") for p in re.split(r"[,;|•·]", text) if p.strip(" .")]


_LABEL_ONLY = re.compile(r"^([^\W\d_][\w &/+.#-]{1,40}):$")


def _parse_skills(lines: list[str], unplaced: list[dict], confidence: dict) -> tuple[list[str], list[dict]]:
    skills: list[str] = []
    groups: list[dict] = []
    leftovers: list[str] = []
    seen: set[str] = set()

    def add(items: list[str]) -> list[str]:
        kept = []
        for item in items:
            words = item.split()
            if not (1 <= len(words) <= 6 and len(item) <= 60 and re.search(r"\w", item)):
                leftovers.append(item)
                continue
            if item.lower() not in seen:
                seen.add(item.lower())
                skills.append(item)
            kept.append(item)
        return kept

    # A line that ends in a separator continues on the next line ("Product Strategy,\nRoadmapping").
    joined: list[str] = []
    for line in lines:
        text = _strip_bullet(line) if line else ""
        if not text:
            joined.append("")
        elif joined and joined[-1] and joined[-1][-1] in ",;|" and not _LABEL_ONLY.match(joined[-1]):
            joined[-1] = f"{joined[-1]} {text}"
        else:
            joined.append(text)

    label = ""
    label_items: list[str] = []

    def close_label() -> None:
        nonlocal label, label_items
        if label and len(label_items) >= 2:
            groups.append({"label": label, "items": label_items})
        label, label_items = "", []

    for text in joined:
        if not text:
            continue
        only = _LABEL_ONLY.match(text)
        grouped = _GROUP_LINE.match(text)
        if only:  # "Tools:" alone: the lines below are its items
            close_label()
            label = only.group(1).strip()
        elif grouped:
            close_label()
            items = add(_split_items(grouped.group(2)))
            if len(items) >= 2:
                groups.append({"label": grouped.group(1).strip(), "items": items})
        else:
            items = add(_split_items(text))
            if label:
                label_items.extend(items)
    close_label()
    if len(skills) > MAX_SKILLS:
        leftovers.extend(skills[MAX_SKILLS:])
        skills = skills[:MAX_SKILLS]
    if leftovers:
        unplaced.append({"label": "Skills (not split into single skills)", "text": "\n".join(leftovers)})
    confidence["skills"] = "medium" if skills else "low"
    return skills, groups


def _parse_languages(lines: list[str], unplaced: list[dict]) -> list[dict]:
    languages: list[dict] = []
    levels_unmapped: list[str] = []
    rest: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for token in _split_items(_strip_bullet(line)) if line else []:
            match = _LANGUAGE.match(token)
            if not match:
                rest.append(token)
                continue
            name = match.group(1).strip()
            raw_level = (match.group(2) or match.group(3) or "").strip()
            level = _LEVEL_OF.get(_norm_phrase(raw_level), "")
            if raw_level and not level:
                levels_unmapped.append(token)
            if name.lower() not in seen:
                seen.add(name.lower())
                languages.append({"language": name, "proficiency": level})
    if rest:
        unplaced.append({"label": "Languages (not parsed)", "text": "\n".join(rest)})
    if levels_unmapped:
        unplaced.append({"label": "Language levels (not mapped)", "text": "\n".join(levels_unmapped)})
    return languages


def _merge_languages(first: list[dict], second: list[dict]) -> list[dict]:
    seen = {l["language"].lower() for l in first}
    return first + [l for l in second if l["language"].lower() not in seen]


_COMPANY_SUFFIX = {"inc", "llc", "ltd", "gmbh", "corp", "co", "ag", "sa", "bv", "plc", "doo", "srl", "oy", "ab"}
_YEAR_ONLY = re.compile(r"^\W*(?:(?:19|20)\d{2}\W*(?:(?:-|–|—|to)\W*(?:(?:19|20)\d{2}|present|current))?)\W*$", re.I)
_PRESENT_RE = re.compile(rf"^{_PRESENT}$", re.I)


def _place(text: str) -> bool:
    """A place or a work mode, and not a company name with a legal suffix ("Acme, Inc.")."""
    if not _is_place(text):
        return False
    last = text.rsplit(",", 1)[-1].strip(" .").lower()
    return last not in _COMPANY_SUFFIX


def _take_location(text: str) -> tuple[str, str]:
    """(text without a trailing place or work mode, that place), e.g. "Acme, Remote" or "Globex, Belgrade, Serbia"."""
    paren = re.search(r"\(([^()]{2,40})\)\s*$", text)
    if paren and _place(paren.group(1)):
        return text[: paren.start()].strip(" ,|-–—"), paren.group(1).strip()
    parts = [p.strip() for p in text.split(",")]
    if len(parts) >= 2:
        if parts[-1].lower() in _REMOTE_WORDS:
            return ", ".join(parts[:-1]), parts[-1]
        if len(parts) >= 3 and _place(", ".join(parts[-2:])):
            return ", ".join(parts[:-2]), ", ".join(parts[-2:])
    return text, ""


def _heads_before(lines: list[str], index: int, floor: int) -> list[str]:
    heads: list[str] = []
    limit = 2
    j = index - 1
    while j > floor and len(heads) < limit:
        line = lines[j]
        suffix = line.rstrip(" .").rsplit(" ", 1)[-1].lower() in _COMPANY_SUFFIX
        if not line or _BULLET.match(line) or len(line) > 80 or line.endswith(",") or (line.endswith(".") and not suffix) or not (line[0].isupper() or line[0].isdigit()):
            break
        if not heads and _place(line):
            limit = 3  # title, company, then a place line above the dates
        heads.insert(0, line)
        j -= 1
    return heads


def _split_title_company(candidates: list[str], company_first: bool = False) -> tuple[str, str, str]:
    """(title, company, confidence) from one to two header strings.

    `company_first` is the LinkedIn PDF layout (company line, then title line), used when the role
    words do not tell the two apart ("Northwind Software" / "Head of Product")."""
    if len(candidates) >= 2:
        first, second = candidates[0], candidates[1]
        if _has_role_word(second) and not _has_role_word(first):
            return second, first, "medium"
        if company_first and (_has_role_word(first) == _has_role_word(second)):
            return second, first, "medium" if _has_role_word(second) else "low"
        return first, second, "medium" if _has_role_word(first) else "low"
    text = candidates[0] if candidates else ""
    for sep in (" at ", " @ ", " — ", " – ", " | ", " - "):
        if sep in text:
            left, right = (p.strip() for p in text.split(sep, 1))
            if sep not in (" at ", " @ ") and _has_role_word(right) and not _has_role_word(left):
                return right, left, "medium"
            return left, right, "medium" if _has_role_word(left) or sep in (" at ", " @ ") else "low"
    return text, "", "low"


def _sentence(text: str) -> str:
    return text if text[-1] in ".!?" else text + "."


def _derived_line(entry: dict) -> str:
    head = " — ".join(p for p in (entry["title"], entry["company"]) if p)
    period = " – ".join(p for p in (entry["start"], entry["end"]) if p)
    description = " ".join(entry.get("description", "").split())
    text = " ".join(_sentence(t) for t in ([description] if description else []) + entry["bullets"])
    return " | ".join([head, period, text]) if text else " | ".join([head, period])


def _is_date_line(line: str) -> bool:
    """A line that opens an entry: a date range, with at most a short heading beside it."""
    if not line or len(line) > 200 or _BULLET.match(line) or not _RANGE.search(line):
        return False
    rest = _tidy(_DURATION.sub(" ", _RANGE.sub(" ", line, count=1)))
    return len(rest) <= 100 and not rest.endswith(".") and not rest[:1].islower()


def _continues(previous: str, line: str) -> bool:
    """A wrapped line: the line before it has no terminal punctuation and this one does not start a sentence
    (lower case or a digit), or the line before it ran to the full width of the page."""
    if _BULLET.match(line) or previous[-1:] in ".!?:;":
        return False
    return not line[0].isupper() or len(previous) >= 72


def _parse_body(body: list[str]) -> tuple[str, str, list[str]]:
    """(location, description, bullets) of the lines under an entry's date line."""
    lines = list(body)
    while lines and not lines[0]:
        lines.pop(0)
    location = ""
    if lines and not _BULLET.match(lines[0]) and _place(lines[0]):
        location = lines.pop(0)
    blocks: list[list[str]] = []
    last: list[str] | None = None
    seen_bullet = False
    for line in lines:
        if not line:
            last = None
            continue
        text = _strip_bullet(line)
        if not text:
            continue
        if _BULLET.match(line):
            blocks.append(["bullet", text])
            seen_bullet = True
            last = blocks[-1]
        elif last is not None and _continues(last[1], text):
            last[1] = f"{last[1]} {text}"
        else:
            blocks.append(["bullet" if seen_bullet else "para", text])
            last = blocks[-1]
    description = "\n".join(t for k, t in blocks if k == "para")
    return location, description, [t for k, t in blocks if k == "bullet"]


def _parse_experience(lines: list[str], unplaced: list[dict], confidence: dict, warnings: list[str], company_first: bool = False) -> tuple[list[dict], list[str]]:
    starts = [i for i, l in enumerate(lines) if _is_date_line(l)]
    if not starts:
        raw = [_strip_bullet(l) for l in lines if l]
        if raw:
            warnings.append("No dated entries were recognised in the experience section; its lines were kept as plain entries.")
        confidence["workExperience"] = "low"
        return [], raw

    heads = []
    for k, i in enumerate(starts):
        heads.append(_heads_before(lines, i, starts[k - 1] if k else -1))
    lead = [l for l in lines[: starts[0] - len(heads[0])] if l]
    if lead:
        unplaced.append({"label": "Experience (before the first dated entry)", "text": "\n".join(lead)})

    entries: list[dict] = []
    for k, i in enumerate(starts):
        match = _RANGE.search(lines[i])
        remainder = _tidy(_DURATION.sub(" ", _RANGE.sub(" ", lines[i], count=1)))
        candidates = heads[k] + ([remainder] if remainder else [])
        location = ""
        places = [c for c in candidates if _place(c) and len(candidates) > 1]
        if places:
            location = places[-1]
            candidates = [c for c in candidates if c is not places[-1]]
        if len(candidates) > 2:
            unplaced.append({"label": "Experience (extra heading lines)", "text": "\n".join(candidates[:-2])})
            candidates = candidates[-2:]
        title, company, level = _split_title_company(candidates, company_first)
        if company and not location:
            company, location = _take_location(company)
        end_index = (starts[k + 1] - len(heads[k + 1])) if k + 1 < len(starts) else len(lines)
        body_location, description, bullets = _parse_body(lines[i + 1 : end_index])
        entry = {
            "title": title, "company": company, "location": location or body_location,
            "start": match.group(1).strip(), "end": match.group(2).strip(),
            "description": description, "bullets": bullets,
        }
        confidence[f"experienceDetail.{len(entries)}"] = level if title else "low"
        entries.append(entry)

    if len(entries) > MAX_ENTRIES:
        extra = entries[MAX_ENTRIES:]
        entries = entries[:MAX_ENTRIES]
        unplaced.append({"label": f"Experience (beyond {MAX_ENTRIES} entries)", "text": "\n".join(_derived_line(e) for e in extra)})
    confidence["workExperience"] = "medium"
    return entries, [_derived_line(e) for e in entries]


def _kind(text: str) -> str:
    """cert, degree, institution, year or other, from the vocabulary in education_words.json."""
    if _YEAR_ONLY.match(text):
        return "year"
    words = set(re.findall(r"[^\W_]+(?:-[^\W_]+)*", text.replace(".", "").lower()))
    if words & _CERT_WORDS:
        return "cert"
    if words & _DEGREE_WORDS:
        return "degree"
    if words & _INSTITUTION_WORDS:
        return "institution"
    return "other"


def _education_items(lines: list[str], mode: str) -> tuple[list[str], list[str], list[str]]:
    """(education, certifications, left over) from the lines of an education and / or certifications section.

    A line that only adds to the one above it (the institution of a degree, the issuer and year of a
    certificate) is joined to it. In `both` mode a line that is neither is left over; in the single
    modes every line is kept in that section."""
    items: list[dict] = []
    left: list[str] = []
    gap = False
    for line in lines:
        if not line:
            gap = True
            continue
        text = _strip_bullet(line)
        kind = _kind(text)
        previous = items[-1] if items else None
        open_item = previous is not None and not gap and not previous["done"]
        gap = False
        if open_item and (kind in ("institution", "year") or (kind == "other" and previous["kind"] in ("degree", "cert") and len(text.split()) <= 8)):
            previous["text"] += " — " + text
            previous["done"] = previous["kind"] == "degree" and kind != "other" or kind == "year" or previous["kind"] == "cert"
            continue
        if mode == "both" and kind in ("other", "year"):
            left.append(text)
            continue
        target = {"degree": "education", "institution": "education", "cert": "cert"}.get(kind)
        if mode == "certifications":
            target = "cert"
        elif mode == "education" or target is None:
            target = "education"
        done = bool(re.search(r"(?:19|20)\d{2}", text)) if target == "cert" else bool(set(re.findall(r"[^\W_]+", text.lower())) & _INSTITUTION_WORDS)
        items.append({"text": text, "kind": kind, "target": target, "done": done})
    return (
        [i["text"] for i in items if i["target"] == "education"],
        [i["text"] for i in items if i["target"] == "cert"],
        left,
    )


def _years_stated(texts: list[str]) -> int:
    """The largest "10+ years", "over 10 years" or "12 years of experience" in the given lines, else 0."""
    best = 0
    for text in texts:
        if len(text) > MAX_LINE_CHARS:
            continue
        for pattern in _YEARS_STATED:
            for found in pattern.finditer(text):
                value = int(found.group(1))
                if 1 <= value <= 60:
                    best = max(best, value)
    return best


def _earliest_year(entries: list[dict]) -> int:
    years = [int(y.group(0)) for e in entries for y in [re.search(r"(?:19|20)\d{2}", e["start"])] if y]
    return min(years) if years else 0


def _latest_entry(entries: list[dict]) -> dict | None:
    """The current job, else the one that ended last, else the first listed."""
    for e in entries:
        if _PRESENT_RE.match(e["end"]):
            return e
    ended = [(int(y.group(0)), e) for e in entries for y in [re.search(r"(?:19|20)\d{2}", e["end"])] if y]
    return max(ended, key=lambda p: p[0])[1] if ended else (entries[0] if entries else None)


def _scrub_domains(line: str, found: dict[str, list[str]]) -> str:
    """Bare domains ("janesample.dev") in a contact area are links. Used only on the header and on
    contact / links sections, so "Monday.com" in a skills list stays a skill."""
    if len(line) > MAX_LINE_CHARS:
        return line
    changed = False
    parts = []
    for part in re.split(r"(\s+|[|,;•·]+)", line):
        token = part.strip().rstrip(_TRAILING)
        match = _DOMAIN.match(token) if token and len(token) <= 253 else None
        if match and match.group(1) not in _NOT_A_TLD:
            found["links"].append(token)
            part = ""
            changed = True
        parts.append(part)
    return _tidy_keeping_bullet("".join(parts)) if changed else line


def parse_text(text: object, source: str = "paste", today: date | None = None) -> dict:
    """The import draft for CV text. Raises TextImportError with a fixed code.

    `source` is "paste", "resume_pdf" or "linkedin_pdf": the same parser reads all three; the LinkedIn
    mode only adds the headings and page footers of a LinkedIn profile PDF. `today` dates the
    years-of-experience fallback and is only passed by tests."""
    if source not in SOURCES:
        raise TextImportError("invalid_request")
    raw_text = clean_text(text)
    lines = [l.strip() for l in raw_text.split("\n")]
    ignored: list[dict] = []
    if source == "linkedin_pdf":
        footers = [l for l in lines if _PAGE_FOOTER.match(l)]
        lines = [("" if _PAGE_FOOTER.match(l) else l) for l in lines]
        if footers:
            ignored.append({"name": f"{len(footers)} page footer line(s)", "reason": "Page numbers of the LinkedIn PDF"})
    warnings: list[str] = []
    unplaced: list[dict] = []
    confidence: dict[str, str] = {}
    found: dict[str, list[str]] = {"emails": [], "links": []}

    scrubbed: list[str] = []
    changed_lines: set[int] = set()
    for i, line in enumerate(lines):
        clean, changed = _scrub_line(line, found)
        scrubbed.append(clean)
        if changed:
            changed_lines.add(i)

    nonblank = [i for i, l in enumerate(scrubbed) if l]
    nonblank_rank = {i: n for n, i in enumerate(nonblank)}
    first_heading = next((i for i, l in enumerate(scrubbed) if l and _header(l)), len(scrubbed))
    for i in range(first_heading):
        domainless = _scrub_domains(scrubbed[i], found)
        if domainless != scrubbed[i]:
            scrubbed[i] = domainless
            changed_lines.add(i)
    phone = ""
    phone_values: set[str] = set()
    for i, line in enumerate(scrubbed):
        for value, (start, _) in _phone_spans(line):
            labelled = _labelled(line, start)
            if value.startswith("+") or labelled:
                phone_values.add(value)
            # An unlabelled number is a phone only near the top, in the part before the first heading or on a
            # line that also held an e-mail or link, and never when it is grouped like an amount ("10 000 000").
            top = nonblank_rank.get(i, 99) < 12 and (i < first_heading or i in changed_lines)
            if not phone and (value.startswith("+") or labelled or (top and not _THOUSANDS.fullmatch(value))):
                phone = value
                phone_values.add(value)
    if phone_values:
        for i, line in enumerate(scrubbed):
            if len(line) > MAX_LINE_CHARS:
                continue
            spans = [s for v, s in _phone_spans(line) if v in phone_values]
            if spans:
                for start, end in sorted(spans, reverse=True):
                    line = line[:start] + line[end:]
                scrubbed[i] = _tidy_keeping_bullet(line)
                changed_lines.add(i)

    sections: list[tuple[str, str, list[str]]] = []
    preamble: list[tuple[int, str]] = []
    current: list[str] | None = None
    contact_area = False
    for index, line in enumerate(scrubbed):
        if line and _DECORATION.match(line):
            continue
        marked = _header(line) if line else None
        if marked is None and source == "linkedin_pdf" and line and _norm_phrase(line.rstrip(":")) in _LINKEDIN_SECTIONS:
            marked = ("section", _LINKEDIN_SECTIONS[_norm_phrase(line.rstrip(":"))], "")
        if marked and marked[2] and current is not None and sections and sections[-1][2] is current and sections[-1][0] == marked[0] and sections[-1][1] == marked[1]:
            marked = None  # "Tools: SQL, Jira" inside the skills section is a labelled group, not a new section
        if marked:
            kind, key, inline = marked
            target = next((s for s in sections if s[0] == kind and s[1] == key), None)
            if target is None:
                target = (kind, key, [])
                sections.append(target)
            current = target[2]
            contact_area = kind == "section" and key in ("personal", "links")
            if inline:
                current.append(inline)
            continue
        if current is not None:
            current.append(_scrub_domains(line, found) if contact_area and line else line)
        else:
            preamble.append((index, line))
    # "Personal details" holds the same labelled lines as the top of the document, so it is read the same way.
    for kind, key, lines_in in sections:
        if kind == "section" and key == "personal":
            preamble.extend((-1, l) for l in lines_in)

    basic: dict[str, str] = {}
    name_line = None
    headline = ""
    leftovers: list[str] = []

    def pieces_of(line: str) -> list[str]:
        return [p.strip() for p in re.split(_SEPARATORS, line) if p.strip()]

    skip_next: set[int] = set()
    for position, (index, line) in enumerate(preamble):
        if not line or position in skip_next:
            continue
        was_contact = index in changed_lines
        pieces = pieces_of(line)
        remaining = []
        for piece in pieces:
            labeled = labeled_field(piece)
            if not labeled:
                remaining.append(piece)
                continue
            field, value = labeled
            if field == "fullName" and "fullName" not in basic and re.search(r"[^\W\d_]", value) and len(value) <= 60 and "@" not in value:
                name_line = basic["fullName"] = value
                confidence["fullName"] = "medium"
            elif field in ("address", "location") and value and "location" not in basic:
                basic["location"] = value
                confidence["location"] = "medium"
        pieces = remaining
        if not pieces:
            continue
        if name_line is None and _is_name(pieces[0]):
            name_line = pieces[0]
            basic["fullName"] = _title_case_name(name_line)
            confidence["fullName"] = "medium"
            pieces = pieces[1:]
            if not pieces:
                continue
        elif name_line is None and len(pieces) == 1 and not was_contact and _is_name_part(pieces[0]):
            # "FIRSTNAME" on one line and "LASTNAME" on the next: the first one or two short top lines.
            following = next(((n, pieces_of(l)) for n, (i, l) in enumerate(preamble[position + 1 :], position + 1) if l), None)
            if following and len(following[1]) == 1 and preamble[following[0]][0] not in changed_lines and _is_name_part(following[1][0]):
                name_line = f"{pieces[0]} {following[1][0]}"
                basic["fullName"] = _title_case_name(name_line)
                confidence["fullName"] = "medium"
                skip_next.add(following[0])
                continue
            name_line = ""
        elif name_line is None and not was_contact:
            name_line = ""
        for piece in pieces:
            if _norm_phrase(piece.rstrip(":")) in _CONTACT_LABELS:
                continue
            elif "location" not in basic and _place(piece):
                basic["location"] = piece
                confidence["location"] = "low"
            elif not headline and not was_contact and len(piece) <= 80 and not piece.endswith(".") and len(piece.split()) <= 10:
                headline = piece
            else:
                leftovers.append(piece)
    if leftovers:
        label = "Top of the document" if sections else "Text without headings"
        unplaced.append({"label": label, "text": "\n".join(leftovers)})

    skills: list[str] = []
    groups: list[dict] = []
    languages: list[dict] = []
    entries: list[dict] = []
    summary_lines: list[str] = []
    parsed = {"skills": [], "projects": [], "education": [], "workExperience": [], "certifications": []}
    for kind, key, lines_in in sections:
        body = lines_in
        if kind == "unplaced":
            text_block = "\n".join(l for l in body if l)
            if text_block:
                unplaced.append({"label": key.title() if key.isupper() else key, "text": text_block})
        elif key == "summary":
            text_block = "\n".join(l for l in body if l)
            summary_lines.extend(l for l in body if l)
            if text_block:
                unplaced.append({"label": "Summary", "text": text_block})
        elif key == "experience":
            entries, parsed["workExperience"] = _parse_experience(body, unplaced, confidence, warnings, source == "linkedin_pdf")
        elif key == "personal":
            continue  # read with the top of the document above
        elif key == "skills":
            # "Languages: English (fluent)" inside a skills block is a language line.
            language_lines = []
            skill_lines = []
            for l in body:
                grouped = _GROUP_LINE.match(_strip_bullet(l)) if l else None
                if grouped and _SECTION_OF.get(_norm_phrase(grouped.group(1))) == "languages":
                    language_lines.append(grouped.group(2))
                else:
                    skill_lines.append(l)
            skills, groups = _parse_skills(skill_lines, unplaced, confidence)
            parsed["skills"] = skills
            if language_lines:
                languages = _merge_languages(languages, _parse_languages(language_lines, unplaced))
                confidence["languages"] = "medium"
        elif key == "languages":
            languages = _merge_languages(languages, _parse_languages(body, unplaced))
            confidence["languages"] = "medium" if languages else "low"
        elif key == "links":
            rest = "\n".join(l for l in body if l and _norm_phrase(l.rstrip(":")) not in _CONTACT_LABELS)
            if rest:
                unplaced.append({"label": "Links", "text": rest})
        elif key in ("education", "certifications", "educationCertifications"):
            mode = {"education": "education", "certifications": "certifications"}.get(key, "both")
            education, certifications, left = _education_items(body, mode)
            for field, items in (("education", education), ("certifications", certifications)):
                if len(items) > MAX_ENTRIES:
                    unplaced.append({"label": f"{field.title()} (beyond {MAX_ENTRIES} entries)", "text": "\n".join(items[MAX_ENTRIES:])})
                    items = items[:MAX_ENTRIES]
                parsed[field] = parsed[field] + items
                if items or mode != "both":
                    confidence[field] = "medium" if parsed[field] else "low"
            if left:
                unplaced.append({"label": "Education and certifications (not placed)", "text": "\n".join(left)})
        else:
            items = _groups(body)
            if len(items) > MAX_ENTRIES:
                unplaced.append({"label": f"{key.title()} (beyond {MAX_ENTRIES} entries)", "text": "\n".join(items[MAX_ENTRIES:])})
                items = items[:MAX_ENTRIES]
            parsed[key] = items
            confidence[key] = "medium" if items else "low"

    # Current role: the most recent job, else the headline under the name (which is also kept as a hint).
    latest = _latest_entry(entries)
    if latest and latest["title"]:
        basic["currentRole"] = latest["title"]
        confidence["currentRole"] = confidence.get(f"experienceDetail.{entries.index(latest)}", "low")
    elif headline:
        basic["currentRole"] = headline
        confidence["currentRole"] = "medium" if _has_role_word(headline) else "low"

    # Years of experience: stated in the summary or the top lines, else counted from the earliest start.
    stated = _years_stated(summary_lines + [headline] + [l for _, l in preamble if l])
    if stated:
        basic["experienceYears"] = str(stated)
        confidence["experienceYears"] = "derived"
    elif _earliest_year(entries):
        years = (today or date.today()).year - _earliest_year(entries)
        if years >= 1:
            basic["experienceYears"] = str(years)
            confidence["experienceYears"] = "derived"
            warnings.append(f"Experience (years) was counted from the earliest start date, {_earliest_year(entries)}; no number of years is stated in the text.")

    emails = list(dict.fromkeys(e for e in found["emails"] if e))
    links: list[str] = []
    for value in found["links"]:
        if value and value.lower() not in {l.lower() for l in links}:
            links.append(value)
    if emails:
        basic["email"] = emails[0]
        confidence["email"] = "high"
    if len(emails) > 1:
        warnings.append(f"{len(emails) - 1} more e-mail address(es) were found; they are not in any field and stay in the raw text.")
    if phone:
        basic["phone"] = phone
        confidence["phone"] = "high"
    if links:
        confidence["links"] = "high"
    if len(links) > MAX_LINKS:
        warnings.append(f"{len(links) - MAX_LINKS} more link(s) were found; they stay in the raw text only.")
        links = links[:MAX_LINKS]
    if changed_lines:
        warnings.append("E-mail addresses, phone numbers and links were moved out of the text into their own fields.")
    if not sections:
        warnings.append("No section headings were recognised; only contact details were read. The rest is listed under 'Found but not placed'.")

    if source == "linkedin_pdf" and "linkedin" not in raw_text.lower():
        warnings.append("This does not look like a LinkedIn profile PDF (no LinkedIn address or heading); it was read like any other CV.")

    return {
        "source": source,
        "fileName": "",
        "rawText": raw_text,
        "headline": headline,
        "basicProfile": basic,
        "parsedData": {**parsed, "experienceDetail": entries, "competencyGroups": groups},
        "languages": languages,
        "links": links,
        "confidence": confidence,
        "unplaced": unplaced,
        "ignored": ignored,
        "warnings": warnings,
    }
