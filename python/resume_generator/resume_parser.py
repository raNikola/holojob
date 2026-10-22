"""Read a candidate's CV text into the structure the CV templates need.

Nothing here is tuned to one person's CV:

* sections are found by the words a heading contains, not by an exact list
* experience entries are anchored on their date ranges
* the header is read by the patterns contact details follow, and the name is
  located through the profile's own name

PDF text often arrives as one long line with no line breaks, so every step
works on flat text and treats newlines as a bonus. What the text cannot give
reliably (an entry's title and company) comes from the profile's own lists,
which the profile form shows and edits. Nothing is ever filled in with a
default: a part that cannot be read stays empty.
"""

from __future__ import annotations

import re
import unicodedata

# --- sections ---------------------------------------------------------------------------------

# A heading is recognised by a stem it contains, so "PROFESSIONAL EXPERIENCE",
# "Work History" and "EXPERIENCE & PROJECTS" all read as experience.
SECTION_STEMS = {
    "summary": ("SUMMARY", "PROFILE", "ABOUT", "OBJECTIVE", "PERSONAL STATEMENT"),
    "experience": ("EXPERIENCE", "EMPLOYMENT", "WORK HISTORY", "CAREER HISTORY"),
    "skills": ("SKILL", "COMPETENC", "EXPERTISE", "TECHNOLOG", "TOOLS", "TOOLKIT"),
    "education": ("EDUCATION", "ACADEMIC", "QUALIFICATION", "TRAINING"),
}
# Headings that end a section without being one the CV uses.
STOP_STEMS = (
    "CERTIF", "PROJECT", "LANGUAGE", "AWARD", "PUBLICATION", "INTEREST", "REFERENCE",
    "VOLUNTEER", "COURSE", "HOBB", "ACHIEVEMENT", "PATENT", "ACTIVITIES",
)
_UPPER_JOINERS = {"&", "/"}
_HEADING_MAX_WORDS = 6


def _kind_of(text: str) -> str | None:
    upper = text.upper()
    for kind, stems in SECTION_STEMS.items():
        if any(stem in upper for stem in stems):
            return kind
    if any(stem in upper for stem in STOP_STEMS):
        return "other"
    return None


def _is_upper_token(token: str) -> bool:
    core = token.strip(".,:;()[]|•")
    return core in _UPPER_JOINERS or (len(core) >= 2 and core.isupper())


def _find_headings(text: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) of every section heading, in order."""
    found: list[tuple[int, int, str]] = []

    # Runs of capitalised words, which is how a heading survives flat PDF text.
    run: list[re.Match] = []

    def close_run() -> None:
        if run and len(run) <= _HEADING_MAX_WORDS:
            kind = _kind_of(" ".join(m.group() for m in run))
            if kind:
                found.append((run[0].start(), run[-1].end(), kind))
        run.clear()

    for match in re.finditer(r"\S+", text):
        if _is_upper_token(match.group()):
            run.append(match)
        else:
            close_run()
    close_run()

    # A short line on its own, in Title Case or ending in a colon ("Work History").
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        words = stripped.rstrip(":").split()
        if 1 <= len(words) <= 5 and (stripped.istitle() or stripped.endswith(":")):
            kind = _kind_of(stripped)
            if kind:
                start = offset + line.index(stripped[0])
                found.append((start, start + len(stripped), kind))
        offset += len(line)

    found.sort()
    merged: list[tuple[int, int, str]] = []
    for start, end, kind in found:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end, kind))
    return merged


def split_sections(raw: str) -> tuple[str, dict[str, str]]:
    """The text before the first heading, and the text under each kind of heading."""
    text = raw or ""
    headings = _find_headings(text)
    if not headings:
        return text, {}
    blocks: dict[str, list[str]] = {}
    for i, (_, end, kind) in enumerate(headings):
        stop = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        blocks.setdefault(kind, []).append(text[end:stop])
    return text[: headings[0][0]], {kind: "\n".join(parts) for kind, parts in blocks.items()}


# --- text hygiene -----------------------------------------------------------------------------


def _squash(text: str) -> str:
    """One line, single spaces, and none of the PDF's stray space before punctuation."""
    text = re.sub(r"\s*Page \d+ of \d+\s*", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def _fold(text: str) -> str:
    """Lower case without diacritics, so "Niš" and "NIS" compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


# --- header -----------------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<![\w/])\+?\d[\d ()./-]{6,}\d(?![\w/])")
LINK_RE = re.compile(r"(?<![\w@.])(?:https?://)?(?:[\w-]+\.)+(?!js\b)[a-z]{2,}(?:/[^\s|,;]*)?", re.I)
_LABEL_WORDS = r"(?:DETAILS|CONTACT|CONTACTS|INFO|INFORMATION)"
_LOWER_WORDS = {"FOR", "AND", "OF", "THE", "IN", "AT", "TO", "ON", "WITH", "BY"}


def normalize_link(link: str) -> str:
    """'https://www.linkedin.com/in/jane/' -> 'linkedin.com/in/jane'."""
    return re.sub(r"^https?://(?:www\.)?|^www\.|/+$", "", (link or "").strip(), flags=re.I)


def _is_title_word(word: str) -> bool:
    return len(word) > 1 and word[0].isupper() and word[1:].islower()


def _find_place(text: str) -> re.Match | None:
    """'City, Country' as two runs of Title Case words around a comma.

    Title Case is what keeps a heading like "DETAILS" out of the city and a job
    title like "Product Lead, ACME" from reading as a place.
    """
    word = r"[^\W\d_][\w'.-]*"
    for comma in re.finditer(",", text):
        # A line break or a separator ends a name: "Senior Engineer" above
        # "Zagreb, Croatia", or "Jo Doe | Austin, TX", are separate things.
        left = re.findall(word, re.split(r"[|\n•·]", text[: comma.start()])[-1])[-2:]
        right = re.findall(word, re.split(r"[|\n•·]", text[comma.end():])[0])[:2]
        city: list[str] = []
        for token in reversed(left):
            if not _is_title_word(token):
                break
            city.insert(0, token)
        country: list[str] = []
        for index, token in enumerate(right):
            # A country or state code ("UK", "USA", "NY") is fine as the first word.
            code = index == 0 and token.isupper() and 2 <= len(token) <= 3
            if not (_is_title_word(token) or code):
                break
            country.append(token)
        if city and country:
            pattern = r"\s+".join(map(re.escape, city)) + r"\s*,\s*" + r"\s+".join(map(re.escape, country))
            found = re.search(pattern, text)
            if found:
                return found
    return None


def _locate_name(header: str, full_name: str) -> tuple[str, int]:
    """The name as the CV writes it, and where it ends in the header.

    The profile's own name is the anchor: flat text has no "first line".
    Without one, the first line is used, or else the first few plain words.
    """
    tokens = [(m.start(), m.end(), _fold(m.group())) for m in re.finditer(r"\S+", header)]
    want = [_fold(part) for part in (full_name or "").split()]
    if want:
        for i in range(len(tokens) - len(want) + 1):
            if [t[2] for t in tokens[i : i + len(want)]] == want:
                start, end = tokens[i][0], tokens[i + len(want) - 1][1]
                return header[start:end], end

    first = next((ln for ln in header.splitlines() if ln.strip()), "") if "\n" in header else ""
    if first and len(first.split()) <= 6 and not re.search(r"[\d@]", first):
        return first.strip(), header.index(first) + len(first)

    plain = []
    for start, end, _ in tokens[:3]:
        word = header[start:end]
        if not re.fullmatch(r"[^\W\d_][\w'.-]*", word):
            break
        plain.append(word)
    return (" ".join(plain), tokens[len(plain) - 1][1]) if plain else ("", 0)


def _smart_case(text: str) -> str:
    """'TECHNICAL PRODUCT LEADER FOR B2B SaaS' -> 'Technical Product Leader for B2B SaaS'."""
    out = []
    for token in text.split():
        if token in _LOWER_WORDS:
            out.append(token.lower())
        elif token.isupper() and len(token) > 3:
            out.append(token.capitalize())
        else:
            out.append(token)
    return " ".join(out)


def parse_header(header: str, full_name: str = "") -> dict:
    """Name, headline and contact details from the text above the first heading."""
    text = header or ""
    work = text

    emails = EMAIL_RE.findall(work)
    work = EMAIL_RE.sub(" ", work)
    phones = [m.group().strip() for m in PHONE_RE.finditer(work) if 8 <= sum(c.isdigit() for c in m.group()) <= 15]
    work = PHONE_RE.sub(" ", work)
    links = [normalize_link(m.group()) for m in LINK_RE.finditer(work)]
    work = LINK_RE.sub(" ", work)
    place = _find_place(work)

    name, name_end = _locate_name(text, full_name)

    # The headline sits between the name and the first contact detail.
    tagline = ""
    if name:
        starts = [m.start() for m in (EMAIL_RE.search(text), PHONE_RE.search(text), LINK_RE.search(text)) if m]
        starts += [text.find(place.group())] if place and text.find(place.group()) >= 0 else []
        starts = [s for s in starts if s >= name_end]
        between = text[name_end : min(starts) if starts else len(text)]
        between = re.sub(rf"\s+{_LABEL_WORDS}\s*$", "", _squash(between), flags=re.I)
        tagline = _smart_case(between.strip(" |-–—:•"))

    return {
        "name": name,
        "headline": tagline,
        "location": place.group() if place else "",
        "phone": phones[0] if phones else "",
        "email": emails[0] if emails else "",
        "links": list(dict.fromkeys(links)),
    }


# --- experience -------------------------------------------------------------------------------

_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_POINT = rf"(?:{_MONTHS}\.?\s+(?:19|20)\d{{2}}|\d{{1,2}}[/.]\s?(?:19|20)\d{{2}}|(?:19|20)\d{{2}})"
DATE_RANGE_RE = re.compile(
    rf"{_DATE_POINT}\s*[–—-]\s*(?:Present|Current|Now|Ongoing|{_DATE_POINT})", re.I
)
_MONTH_NUMBER = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
# A date range after one of these is part of a sentence, not an entry's header.
_PREPOSITIONS = {
    "in", "during", "from", "since", "between", "until", "through", "over", "by", "of", "for",
    "the", "a", "an", "this", "that", "our", "their", "its", "to", "at", "on", "with",
}
_SMALL_WORDS = {"and", "of", "the", "for", "in", "at", "to", "on", "de", "van", "von", "&", "/"}
_BOUNDARY_RE = re.compile(r"(?:[.!?]|[•▪●◦])\s+(?=[A-Z0-9(])")
_BULLET_RE = re.compile(r"\s*[•▪●◦]\s*")
_HEADER_WINDOW = 160


def _start_key(text: str) -> tuple[int, int | None] | None:
    """(year, month or None) of the first date in the text."""
    match = re.search(rf"(?:({_MONTHS})\.?\s+)?((?:19|20)\d{{2}})", text or "", re.I)
    if not match:
        return None
    month = _MONTH_NUMBER.get((match.group(1) or "")[:3].lower())
    return int(match.group(2)), month


def _same_start(a: tuple[int, int | None] | None, b: tuple[int, int | None] | None) -> bool:
    if not a or not b or a[0] != b[0]:
        return False
    return a[1] is None or b[1] is None or a[1] == b[1]


def parse_role_entry(entry: str) -> dict:
    """One profile work-experience entry: 'Title — Company | Dates | Description'."""
    parts = [p.strip() for p in (entry or "").split(" | ")]
    title, _, company = (parts[0] if parts else "").partition(" — ")
    dates = parts[1] if len(parts) > 1 else ""
    return {
        "title": title.strip(),
        "company": company.strip(),
        "dates": dates,
        "description": " | ".join(parts[2:]).strip(),
        "start": _start_key(dates),
    }


def _looks_like_subheading(text: str) -> bool:
    words = text.split()
    if not words or len(words) > 7 or text.rstrip().endswith((".", "!", "?", ";", ",")):
        return False
    capital = sum(1 for w in words if w[0].isupper() or w in ("&", "and", "of"))
    return capital / len(words) >= 0.6


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text) if s.strip()]


def _bullets(body: str) -> list[str]:
    """The entry's text as bullets: marked bullets when it has them, else sentences."""
    body = body.strip()
    body = re.sub(r"^\|\s*", "", body)
    body = re.sub(r"^\([^)]{1,120}\)\s*", "", body)  # the company descriptor after the dates
    pieces = [_squash(p) for p in _BULLET_RE.split(body)]
    candidates: list[str] = []
    for index, piece in enumerate(pieces):
        # Text before the first bullet is narrative; each bullet after it stands alone.
        candidates.extend(_sentences(piece) if index == 0 or len(pieces) == 1 else [piece])
    return [c for c in candidates if len(c) >= 25 and not _looks_like_subheading(c)]


def _header_like(pre: str) -> bool:
    """Whether the text before a date range reads like an entry header.

    'Title, Company | Place' and 'Job Title' do. 'Reduced costs in' does not:
    that is a sentence with a year range in it.
    """
    pre = _squash(pre).strip(" |,;-")
    words = pre.split()
    if not 1 <= len(words) <= 14:
        return False
    if "|" in pre or "," in pre:
        return True
    return all(w[0].isupper() or w.lower() in _SMALL_WORDS or not w[0].isalpha() for w in words)


def _split_header(pre: str) -> tuple[str, str, str]:
    """(title, company, location) from the text before an entry's date range.

    'Title, Company | Location', 'Title, Company' and a bare 'Title' are the
    layouts it can tell apart; whatever it cannot split is left empty, not guessed.
    """
    pre = _squash(pre).strip(" |,;-")
    left, _, right = pre.partition("|")
    title, _, company = left.partition(",")
    return title.strip(), company.strip(), right.strip()


def _split_experience(block: str, roles: list[dict]) -> list[dict]:
    text = _squash(block)
    anchors: list[re.Match] = []
    starts: list[int] = []
    for match in DATE_RANGE_RE.finditer(text):
        previous = re.findall(r"[A-Za-z]+$", text[: match.start()].rstrip())
        if previous and previous[0].lower() in _PREPOSITIONS:
            continue
        floor = anchors[-1].end() if anchors else 0
        offset = max(floor, match.start() - _HEADER_WINDOW)
        boundaries = list(_BOUNDARY_RE.finditer(text[offset : match.start()]))
        start = offset + boundaries[-1].end() if boundaries else offset
        if not _header_like(text[start : match.start()]):
            continue
        anchors.append(match)
        starts.append(start)
    if not anchors:
        return []

    used: set[int] = set()
    entries = []
    for i, match in enumerate(anchors):
        title, company, location = _split_header(text[starts[i] : match.start()])
        key = _start_key(match.group())
        for j, role in enumerate(roles):
            if j not in used and _same_start(key, role["start"]):
                used.add(j)
                title, company = role["title"] or title, role["company"] or company
                break
        body = text[match.end() : starts[i + 1] if i + 1 < len(anchors) else len(text)]
        if company:
            # Some layouts put the company after the dates, so it opens the body.
            body = re.sub(rf"^\s*\|?\s*{re.escape(company)}\s*", "", body, flags=re.I)
        entries.append({
            "company": company,
            "location": location,
            "dates": re.sub(r"\s*[–—-]\s*", " – ", match.group()),
            "title": title,
            "bullets": _bullets(body),
        })
    return entries


# --- skills -----------------------------------------------------------------------------------

_LABEL_RE = re.compile(
    r"(?<![\w.,)])((?:[A-Z][\w+/]*|&)(?:\s+(?:[A-Z][\w+/]*|&|and|of|the)){0,3})\s*:\s+"
)


def skill_label(label: str) -> str:
    """A skills row label as the CV prints it.

    A bare "Languages" row lists programming languages, and the CV also has a
    section for the languages the candidate speaks, so the row is renamed.
    """
    label = (label or "").strip().rstrip(":").strip()
    return "Programming languages" if label.lower() in ("language", "languages") else label


def _split_items(text: str) -> list[str]:
    """Comma-separated items, keeping a comma inside parentheses with its item."""
    items, depth, current = [], 0, []
    for char in text:
        depth += (char == "(") - (char == ")")
        if char == "," and depth <= 0:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [i.strip().rstrip(".").strip() for i in items if i.strip().rstrip(".").strip()]


def parse_skill_rows(block: str) -> list[dict]:
    """'Label: item, item' rows, with any labels, however the line breaks fall."""
    text = _squash(block)
    labels = list(_LABEL_RE.finditer(text))
    rows = []
    for i, match in enumerate(labels):
        stop = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        items = _split_items(text[match.end() : stop])
        if items:
            rows.append({"label": skill_label(match.group(1)), "skills": items})
    return rows


# --- education --------------------------------------------------------------------------------

EDUCATION_SEPARATOR = " — "
EDUCATION_YEAR_RE = re.compile(r"\|\s*((?:19|20)\d{2})\s*$")


def parse_education_entry(entry: str) -> dict:
    """Read one "Degree — School | Year" entry from the profile's education list.

    That list is what the profile form shows and edits, so the CV prints what
    the candidate can see. Only what the entry states is returned: a part it
    does not state stays empty, because a CV must never show an education the
    candidate did not give.
    """
    text = _squash(entry or "")
    if not text:
        return {}
    year_m = EDUCATION_YEAR_RE.search(text)
    graduated = year_m.group(1) if year_m else ""
    body = text[: year_m.start()].strip() if year_m else text
    degree, _, school = body.partition(EDUCATION_SEPARATOR)
    return {"degree": degree.strip(), "school": school.strip(), "graduated": graduated}


def education_problem(education: dict) -> str | None:
    """Why this education cannot be trusted on a CV, or None when it can."""
    if not education:
        return (
            "the profile has no education entry, so the CV leaves the section out; "
            "add one as 'Degree — School | Year'"
        )
    degree = education.get("degree") or ""
    if not degree[:1].isalnum():
        return (
            f"the education entry looks malformed (it starts with {degree[:12]!r}); "
            "fix it in the profile"
        )
    if not education.get("school"):
        return (
            "the education entry has no school; write it as 'Degree — School | Year' "
            "so the CV can show it"
        )
    return None


# --- the whole CV -----------------------------------------------------------------------------


def parse_resume_from_profile(profile: dict) -> dict:
    resume = profile.get("resume") or {}
    parsed_data = resume.get("parsedData") or {}
    basic = profile.get("basicProfile") or {}
    raw = resume.get("rawText") or ""

    header_text, sections = split_sections(raw)
    header = parse_header(header_text, basic.get("fullName") or "")

    # The profile is what the candidate sees and edits, so it wins; the CV's own
    # header fills what the profile leaves blank. Links mirror the CV header when
    # it lists any, so the CV shows the links its owner chose to show.
    links = header["links"] or [normalize_link(link) for link in parsed_data.get("links") or []]
    contact_items = list(dict.fromkeys(filter(None, [
        (basic.get("location") or header["location"]).strip(),
        (basic.get("phone") or header["phone"]).strip(),
        (basic.get("email") or header["email"]).strip(),
        *links,
    ])))

    roles = [parse_role_entry(e) for e in parsed_data.get("workExperience") or [] if isinstance(e, str)]
    experience = _split_experience(sections.get("experience", ""), roles)
    if not experience:
        # No entry could be read from the CV text: the profile's own list is the CV.
        experience = [
            {
                "company": r["company"], "location": "", "dates": r["dates"], "title": r["title"],
                "bullets": [r["description"]] if r["description"] else [],
            }
            for r in roles
        ]

    entries = parsed_data.get("education") or []
    # One education block fits the templates; the first entry that reads is used.
    education = next((e for e in map(parse_education_entry, entries) if e), {})

    name = (basic.get("fullName") or header["name"] or "Candidate").strip()
    return {
        "name": name.upper() if len(name) < 40 else name,
        "headline": header["headline"],
        "contact": " | ".join(contact_items),
        "contact_items": contact_items,
        "about_me": _squash(sections.get("summary", "")),
        "experience": experience,
        "skill_categories": parse_skill_rows(sections.get("skills", "")),
        "education": education,
    }
