"""Cover letter, composed from the candidate's own words.

A rule-based letter states only what the candidate wrote: their career summary
from the questionnaire (else the CV summary), and their CV bullets, quoted whole
as a list. Around them sit four fixed sentences that claim nothing about the
candidate: the application line, the two role lead-ins built from profile
fields, and the thank-you. The job ad decides which bullets come first; it never
supplies words. A thin profile gives a short letter, never a padded one.

An LLM-drafted letter (paragraphs_override) is used as given: run_tailor only
accepts it after the provenance and lint checks.
"""

from __future__ import annotations

from datetime import date

from candidate_text import BANNED_PHRASES, banned_phrases_in, narrative_answer, own_sentences
from template_engine import render_cover_letter_html, render_cover_letter_md

# How much of the candidate's material each part of the letter takes.
OPENING_SENTENCES = 2
CURRENT_ROLE_BULLETS = 3
EARLIER_ROLE_BULLETS = 2

THANK_YOU = "Thank you for considering my application."

__all__ = [
    "BANNED_PHRASES",
    "build_cover_letter_context",
    "generate_cover_letter",
    "generate_cover_letter_html",
    "lint_cover_letter",
]


def _application_line(job: dict) -> str:
    title = (job.get("title") or "").strip()
    company = (job.get("company") or "").strip()
    role = f"the {title} role" if title else "this role"
    return f"I am applying for {role} at {company}." if company else f"I am applying for {role}."


def _lead_in(entry: dict, first: bool) -> str:
    """'At ACME, where I work as Lead:' from profile fields only."""
    title = (entry.get("title") or "").strip()
    company = (entry.get("company") or "").strip()
    if first:
        dates = (entry.get("dates") or "").lower()
        verb = "work" if any(w in dates for w in ("present", "current", "now", "ongoing")) else "worked"
        if title and company:
            return f"At {company}, where I {verb} as {title}:"
        return f"At {company}:" if company else (f"As {title}:" if title else "")
    if title and company:
        return f"Before that, as {title} at {company}:"
    return f"Before that, at {company}:" if company else (f"Before that, as {title}:" if title else "Before that:")


def _build_paragraphs(profile: dict, resume_ctx: dict, job: dict) -> tuple[list[dict], list[str]]:
    """Letter blocks ({text, bullets}) and the gaps that kept it short."""
    warnings: list[str] = []

    opening = own_sentences(narrative_answer(profile), OPENING_SENTENCES)
    if not opening:
        opening = own_sentences(resume_ctx.get("about_me") or resume_ctx.get("summary") or "", OPENING_SENTENCES)
    if not opening:
        warnings.append(
            "cover letter: no career summary in the questionnaire or the CV, so the opening is one sentence"
        )
    blocks = [{"text": " ".join([_application_line(job), *opening]), "bullets": []}]

    # The CV's bullets for each role, in the CV's job-relevance order, so the
    # letter and the CV agree. No bullet appears twice.
    used: set[str] = set()
    roles = [entry for entry in resume_ctx.get("experience") or [] if entry.get("bullets")]
    for index, (entry, limit) in enumerate(zip(roles, (CURRENT_ROLE_BULLETS, EARLIER_ROLE_BULLETS))):
        bullets = [b for b in entry["bullets"] if b not in used and not banned_phrases_in(b)][:limit]
        if bullets:
            used.update(bullets)
            blocks.append({"text": _lead_in(entry, first=index == 0), "bullets": bullets})
    if len(blocks) == 1:
        warnings.append("cover letter: no experience bullets to quote, so the letter has no evidence paragraphs")

    blocks.append({"text": THANK_YOU, "bullets": []})
    return blocks, warnings


def _flatten(paragraphs: list) -> list[str]:
    """Each paragraph as plain text: a block's text followed by its bullets."""
    flat = []
    for p in paragraphs:
        if isinstance(p, dict):
            flat.append(" ".join(filter(None, [p.get("text") or "", *(p.get("bullets") or [])])))
        else:
            flat.append(str(p))
    return flat


def lint_cover_letter(paragraphs: list) -> list[str]:
    """Part 4 checks: no clichés (in any inflection), 4 paragraphs, ~330–420 words.

    For an LLM draft these decide whether it is accepted. For a rule-based letter
    they are a report: a short letter from a thin profile is not padded to pass.
    """
    flat = _flatten(paragraphs)
    text = " ".join(flat)
    issues = [f"Banned cliché: '{phrase}'" for phrase in banned_phrases_in(text)]
    words = len(text.split())
    if not 250 <= words <= 500:
        issues.append(f"Word count {words} outside acceptable range (target 330–420)")
    if len(flat) != 4:
        issues.append(f"Expected 4 paragraphs, got {len(flat)}")
    return issues


def build_cover_letter_context(
    profile: dict,
    intelligence: dict,
    job: dict,
    resume_ctx: dict,
    paragraphs_override: list[str] | None = None,
) -> dict:
    if paragraphs_override:
        blocks, warnings = [{"text": p, "bullets": []} for p in paragraphs_override], []
    else:
        blocks, warnings = _build_paragraphs(profile, resume_ctx, job)

    company = job.get("company") or "the company"
    location = job.get("location") or ""
    addressee = ["Hiring Team", company]
    if location:
        addressee.append(location)

    name = resume_ctx.get("name") or (profile.get("basicProfile") or {}).get("fullName") or "Candidate"
    return {
        "name": name,
        "subtitle": resume_ctx.get("subtitle") or "",
        "contact_items": resume_ctx.get("contact_items") or [],
        "date_long": f"{date.today().strftime('%B')} {date.today().day}, {date.today().year}",
        "addressee_lines": addressee,
        "salutation": "Dear Hiring Team,",
        "paragraphs": blocks,
        "signature_name": name.title() if name.isupper() else name,
        "lint_issues": lint_cover_letter(blocks),
        "warnings": warnings,
    }


def generate_cover_letter(profile: dict, intelligence: dict, job: dict, resume_ctx: dict | None = None) -> str:
    """Markdown version (kept for the dashboard preview)."""
    if resume_ctx is None:
        from resume_tailor import build_resume_context

        resume_ctx = build_resume_context(profile, intelligence, job)
    ctx = build_cover_letter_context(profile, intelligence, job, resume_ctx)
    return render_cover_letter_md(ctx)


def generate_cover_letter_html(ctx: dict) -> str:
    return render_cover_letter_html(ctx)
