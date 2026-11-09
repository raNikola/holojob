"""LLM content generation via local Claude Code (no API key).

Claude drafts the variable content (Parts 4-5 of HOLOJOB_GENERATION_CONTEXT.md):
subtitle, summary, bullet rewrites/ordering, skills ordering, optional projects,
and the 4 cover letter paragraphs. Output is structurally validated here and
fact-checked (provenance + cliché lint) by the caller before acceptance.
Styling never goes near the LLM — templates stay fixed.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "llm"))
# Appended: other python folders have modules of the same name as the ones here.
if str(ROOT / "python" / "cv_analysis") not in sys.path:
    sys.path.append(str(ROOT / "python" / "cv_analysis"))

import claude_code  # noqa: E402
import redact  # noqa: E402

PROJECT_INTEL_PATH = ROOT / "data/intelligence/project-intelligence.json"

PROMPT_TEMPLATE = """You are the resume/cover-letter tailoring engine of a Holojob. \
You receive a job description and verified candidate data. Produce tailored CONTENT only \
— styling is handled elsewhere.

## HARD RULES (violations make the output unusable)
- Every claim must trace to the CANDIDATE DATA below. NEVER invent metrics, numbers, \
employers, titles, dates, or technologies. Copy numbers and proper nouns verbatim \
(e.g. "40% faster releases", "3 production launches").
- Mirror the JD's exact phrasing only where the candidate genuinely has the skill; \
skip JD keywords the candidate cannot support.
- Banned phrases: passionate, team player, fast-paced environment, results-driven, \
go-getter, think outside the box, self-starter, dynamic, synergy.
- Resume experience: reorder/reword the given bullets to put JD-relevant ones first \
and mirror JD vocabulary. Keep every metric verbatim. 4-6 bullets for recent roles, \
2 for short stints. Do not add bullets with facts not present in the data.
- Cover letter: exactly 4 paragraphs, 330-420 words total. P1 = hook naming the exact \
role + company, leading with the strongest quantified credential, ending with a bridge \
to the company's domain. P2 = deep-dive of the most relevant role weaving the JD's top \
keywords into real accomplishments, ending with a lesson tied to a JD value. \
P3 = breadth from an earlier role + one differentiator the JD cares about. \
P4 = 2-3 sentences mapping 3-4 JD keywords to candidate skills, request the \
conversation, thank them. Confident, concrete, no clichés.
- projects: include at most 2, ONLY if genuinely relevant to this JD; one factual line \
each drawn from the PROJECT INTELLIGENCE data. Empty array if none are relevant.

## JOB
Title: {title}
Company: {company}
Location: {location}
Description:
{description}

## CANDIDATE DATA (the only source of truth)
Parsed resume:
{parsed_resume}

Intelligence summary:
{intelligence}

Project intelligence:
{project_intel}

## OUTPUT
Return ONLY a JSON object, no prose, with exactly this shape:
{{
  "subtitle": "<role-echoing tagline, e.g. 'Senior Software Engineer | Backend, Cloud & Distributed Systems'>",
  "summary": "<3 sentences: experience framing -> candidate∩JD tech stack -> specialization matching JD themes>",
  "experience": [{{"company": "<exact company name from data>", "bullets": ["<reordered/reworded bullets>"]}}],
  "skills": [{{"label": "<category>", "skills": ["<items, JD-relevant first>"]}}],
  "projects": [{{"name": "<project>", "line": "<one factual line>"}}],
  "cover_letter_paragraphs": ["<P1>", "<P2>", "<P3>", "<P4>"]
}}"""


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(text or ""))


def load_project_intelligence() -> dict:
    if PROJECT_INTEL_PATH.exists():
        try:
            return json.loads(PROJECT_INTEL_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


# What redact.py leaves in the text in place of a name, e-mail, phone number or link. A draft that has one in it
# copied a placeholder instead of writing a sentence, and would print "[NAME]" in a document.
PLACEHOLDER_RE = re.compile(r"\[(?:NAME|EMAIL|PHONE|LINK)\]")


def _identity(parsed: dict) -> tuple[str, list[str]]:
    """The name and links of the candidate as the parser read them: what redact.py needs besides its patterns."""
    name = str(parsed.get("name") or "").strip()
    if name.lower() == "candidate":  # the parser's stand-in when the CV has no name
        name = ""
    links = [str(l).strip() for l in parsed.get("links") or [] if str(l or "").strip()]
    return name, links


def _redact_tree(value, name: str, links: list[str]):
    """The same structure with every text redacted (keys are ours and stay)."""
    if isinstance(value, str):
        return redact.redact_cv_text(value, name, links)[0]
    if isinstance(value, list):
        return [_redact_tree(v, name, links) for v in value]
    if isinstance(value, dict):
        return {k: _redact_tree(v, name, links) for k, v in value.items()}
    return value


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _texts(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)


def _is_text_or_none(value) -> bool:
    return value is None or isinstance(value, str)


def _entries(data: dict, key: str, issues: list[str]) -> list[dict]:
    """The objects under `key`; anything else there is recorded as an issue. Absent or null is an empty section."""
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        issues.append(f"{key} must be a list")
        return []
    if not all(isinstance(entry, dict) for entry in value):
        issues.append(f"{key} entries must be objects")
    return [entry for entry in value if isinstance(entry, dict)]


def _validate(data: dict, parsed: dict) -> list[str]:
    """Structural checks before the caller's provenance/lint gates."""
    issues = []
    if any(PLACEHOLDER_RE.search(t) for t in _texts(data)):
        issues.append("draft contains a redaction placeholder")
    if not isinstance(data.get("subtitle"), str) or not data["subtitle"].strip():
        issues.append("missing subtitle")
    if not isinstance(data.get("summary"), str) or len(data["summary"]) < 80:
        issues.append("missing/short summary")
    paras = data.get("cover_letter_paragraphs")
    if not isinstance(paras, list) or len(paras) != 4 or not all(isinstance(p, str) and p.strip() for p in paras):
        issues.append("cover letter must be exactly 4 non-empty paragraphs")
    known_companies = {(e.get("company") or "").strip().lower() for e in parsed.get("experience") or []}
    for entry in _entries(data, "experience", issues):
        company = entry.get("company")
        if not _is_text_or_none(company) or (company or "").strip().lower() not in known_companies:
            issues.append(f"unknown company in experience: {company}")
        bullets = entry.get("bullets")
        if not bullets:
            issues.append(f"empty bullets for {company}")
        elif not isinstance(bullets, list):
            issues.append(f"bullets for {company} must be a list")
        elif not all(isinstance(b, str) for b in bullets):
            issues.append(f"bullets for {company} must be text")
    for entry in _entries(data, "skills", issues):
        items = entry.get("skills")
        if not _is_text_or_none(entry.get("label")):
            issues.append("skills label must be text")
        if items is not None and not (isinstance(items, list) and all(isinstance(s, str) for s in items)):
            issues.append("skills items must be a list of text")
    for entry in _entries(data, "projects", issues):
        if not _is_text_or_none(entry.get("name")) or not _is_text_or_none(entry.get("line")):
            issues.append("project name and line must be text")
    return issues


def build_prompt(parsed: dict, intelligence: dict, job: dict) -> tuple[str | None, str]:
    """(prompt, '') or (None, reason). Every text that goes in is redacted first (name, e-mails, phones, links, with the
    name and links the parser read), and a final check on the redacted texts fails closed: if anything of the candidate's
    is left, nothing is built and so nothing is sent."""
    name, links = _identity(parsed)

    def clean(value):
        return _redact_tree(value, name, links)

    intel_slim = {
        "candidateSummary": intelligence.get("candidateSummary"),
        "skillsMap": intelligence.get("skillsMap"),
        "experienceMap": intelligence.get("experienceMap"),
        "atsKeywordBank": (intelligence.get("atsKeywordBank") or {}).get("highPriority"),
    }
    project_intel = load_project_intelligence()
    project_slim = {
        "aggregate": project_intel.get("aggregate"),
        "projects": [
            {k: p.get(k) for k in ("name", "summary", "domain", "techStack", "quantifiables", "highlights")}
            for p in project_intel.get("projects") or []
        ],
    } if project_intel else "none available"

    sent = {
        "title": clean(job.get("title") or ""),
        "company": clean(job.get("company") or ""),
        "location": clean(job.get("location") or ""),
        "description": clean(_strip_html(job.get("description") or "")[:5000]),
        "parsed_resume": clean({k: parsed.get(k) for k in ("about_me", "experience", "skill_categories", "education")}),
        "intelligence": clean(intel_slim),
        "project_intel": clean(project_slim),
    }
    leaks = redact.find_leaks("\n".join(_texts(sent)), name, links)
    if leaks:
        return None, f"personal details could not be removed ({', '.join(leaks)}), so nothing was sent"

    return PROMPT_TEMPLATE.format(
        title=sent["title"],
        company=sent["company"],
        location=sent["location"],
        description=sent["description"],
        parsed_resume=json.dumps(sent["parsed_resume"], ensure_ascii=False, indent=1),
        intelligence=json.dumps(sent["intelligence"], ensure_ascii=False, indent=1),
        project_intel=json.dumps(sent["project_intel"], ensure_ascii=False, indent=1)
        if isinstance(sent["project_intel"], dict) else sent["project_intel"],
    ), ""


NOT_CONFIRMED = "not confirmed: the redacted text was not approved for sending, so nothing was sent"


def generate_llm_content(parsed: dict, intelligence: dict, job: dict, *, confirmed: bool = False) -> tuple[dict | None, str]:
    """Returns (content, '') or (None, reason). Caller must fact-check before use.

    Sends nothing unless `confirmed` is True: the owner approved what `build_prompt` returns (the preview shows exactly it)."""
    if confirmed is not True:
        return None, NOT_CONFIRMED
    if not claude_code.is_available():
        return None, claude_code.availability()["reason"]

    prompt, refused = build_prompt(parsed, intelligence, job)
    if prompt is None:
        return None, refused

    with claude_code.ai_gate.context(feature="tailoring", job_id=job.get("jobId")):
        data, err = claude_code.complete_json(prompt, timeout=300)
    if data is None:
        name, links = _identity(parsed)
        return None, redact.redact_cv_text(err, name, links)[0]
    issues = _validate(data, parsed)
    if issues:
        return None, "; ".join(issues)
    return data, ""
