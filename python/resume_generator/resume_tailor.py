"""Truth-only resume tailoring from profile + intelligence + job."""

from __future__ import annotations

import html
import re

from candidate_text import narrative_answer, own_sentences
from profile_languages import languages_text, normalize_languages
from resume_parser import education_problem, parse_resume_from_profile, skill_label
from text_utils import normalize_text


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(text or ""))


def _jd_keywords(job: dict, intelligence: dict, limit: int = 15) -> list[str]:
    bank = intelligence.get("atsKeywordBank") or {}
    high = list(bank.get("highPriority") or [])
    matched = list(job.get("matchedSkills") or [])
    jd_text = normalize_text(_strip_html(job.get("description", "")))
    keywords = []
    for kw in matched + high:
        if kw and kw.lower() in jd_text:
            keywords.append(kw)
        elif kw in matched:
            keywords.append(kw)
        if len(keywords) >= limit:
            break
    return keywords[:limit] or matched[:10] or high[:10]


def _candidate_summary(about: str, profile: dict) -> str:
    """The candidate's own summary, as written.

    Rule-based tailoring does not write a summary for them: any sentence it
    composed would state things the candidate never said. It is the summary
    section of their CV, else their questionnaire career summary read from the
    profile, else empty, and the context then warns. The intelligence file's
    careerNarrative is not used: without that answer the engine fills it from a
    template or a "pending" placeholder. Sentences with a banned phrase are left
    out, never edited.
    """
    for source in (about, narrative_answer(profile)):
        sentences = own_sentences(source)
        if sentences:
            return " ".join(sentences)
    return ""


# Part 5: "4-6 bullets for recent roles". The most recent roles get the most room.
BULLET_CAPS = (6, 5, 4)


def _tailor_bullets(
    bullets: list[str], keywords: list[str], canonical_skills: set[str], limit: int | None = None
) -> list[str]:
    """Part 5: the JD-relevant bullets first, as many as the role has room for.

    Bullets are picked and ordered, never rewritten: metrics and facts stay as the
    candidate wrote them.
    """
    if not bullets:
        return bullets
    kw_lower = [k.lower() for k in keywords]

    def relevance(bullet: str) -> int:
        b = bullet.lower()
        return sum(1 for kw in kw_lower if kw in b)

    ordered = sorted(bullets, key=relevance, reverse=True)
    return ordered[:limit] if limit else ordered


def _tailor_skill_categories(
    categories: list[dict],
    keywords: list[str],
    parsed_skills: list[str],
) -> list[dict]:
    """Reorder skills within categories — matched JD skills first."""
    kw_lower = [k.lower() for k in keywords]
    all_canonical = {s.lower(): s for s in parsed_skills}

    def prioritize(items: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def add(item: str) -> None:
            key = item.lower().replace(".js", "").replace(" ", "")
            if key not in seen:
                ordered.append(item)
                seen.add(key)

        for kw in keywords:
            for item in items:
                if item.lower() == kw.lower() or kw.lower() in item.lower():
                    add(item)
        for item in items:
            add(item)
        return ordered

    if not categories:
        # Build default categories from parsed skills + keywords
        langs = prioritize([s for s in parsed_skills if s in (
            "JavaScript", "Python", "Java", "SQL", "Go", "AQL",
        )] or keywords[:5])
        backend = prioritize([s for s in parsed_skills if s in (
            "Node.js", "Express", "Flask", "Django", "REST API", "Microservices",
        )])
        frontend = prioritize([s for s in parsed_skills if s in (
            "React", "Next.js", "Vue", "Flutter", "Vite",
        )])
        databases = prioritize([s for s in parsed_skills if s in (
            "PostgreSQL", "MongoDB", "MySQL",
        )])
        devops = prioritize([s for s in parsed_skills if s in (
            "AWS", "Docker", "CI/CD", "GitHub Actions", "Nginx", "Linux", "Git",
        )])
        return [
            {"label": "Programming languages", "skills": langs or keywords[:5]},
            {"label": "Backend Frameworks", "skills": backend or []},
            {"label": "Frontend Frameworks", "skills": frontend or []},
            {"label": "Databases", "skills": databases or []},
            {"label": "DevOps and Cloud", "skills": devops or []},
            {"label": "Platforms and Tools", "skills": prioritize([s for s in parsed_skills if s in ("System Design",)])},
        ]

    def _norm_key(s: str) -> str:
        return s.lower().replace(".js", "").replace(" ", "").rstrip("s")

    tailored_cats = []
    for cat in categories:
        items = prioritize(cat.get("skills") or cat.get("items") or [])
        # Add matched keywords that fit category label
        label_l = cat.get("label", "").lower()
        for kw in keywords:
            if _norm_key(kw) in {_norm_key(i) for i in items}:
                continue
            if kw.lower() not in all_canonical:
                continue
            if "language" in label_l and kw in ("JavaScript", "Python", "Java", "SQL", "Go"):
                items.insert(0, kw)
            elif "backend" in label_l and kw in ("Node.js", "Express", "Django", "Flask", "REST API"):
                items.insert(0, kw)
            elif "frontend" in label_l and kw in ("React", "Vue", "Next.js", "Flutter"):
                items.insert(0, kw)
            elif "database" in label_l and kw in ("PostgreSQL", "MySQL", "MongoDB"):
                items.insert(0, kw)
            elif "devops" in label_l or "cloud" in label_l:
                if kw in ("AWS", "Docker", "CI/CD", "GitHub Actions", "Linux"):
                    items.insert(0, kw)
        tailored_cats.append({"label": skill_label(cat["label"]), "skills": items})

    # Part 5: reorder rows so JD-critical categories appear higher (stable sort).
    def row_relevance(cat: dict) -> int:
        joined = " ".join(cat.get("skills") or []).lower()
        return sum(1 for kw in kw_lower if kw in joined)

    return sorted(tailored_cats, key=row_relevance, reverse=True)


def build_resume_context(profile: dict, intelligence: dict, job: dict) -> dict:
    parsed = parse_resume_from_profile(profile)
    basic = profile.get("basicProfile") or {}
    resume_parsed = (profile.get("resume") or {}).get("parsedData") or {}
    canonical_skills = set(resume_parsed.get("skills") or [])
    keywords = _jd_keywords(job, intelligence)

    about = _candidate_summary(parsed.get("about_me") or "", profile)

    experience = []
    for index, exp in enumerate(parsed.get("experience") or []):
        cap = BULLET_CAPS[min(index, len(BULLET_CAPS) - 1)]
        experience.append({
            **exp,
            "bullets": _tailor_bullets(exp.get("bullets") or [], keywords, canonical_skills, cap),
        })

    rows = list(parsed.get("skill_categories") or [])
    if rows:
        # The CV's own rows come first; whatever else the profile lists goes in one
        # more row, so nothing the candidate listed is dropped and nothing is added.
        shown = {s.lower() for row in rows for s in row["skills"]}
        rest = [s for s in resume_parsed.get("skills") or [] if s.lower() not in shown]
        if rest:
            rows.append({"label": "Skills", "skills": rest})
    skill_categories = _tailor_skill_categories(rows, keywords, list(canonical_skills))

    languages = normalize_languages(basic.get("languages"))

    # Whatever the profile states, and nothing else: with no readable entry the
    # templates leave the section out and the warning below tells the candidate.
    education = parsed.get("education") or {}
    warnings = []
    problem = education_problem(education)
    if problem:
        warnings.append(f"education: {problem}")

    if not about:
        warnings.append("summary: no summary could be read from the CV or the profile; the CV leaves it out")
    if not experience:
        warnings.append("experience: no work experience could be read from the CV or the profile")

    contact = parsed.get("contact") or ""
    contact_items = parsed.get("contact_items") or []

    return {
        "name": parsed.get("name") or (basic.get("fullName") or "Candidate").strip(),
        # The candidate's own headline: a tagline echoing the job's title would claim it.
        "subtitle": parsed.get("headline") or (basic.get("currentRole") or "").strip(),
        "contact": contact,
        "contact_items": contact_items,
        "email": basic.get("email") or "",
        "phone": basic.get("phone") or "",
        "location": basic.get("location") or "",
        "about_me": about,
        "summary": about,
        "experience": experience,
        "skill_categories": skill_categories,
        "education": education,
        "languages": languages,
        "languages_text": languages_text(languages),
        "warnings": warnings,
        "keywords": keywords,
        "target_title": job.get("title") or "",
        "target_company": job.get("company") or "",
        # legacy fields for md template
        "skills": keywords + [s for cat in skill_categories for s in cat.get("skills", [])][:20],
    }
