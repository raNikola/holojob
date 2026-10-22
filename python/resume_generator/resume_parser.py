"""Parse canonical resume structure from profile rawText."""

from __future__ import annotations

import re

DATE_RANGE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s*[–\-]\s*(?:Present|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})",
    re.I,
)

TITLE_PATTERNS = [
    "Deputy CTO",
    "Founder & Lead Engineer",
    "Flutter Developer (Contract)",
]

SKILL_LINE_RE = re.compile(
    r"^(Languages|Backend\s*Frameworks?|Frontend\s*Frameworks?|Databases|DevOps and Cloud|Cloud\s*&\s*DevOps|Platforms and Tools)\s*:?\s*(.+)$",
    re.I,
)


def _clean(text: str) -> str:
    text = re.sub(r"\s*Page \d+ of \d+\s*", "", text)
    text = re.sub(r"•\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_section(raw: str, start_marker: str, end_markers: list[str]) -> str:
    text = raw or ""
    start = text.upper().find(start_marker.upper())
    if start < 0:
        return ""
    start += len(start_marker)
    end = len(text)
    for em in end_markers:
        idx = text.upper().find(em.upper(), start)
        if idx >= 0:
            end = min(end, idx)
    return _clean(text[start:end])


def _parse_header(raw: str) -> tuple[str, str]:
    text = raw or ""
    idx = text.upper().find("ABOUT ME")
    header = text[:idx].strip() if idx >= 0 else text[:300]

    # Contact starts at city (prefer) or email — avoid greedy .+@ match from string start
    contact_m = re.search(r"Mumbai,\s*India", header, re.I)
    if not contact_m:
        contact_m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", header)
    if contact_m:
        name = header[: contact_m.start()].strip()
        contact = header[contact_m.start() :].strip()
        name = re.sub(r"\s+", " ", name).strip()
        contact = re.sub(r"\s*\|\s*", " | ", contact)
        return name, contact

    if "|" in header:
        parts = [p.strip() for p in header.split("|")]
        return parts[0], " | ".join(parts[1:])
    return header, ""


def _split_bullets(text: str) -> list[str]:
    if not text:
        return []
    text = re.sub(r"\s*(SKILLS AND OTHERS|EDUCATION).*$", "", text, flags=re.I)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    bullets = []
    for s in sentences:
        s = s.strip()
        if len(s) < 25:
            continue
        # Drop stray next-job headers absorbed into bullet list
        if re.match(r"^(ECS Financials|Calcitex Cybernetics|Adtip)\s", s):
            continue
        if re.search(r"\s+—\s+[A-Z][a-z]+,\s", s) and len(s) < 80:
            continue
        bullets.append(s)
    return bullets


def _extract_title_and_bullets(after_dates: str) -> tuple[str, list[str]]:
    text = after_dates.strip()
    for title in TITLE_PATTERNS:
        if text.startswith(title):
            body = text[len(title) :].strip()
            return title, _split_bullets(body)
    # Generic: title is first clause before action verb
    m = re.match(r"^([A-Z][^B]+?)\s+(Built|Led|Developed|Engineered|Managed|Owned|Collaborated|Designed|Automated|Delivered)", text)
    if m:
        return m.group(1).strip(), _split_bullets(text[m.end(1) :].strip())
    return "", _split_bullets(text)


def _split_experience_block(block: str) -> list[dict]:
    if not block:
        return []

    entries: list[dict] = []
    matches = list(DATE_RANGE_RE.finditer(block))
    if not matches:
        return entries

    for i, m in enumerate(matches):
        dates = m.group(0)
        seg_start = matches[i - 1].end() if i > 0 else 0
        seg_end = m.start()
        preamble = block[seg_start:seg_end].strip()

        # Keep only company line from preamble (drop trailing text from previous job bullets)
        for company_name in ("ECS Financials", "Calcitex Cybernetics", "Adtip"):
            pos = preamble.rfind(company_name)
            if pos >= 0:
                preamble = preamble[pos:]
                break

        company, location = "", ""
        if " — " in preamble:
            company, location = [p.strip() for p in preamble.split(" — ", 1)]
        elif preamble:
            company = preamble.split()[0] if preamble.startswith("Adtip") else preamble.strip()

        next_end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        after = block[m.end() : next_end].strip()
        title, bullets = _extract_title_and_bullets(after)

        entries.append({
            "company": company,
            "location": location,
            "dates": dates,
            "title": title,
            "bullets": bullets,
        })

    return entries


def _parse_skills(block: str) -> list[dict]:
    if not block:
        return []
    categories: list[dict] = []
    # Normalize glued labels from PDF extract (e.g. "Frameworks: Node.js")
    block = re.sub(r"Backend\s*Frameworks?:", "\nBackend Frameworks:", block, flags=re.I)
    block = re.sub(r"Frontend\s*Frameworks?:", "\nFrontend Frameworks:", block, flags=re.I)
    block = re.sub(r"DevOps and Cloud:", "\nDevOps and Cloud:", block, flags=re.I)
    block = re.sub(r"Platforms and Tools:", "\nPlatforms and Tools:", block, flags=re.I)
    block = re.sub(r"Databases:", "\nDatabases:", block, flags=re.I)
    block = re.sub(r"Languages:", "\nLanguages:", block, flags=re.I)

    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = SKILL_LINE_RE.match(line)
        if m:
            categories.append({
                "label": m.group(1).strip().rstrip(":"),
                "skills": [s.strip() for s in m.group(2).split(",") if s.strip()],
            })
        elif ":" in line:
            label, items = line.split(":", 1)
            categories.append({
                "label": label.strip(),
                "skills": [s.strip() for s in items.split(",") if s.strip()],
            })

    if not categories and block:
        # Single-line skills block from PDF
        for label in ("Languages", "Backend Frameworks", "Frontend Frameworks", "Databases", "DevOps and Cloud", "Platforms and Tools"):
            pat = rf"{label}\s*:?\s*([^:]+?)(?=(?:Languages|Backend|Frontend|Databases|DevOps|Platforms|EDUCATION)|$)"
            m = re.search(pat, block, re.I)
            if m:
                categories.append({
                    "label": label,
                    "skills": [s.strip() for s in m.group(1).split(",") if s.strip()],
                })
    return categories


EDUCATION_SEPARATOR = " — "
EDUCATION_YEAR_RE = re.compile(r"\|\s*((?:19|20)\d{2})\s*$")
EDUCATION_CGPA_RE = re.compile(r"[,;|]?\s*CGPA:?\s*([\d.]+(?:\s*/\s*\d+)?)", re.I)


def parse_education_entry(entry: str) -> dict:
    """Read one "Degree — School | Year" entry from the profile's education list.

    That list is what the profile form shows and edits, so the CV prints what
    the candidate can see. Only what the entry states is returned: a part it
    does not state stays empty, because a CV must never show an education the
    candidate did not give.
    """
    text = _clean(entry or "")
    if not text:
        return {}

    cgpa = ""
    cgpa_m = EDUCATION_CGPA_RE.search(text)
    if cgpa_m:
        cgpa = re.sub(r"\s+", "", cgpa_m.group(1))
        text = (text[: cgpa_m.start()] + text[cgpa_m.end() :]).strip()

    year_m = EDUCATION_YEAR_RE.search(text)
    graduated = year_m.group(1) if year_m else ""
    body = text[: year_m.start()].strip() if year_m else text

    degree, _, school = body.partition(EDUCATION_SEPARATOR)
    return {
        "degree": degree.strip(),
        "school": school.strip(),
        "graduated": graduated,
        "cgpa": cgpa,
    }


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


def parse_resume_from_profile(profile: dict) -> dict:
    raw = (profile.get("resume") or {}).get("rawText") or ""
    basic = profile.get("basicProfile") or {}

    name, contact = _parse_header(raw)
    if not name:
        name = (basic.get("fullName") or "Candidate").strip()
    if not contact:
        contact = " | ".join(filter(None, [
            basic.get("location"),
            basic.get("email"),
            basic.get("phone"),
            basic.get("linkedin"),
        ]))

    about = _extract_section(raw, "ABOUT ME", ["PROFESSIONAL EXPERIENCE", "SKILLS", "EDUCATION"])
    exp_block = _extract_section(raw, "PROFESSIONAL EXPERIENCE", ["SKILLS AND OTHERS", "TECHNICAL SKILLS", "EDUCATION"])
    skills_block = _extract_section(raw, "SKILLS AND OTHERS", ["EDUCATION"])
    if not skills_block:
        skills_block = _extract_section(raw, "TECHNICAL SKILLS", ["EDUCATION"])

    experience = _split_experience_block(exp_block)
    skill_categories = _parse_skills(skills_block)
    entries = ((profile.get("resume") or {}).get("parsedData") or {}).get("education") or []
    # One education block fits the templates; the first entry that reads is used.
    education = next((e for e in map(parse_education_entry, entries) if e), {})

    return {
        "name": name.upper() if len(name) < 40 else name,
        "contact": contact,
        "about_me": about,
        "experience": experience,
        "skill_categories": skill_categories,
        "education": education,
    }
