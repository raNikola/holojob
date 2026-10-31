"""Deterministic parser for pasted CV text (English only).

Turns plain text into an import draft: the existing profile fields plus what was
found but could not be placed. Nothing is invented and nothing is dropped: a line
that fits no field goes to `unplaced`, and the full text is always kept in `rawText`.

Contact details (e-mail, phone, links) are moved into their own fields and removed
from every free-text field, so a bullet or an unplaced block never carries them.
Headings are matched against the English vocabulary in `section_headers.json`.

Every regular expression runs on one line or one token of bounded length, so a
hostile input of a single huge line cannot make the parse quadratic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from cv_analysis.redact import EMAIL_RE, PATH_URL_RE, PHONE_RE, SCHEME_URL_RE, SOCIAL_RE
from cv_analysis.redact import _is_phone as _looks_like_phone_number

MAX_TEXT_BYTES = 200 * 1024
MAX_LINE_CHARS = 2000
MAX_TOKEN_CHARS = 2048
MAX_ENTRIES = 60
MAX_SKILLS = 80
MAX_LINKS = 30

_VOCAB = json.loads(Path(__file__).with_name("section_headers.json").read_text(encoding="utf-8"))


class TextImportError(Exception):
    """A refusal with a fixed code; the message never carries the text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _norm_phrase(text: str) -> str:
    text = text.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z\- ]", " ", text).split())


_SECTION_OF = {_norm_phrase(p): key for key, phrases in _VOCAB["sections"].items() for p in phrases}
_UNPLACED_HEADERS = {_norm_phrase(p) for p in _VOCAB["unplacedSections"]}
_ROLE_WORDS = set(_VOCAB["roleWords"])
_CONTACT_LABELS = {_norm_phrase(p) for p in _VOCAB["contactLabels"]}
_LEVEL_OF = {_norm_phrase(p): level for level, phrases in _VOCAB["languageLevels"].items() for p in phrases}

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
_PHONE_LABEL = re.compile(r"\b(?:phone|tel|telephone|mobile|mob|cell)\b", re.I)
_LOCATION_LABEL = re.compile(r"^(?:location|address|based in|city)\s*:\s*(.+)$", re.I)
_PLACE = re.compile(r"^[A-Z][A-Za-z.'’\- ]{1,30}(?:,\s*[A-Z][A-Za-z.'’\- ]{1,30}){1,2}$")
_GROUP_LINE = re.compile(r"^([A-Za-z][A-Za-z &/+.#-]{1,40}):\s*(.+)$")
_DURATION = re.compile(r"\(?\s*\b\d+\s*(?:years?|yrs?)\b(?:\s+\d+\s*(?:months?|mos?)\b)?\s*\)?|\(?\s*\b\d+\s*(?:months?|mos?)\b\s*\)?", re.I)
_LANGUAGE = re.compile(r"^([A-Za-z]+(?: [A-Za-z]+)?)\s*(?:\(([^)]*)\)|[:\-–—]\s*(.+))?$")


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
        for pattern in (SCHEME_URL_RE, SOCIAL_RE, PATH_URL_RE):
            found["links"].extend(m.group(0).rstrip(_TRAILING) for m in pattern.finditer(token))
            token = pattern.sub("", token)
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
    """True when a phone label ("Phone:", "Tel") ends right before `start`."""
    return any(re.fullmatch(r"[\s:.\-–]*", line[m.end():start]) for m in _PHONE_LABEL.finditer(line) if m.end() <= start)


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


def _is_name(text: str) -> bool:
    words = text.split()
    if not 2 <= len(words) <= 4 or len(text) > 50 or _has_role_word(text):
        return False
    if re.search(r"resume|curriculum|vitae|\bcv\b", text, re.I):
        return False
    return all(w[0].isupper() and all(c.isalpha() or c in "'’.-" for c in w) for w in words)


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


def _parse_skills(lines: list[str], unplaced: list[dict], confidence: dict) -> tuple[list[str], list[dict]]:
    skills: list[str] = []
    groups: list[dict] = []
    leftovers: list[str] = []
    seen: set[str] = set()

    def add(items: list[str]) -> list[str]:
        kept = []
        for item in items:
            words = item.split()
            if not (1 <= len(words) <= 5 and len(item) <= 40 and re.search(r"\w", item)):
                leftovers.append(item)
                continue
            if item.lower() not in seen:
                seen.add(item.lower())
                skills.append(item)
            kept.append(item)
        return kept

    for line in lines:
        if not line:
            continue
        text = _strip_bullet(line)
        grouped = _GROUP_LINE.match(text)
        if grouped:
            items = add(_split_items(grouped.group(2)))
            if len(items) >= 2:
                groups.append({"label": grouped.group(1).strip(), "items": items})
        else:
            add(_split_items(text))
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


def _heads_before(lines: list[str], index: int, floor: int) -> list[str]:
    heads: list[str] = []
    j = index - 1
    while j > floor and len(heads) < 2:
        line = lines[j]
        if not line or _BULLET.match(line) or len(line) > 80 or line.endswith("."):
            break
        heads.insert(0, line)
        j -= 1
    return heads


def _split_title_company(candidates: list[str]) -> tuple[str, str, str]:
    """(title, company, confidence) from one to two header strings."""
    if len(candidates) >= 2:
        first, second = candidates[0], candidates[1]
        if _has_role_word(second) and not _has_role_word(first):
            return second, first, "medium"
        return first, second, "medium" if _has_role_word(first) else "low"
    text = candidates[0] if candidates else ""
    for sep in (" at ", " @ ", " — ", " – ", " | ", " - "):
        if sep in text:
            left, right = (p.strip() for p in text.split(sep, 1))
            if sep not in (" at ", " @ ") and _has_role_word(right) and not _has_role_word(left):
                return right, left, "medium"
            return left, right, "medium" if _has_role_word(left) or sep in (" at ", " @ ") else "low"
    return text, "", "low"


def _derived_line(entry: dict) -> str:
    head = " — ".join(p for p in (entry["title"], entry["company"]) if p)
    period = " – ".join(p for p in (entry["start"], entry["end"]) if p)
    bullets = " ".join(b if b[-1] in ".!?" else b + "." for b in entry["bullets"])
    return " | ".join([head, period, bullets]) if bullets else " | ".join([head, period])


def _parse_experience(lines: list[str], unplaced: list[dict], confidence: dict, warnings: list[str]) -> tuple[list[dict], list[str]]:
    starts = [i for i, l in enumerate(lines) if l and len(l) <= 200 and not _BULLET.match(l) and _RANGE.search(l)]
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
        if len(candidates) > 2:
            unplaced.append({"label": "Experience (extra heading lines)", "text": "\n".join(candidates[:-2])})
            candidates = candidates[-2:]
        title, company, level = _split_title_company(candidates)
        end_index = (starts[k + 1] - len(heads[k + 1])) if k + 1 < len(starts) else len(lines)
        bullets: list[str] = []
        for line in lines[i + 1 : end_index]:
            if not line:
                continue
            text = _strip_bullet(line)
            if bullets and not _BULLET.match(line) and text[:1].islower():
                bullets[-1] = f"{bullets[-1]} {text}"
            else:
                bullets.append(text)
        entry = {"title": title, "company": company, "start": match.group(1).strip(), "end": match.group(2).strip(), "bullets": bullets}
        confidence[f"experienceDetail.{len(entries)}"] = level if title else "low"
        entries.append(entry)

    if len(entries) > MAX_ENTRIES:
        extra = entries[MAX_ENTRIES:]
        entries = entries[:MAX_ENTRIES]
        unplaced.append({"label": f"Experience (beyond {MAX_ENTRIES} entries)", "text": "\n".join(_derived_line(e) for e in extra)})
    confidence["workExperience"] = "medium"
    return entries, [_derived_line(e) for e in entries]


def parse_text(text: object) -> dict:
    """The import draft for pasted CV text. Raises TextImportError with a fixed code."""
    raw_text = clean_text(text)
    lines = [l.strip() for l in raw_text.split("\n")]
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
    phone = ""
    phone_values: set[str] = set()
    for i, line in enumerate(scrubbed):
        for value, (start, _) in _phone_spans(line):
            labelled = _labelled(line, start)
            if value.startswith("+") or labelled:
                phone_values.add(value)
            if not phone and (value.startswith("+") or labelled or nonblank_rank.get(i, 99) < 12):
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
    for index, line in enumerate(scrubbed):
        if line and _DECORATION.match(line):
            continue
        marked = _header(line) if line else None
        if marked and marked[2] and current is not None and sections and sections[-1][2] is current and sections[-1][0] == marked[0] and sections[-1][1] == marked[1]:
            marked = None  # "Tools: SQL, Jira" inside the skills section is a labelled group, not a new section
        if marked:
            kind, key, inline = marked
            target = next((s for s in sections if s[0] == kind and s[1] == key), None)
            if target is None:
                target = (kind, key, [])
                sections.append(target)
            current = target[2]
            if inline:
                current.append(inline)
            continue
        if current is not None:
            current.append(line)
        else:
            preamble.append((index, line))

    basic: dict[str, str] = {}
    name_line = None
    headline_done = False
    leftovers: list[str] = []
    for index, line in preamble:
        if not line:
            continue
        was_contact = index in changed_lines
        pieces = [p.strip() for p in re.split(_SEPARATORS, line) if p.strip()]
        if name_line is None and pieces and _is_name(pieces[0]):
            name_line = pieces[0]
            basic["fullName"] = name_line
            confidence["fullName"] = "medium"
            pieces = pieces[1:]
            if not pieces:
                continue
        elif name_line is None and not was_contact:
            name_line = ""
        for piece in pieces:
            label = _LOCATION_LABEL.match(piece)
            if label and "location" not in basic:
                basic["location"] = label.group(1).strip()
                confidence["location"] = "medium"
            elif _norm_phrase(piece.rstrip(":")) in _CONTACT_LABELS:
                continue
            elif "location" not in basic and _PLACE.match(piece) and not _has_role_word(piece):
                basic["location"] = piece
                confidence["location"] = "low"
            elif not headline_done and not was_contact and len(piece) <= 80 and not piece.endswith(".") and len(piece.split()) <= 10:
                basic["currentRole"] = piece
                confidence["currentRole"] = "medium" if _has_role_word(piece) else "low"
                headline_done = True
            else:
                leftovers.append(piece)
    if leftovers:
        label = "Top of the document" if sections else "Text without headings"
        unplaced.append({"label": label, "text": "\n".join(leftovers)})

    skills: list[str] = []
    groups: list[dict] = []
    languages: list[dict] = []
    entries: list[dict] = []
    parsed = {"skills": [], "projects": [], "education": [], "workExperience": [], "certifications": []}
    for kind, key, lines_in in sections:
        body = lines_in
        if kind == "unplaced":
            text_block = "\n".join(l for l in body if l)
            if text_block:
                unplaced.append({"label": key.title() if key.isupper() else key, "text": text_block})
        elif key == "summary":
            text_block = "\n".join(l for l in body if l)
            if text_block:
                unplaced.append({"label": "Summary", "text": text_block})
        elif key == "experience":
            entries, parsed["workExperience"] = _parse_experience(body, unplaced, confidence, warnings)
        elif key == "skills":
            skills, groups = _parse_skills(body, unplaced, confidence)
            parsed["skills"] = skills
        elif key == "languages":
            languages = _parse_languages(body, unplaced)
            confidence["languages"] = "medium" if languages else "low"
        elif key == "links":
            rest = "\n".join(l for l in body if l and _norm_phrase(l.rstrip(":")) not in _CONTACT_LABELS)
            if rest:
                unplaced.append({"label": "Links", "text": rest})
        else:
            items = _groups(body)
            if len(items) > MAX_ENTRIES:
                unplaced.append({"label": f"{key.title()} (beyond {MAX_ENTRIES} entries)", "text": "\n".join(items[MAX_ENTRIES:])})
                items = items[:MAX_ENTRIES]
            parsed[key] = items
            confidence[key] = "medium" if items else "low"

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

    return {
        "source": "paste",
        "fileName": "",
        "rawText": raw_text,
        "basicProfile": basic,
        "parsedData": {**parsed, "experienceDetail": entries, "competencyGroups": groups},
        "languages": languages,
        "links": links,
        "confidence": confidence,
        "unplaced": unplaced,
        "ignored": [],
        "warnings": warnings,
    }
