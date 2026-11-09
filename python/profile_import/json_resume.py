"""A JSON Resume file (https://jsonresume.org/schema/) as an import draft (Wave 7, S3).

Deterministic: every field is read from where the schema puts it, nothing is guessed from prose and no model is involved. The draft has the
same shape as the text parser's, so the review screen, the confirm step and the apply step do not know the difference. Wrong types are
skipped (and counted in the warnings), never raised on; a file that is not JSON, or is JSON without any resume section, is refused with a
fixed code. Free text (summary, descriptions, highlights) goes through the same identifier scrub as pasted text; `references` (other
people's contact details) are never read.
"""

from __future__ import annotations

import json
import re
from datetime import date

from profile_import.text_parser import (
    DRAFT_VERSION,
    MAX_ENTRIES,
    MAX_LINKS,
    MAX_SKILLS,
    MAX_TEXT_BYTES,
    TextImportError,
    _derived_line,
    _earliest_year,
    _latest_entry,
    _scrub_line,
)

PARSER_VERSION = "json-1"
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")
_SECTIONS = ("basics", "work", "education", "skills", "languages", "projects", "certificates")
_UNUSED = {
    "volunteer": "Volunteer work is not used by the profile",
    "awards": "Awards are not used by the profile",
    "publications": "Publications are not used by the profile",
    "interests": "Interests are not used by the profile",
    "references": "References hold other people's contact details; they are not read",
}
_LEVELS = (
    (("native", "mother", "bilingual"), "native"),
    (("fluent", "full professional", "full_professional"), "fluent"),
    (("advanced", "professional", "c1", "c2"), "advanced"),
    (("intermediate", "conversational", "limited", "b1", "b2"), "intermediate"),
    (("basic", "elementary", "beginner", "a1", "a2"), "basic"),
)


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _dicts(value: object) -> list[dict]:
    return [v for v in _list(value) if isinstance(v, dict)]


def _when(value: object) -> str:
    """"2024-04" -> "April 2024", "2019" -> "2019"; anything else is kept as written."""
    raw = _text(value)
    match = _DATE.match(raw)
    if not match:
        return raw
    year, month = match.group(1), match.group(2)
    return f"{_MONTHS[int(month) - 1]} {year}" if month and 1 <= int(month) <= 12 else year


def _proficiency(value: object) -> str:
    low = _text(value).lower()
    for needles, level in _LEVELS:
        if any(n in low for n in needles):
            return level
    return ""


def _free(value: object, found: dict[str, list[str]], touched: list[bool]) -> str:
    clean, changed = _scrub_line(_text(value), found)
    touched[0] = touched[0] or changed
    return clean


def parse_json_resume(text: object, today: date | None = None) -> dict:
    """The import draft for a JSON Resume document. Raises TextImportError (json_invalid, json_not_resume, empty, too_large)."""
    if not isinstance(text, str):
        raise TextImportError("invalid_request")
    if len(text.encode("utf-8", "replace")) > MAX_TEXT_BYTES:
        raise TextImportError("too_large")
    if not text.strip():
        raise TextImportError("empty")
    try:
        doc = json.loads(text.lstrip("﻿"))
    except ValueError:
        raise TextImportError("json_invalid") from None
    if not isinstance(doc, dict) or not any(doc.get(s) for s in _SECTIONS):
        raise TextImportError("json_not_resume")

    found: dict[str, list[str]] = {"emails": [], "links": []}
    touched = [False]
    warnings: list[str] = []
    ignored: list[dict] = []
    confidence: dict[str, str] = {}

    for key in _SECTIONS:
        if key in doc and not isinstance(doc[key], (dict if key == "basics" else list)):
            warnings.append(f"The '{key}' section is not in the shape the JSON Resume schema defines, so it was skipped.")
    basics = doc["basics"] if isinstance(doc.get("basics"), dict) else {}

    # basics ----------------------------------------------------------------------------------------------
    basic: dict[str, str] = {}
    name, email, phone = _text(basics.get("name")), _text(basics.get("email")), _text(basics.get("phone"))
    place = basics.get("location") if isinstance(basics.get("location"), dict) else {}
    location = ", ".join(p for p in (_text(place.get("city")), _text(place.get("region")), _text(place.get("countryCode"))) if p)
    for field, value in (("fullName", name), ("email", email), ("phone", phone), ("location", location)):
        if value:
            basic[field] = value
            confidence[field] = "high"
    headline = _text(basics.get("label"))
    summary = _free(basics.get("summary"), found, touched)
    if summary:
        confidence["summary"] = "high"

    links: list[str] = []
    for url in [basics.get("url")] + [p.get("url") for p in _dicts(basics.get("profiles"))]:
        url = _text(url)
        if url and url.lower() not in {l.lower() for l in links}:
            links.append(url)

    # work -----------------------------------------------------------------------------------------------
    entries: list[dict] = []
    for k, job in enumerate(_dicts(doc.get("work"))[:MAX_ENTRIES]):
        start, end = _when(job.get("startDate")), _when(job.get("endDate"))
        if start and not end:
            end = "Present"
        entry = {
            "title": _text(job.get("position")),
            "company": _text(job.get("name") or job.get("company")),
            "location": _text(job.get("location")),
            "start": start,
            "end": end,
            "description": _free(job.get("summary") or job.get("description"), found, touched),
            "bullets": [b for b in (_free(h, found, touched) for h in _list(job.get("highlights"))) if b],
        }
        confidence[f"experienceDetail.{k}"] = "high" if entry["title"] and entry["company"] else "low"
        if not (entry["title"] and entry["company"]):
            warnings.append(f"Experience entry {k + 1}: the position or the company is missing in the file. Check it.")
        if any(entry[f] for f in ("title", "company", "description", "start")) or entry["bullets"]:
            entries.append(entry)
    if len(_list(doc.get("work"))) > MAX_ENTRIES:
        warnings.append(f"Only the first {MAX_ENTRIES} jobs were read.")
    if entries:
        confidence["workExperience"] = "high"

    # education, certificates, projects, skills, languages -------------------------------------------------
    education: list[str] = []
    education_detail: list[dict] = []
    for k, item in enumerate(_dicts(doc.get("education"))):
        degree = " ".join(p for p in (_text(item.get("studyType")), _text(item.get("area"))) if p)
        school = _text(item.get("institution"))
        years = [y for y in (_when(item.get("startDate")), _when(item.get("endDate"))) if y]
        year = years[-1] if years else ""
        line = ", ".join(p for p in (degree, school, year) if p)
        if line:
            education.append(line)
            education_detail.append({"text": line, "degree": degree, "school": school, "year": year})
            confidence[f"educationDetail.{k}"] = "high"
    if education:
        confidence["education"] = "high"

    certifications = [
        line for line in (", ".join(p for p in (_text(c.get("name")), _text(c.get("issuer")), _when(c.get("date"))) if p) for c in _dicts(doc.get("certificates"))) if line
    ]
    if certifications:
        confidence["certifications"] = "high"

    projects: list[str] = []
    for item in _dicts(doc.get("projects")):
        label = _text(item.get("name"))
        about = _free(item.get("description"), found, touched)
        line = f"{label}: {about}" if label and about else (label or about)
        if line:
            projects.append(line)
    if projects:
        confidence["projects"] = "high"

    skills: list[str] = []
    groups: list[dict] = []
    for item in _dicts(doc.get("skills")):
        label = _text(item.get("name"))
        keywords = [k for k in (_text(x) for x in _list(item.get("keywords"))) if k]
        for word in keywords or ([label] if label else []):
            if word.lower() not in {s.lower() for s in skills}:
                skills.append(word)
        if label and keywords:
            groups.append({"label": label, "items": keywords})
    skills = skills[:MAX_SKILLS]
    if skills:
        confidence["skills"] = "high"

    languages: list[dict] = []
    for item in _dicts(doc.get("languages")):
        language = _text(item.get("language"))
        if language and language.lower() not in {l["language"].lower() for l in languages}:
            languages.append({"language": language, "proficiency": _proficiency(item.get("fluency"))})
    if languages:
        confidence["languages"] = "high"

    for key, reason in _UNUSED.items():
        count = len(_list(doc.get(key)))
        if count:
            ignored.append({"name": f"{key.capitalize()} ({count})", "reason": reason})

    # derived ---------------------------------------------------------------------------------------------
    latest = _latest_entry(entries)
    if latest and latest["title"]:
        basic["currentRole"] = latest["title"]
        confidence["currentRole"] = "high"
    elif headline:
        basic["currentRole"] = headline
        confidence["currentRole"] = "medium"
    earliest = _earliest_year(entries)
    if earliest:
        years = (today or date.today()).year - earliest
        if years >= 1:
            basic["experienceYears"] = str(years)
            confidence["experienceYears"] = "derived"
            warnings.append(f"Experience (years) was counted from the earliest start date, {earliest}.")

    for value in found["links"]:
        if value and value.lower() not in {l.lower() for l in links}:
            links.append(value)
    links = links[:MAX_LINKS]
    if links:
        confidence["links"] = "high"
    for value in found["emails"]:
        if value and "email" not in basic:
            basic["email"] = value
            confidence["email"] = "high"
    if touched[0]:
        warnings.append("E-mail addresses, phone numbers and links were moved out of the text into their own fields.")
    if not any((entries, education, skills, certifications, projects, summary, languages)):
        warnings.append("The file has no experience, education, skills or summary that could be read.")

    workline = [_derived_line(e) for e in entries]
    raw = _render(basic, headline, links, summary, entries, education, skills, certifications, projects, languages)
    return {
        "version": DRAFT_VERSION,
        "parserVersion": PARSER_VERSION,
        "source": "json_resume",
        "fileName": "",
        "rawText": raw,
        "headline": headline,
        "summary": summary,
        "basicProfile": basic,
        "parsedData": {
            "skills": skills, "projects": projects, "education": education, "workExperience": workline, "certifications": certifications,
            "experienceDetail": entries, "educationDetail": education_detail, "competencyGroups": groups,
        },
        "languages": languages,
        "links": links,
        "confidence": confidence,
        "unplaced": [],
        "ignored": ignored,
        "warnings": warnings,
    }


def _render(basic, headline, links, summary, entries, education, skills, certifications, projects, languages) -> str:
    """A plain text CV from what was read, kept with the My CVs entry (the JSON itself is not stored)."""
    out: list[str] = [basic.get("fullName", ""), headline, " | ".join(p for p in (basic.get("email", ""), basic.get("phone", ""), basic.get("location", "")) if p), *links]
    out = [l for l in out if l]
    if summary:
        out += ["", "Summary", summary]
    if entries:
        out += ["", "Experience"]
        for e in entries:
            out.append(" — ".join(p for p in (e["title"], e["company"]) if p))
            period = " – ".join(p for p in (e["start"], e["end"]) if p)
            if period or e["location"]:
                out.append(" | ".join(p for p in (period, e["location"]) if p))
            if e["description"]:
                out.append(e["description"])
            out += [f"- {b}" for b in e["bullets"]]
    for title, items in (("Education", education), ("Skills", [", ".join(skills)] if skills else []), ("Certifications", certifications), ("Projects", projects)):
        if items:
            out += ["", title, *items]
    if languages:
        out += ["", "Languages", ", ".join(f"{l['language']} ({l['proficiency']})" if l["proficiency"] else l["language"] for l in languages)]
    return "\n".join(out)
