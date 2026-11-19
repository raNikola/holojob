"""Experiment B: one AI call per ad that returns a professional-fit number 0-100. EVALUATION ONLY, scratch gate, never the production scoring path.

Pre-registered in ~/holojob-eval/exp-b-plan.md (sha256 beside it). Scoring rule exception: .claude/rules/scoring.md, "Experiment B". Nothing in
python/job_scoring imports this module; no row of scored_jobs.json is written; the owner runs every paid step.

What is sent per ad (privacy-inventory.md, "Experiment B"): the public ad text (title and HTML-stripped description) and the candidate summary at the
plan's scope. Never sent: name, contacts, links, locations, salary, languages, labels, applications, notes, company, confirmed facts.
Every request passes redact.py with the profile's identity and a final find_leaks check; it fails closed.

    python scripts/measure_fit_b.py summary --scope public_cv        # build and hash the candidate summary (counts only)
    python scripts/measure_fit_b.py estimate ...                      # builds every request, scans it, prices it; sends nothing
    python scripts/measure_fit_b.py run ... --max-usd N --confirm     # PAID; owner only
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "job_scoring"))
import profile_enrichment  # noqa: E402

PROMPT_VERSION = 1
SUMMARY_VERSION = 1
FEATURE = "fit-b-experiment"
SCOPES = ("public_cv", "public_cv_plus_confirmed_C")
MAX_AD_CHARS = 16000  # same cut as the embedding experiment; an ad over it is truncated and counted

SCHEMA = {
    "name": "fit_b_rating",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["score", "must_haves", "domain_experience", "seniority", "reason"],
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "must_haves": {
                "type": "array", "maxItems": 8,
                "items": {"type": "object", "additionalProperties": False, "required": ["requirement", "status"], "properties": {
                    "requirement": {"type": "string", "maxLength": 140},
                    "status": {"type": "string", "enum": ["met", "partial", "unmet", "unclear"]},
                }},
            },
            "domain_experience": {"type": "string", "enum": ["direct", "transferable", "none", "unclear"]},
            "seniority": {"type": "string", "enum": ["below", "match", "above", "unclear"]},
            "reason": {"type": "string", "maxLength": 240},
        },
    },
}

PROMPT = """You rate how well one candidate fits one job ad on PROFESSIONAL grounds only. Reply with one JSON object that follows the schema.

Judge only these, using the candidate summary and the ad text below and nothing else:
1. Responsibilities: how closely the work the ad describes matches what the candidate has done.
2. Must-have requirements: list the ad's must-have requirements (at most 8, shortest wording). Mark each met, partial, unmet or unclear against the
   summary. Every unmet must-have lowers the score by the same step: do not weigh one more than another, and do not forgive one because the rest is strong.
3. Transferable skills: relevant skills from other work count, less than direct experience.
4. Domain experience: direct (the same industry or product area), transferable, none, or unclear.
5. Seniority: whether the candidate's level is below, matches or is above what the ad asks.

Do NOT consider location, work authorization or visa, languages, security clearance, salary, company reputation or the candidate's wishes: other checks handle them.
If the summary does not show something, it is unclear or unmet, never assumed.
The score is an integer 0-100: 100 = every must-have met with direct experience at the right level; 0 = nothing in common.

CANDIDATE SUMMARY
{summary}

JOB AD
Title: {title}
{description}
"""


def _plain(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(text or "")))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def ad_text(job: dict) -> tuple[str, str, bool]:
    """(title, description, truncated): public ad text only. No company, no location, no URL."""
    description = _plain(job.get("description"))
    return _plain(job.get("title")), description[:MAX_AD_CHARS], len(description) > MAX_AD_CHARS


def _lines(items) -> list[str]:
    return [_plain(i) for i in items or [] if isinstance(i, str) and _plain(i)]


def summary_sections(scope: str, profile: dict, intelligence: dict, enrichment: dict | None = None) -> dict:
    """The candidate summary as ordered sections. P-pub: what the CV shows (role, level, years, summary, experience without employer names, skills,
    certifications). P-full: P-pub plus the domains and capabilities of the owner's confirmed history entries, and the profile enrichment
    (domain and history entries and experience boundaries, owner decision 2026-11-19; employer names masked as "[employer]"). Field list = the plan's table."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    basic = profile.get("basicProfile") or {}
    parsed = (profile.get("resume") or {}).get("parsedData") or {}
    out = {
        "Current role": [_plain(basic.get("currentRole"))],
        "Seniority": [_plain((intelligence.get("candidateSummary") or {}).get("seniorityLevel"))],
        "Years of experience": [_plain(basic.get("experienceYears"))],
        "Summary": [_plain(parsed.get("summary"))],
        "Skills": _lines(parsed.get("skills")),
        "Certifications": _lines(parsed.get("certifications")),
    }
    experience = []
    for entry in parsed.get("experienceDetail") or []:
        if not isinstance(entry, dict):
            continue
        head = " - ".join(p for p in (_plain(entry.get("title")), f"{_plain(entry.get('start'))} to {_plain(entry.get('end'))}") if p)
        experience.append(head + ("\n" + "\n".join("  * " + b for b in _lines(entry.get("bullets"))) if entry.get("bullets") else ""))
    out["Experience"] = experience
    if scope == "public_cv_plus_confirmed_C":
        confirmed = []
        for entry in intelligence.get("historyEntries") or []:
            if isinstance(entry, dict) and (entry.get("domains") or entry.get("capabilities")):
                confirmed.append(f"{_plain(entry.get('role'))}: domains {', '.join(_lines(entry.get('domains'))) or '-'}; "
                                 f"capabilities {', '.join(_lines(entry.get('capabilities'))) or '-'}")
        out["Confirmed domains and capabilities"] = confirmed
        data = profile_enrichment.normalize(enrichment)
        employers = sorted(data["employers"], key=len, reverse=True)

        def masked(text: str) -> str:
            for name in employers:
                text = re.sub(re.escape(name), "[employer]", text, flags=re.IGNORECASE)
            return _plain(text)

        out["Domain experience"] = [f"{masked(d['title'])}: {masked(d['text'])}" for d in data["domains"]]
        out["Work history detail"] = [f"{masked(h['role'])} ({masked(h['period'])}): {masked(h['text'])}" for h in data["history"]]
        out["Experience boundaries"] = [masked(b["text"]) for b in data["boundaries"]]
    return {k: [x for x in v if x] for k, v in out.items() if any(v)}


def render_summary(sections: dict) -> str:
    return "\n".join(f"{name}:\n" + "\n".join(("  " + line) if "\n" not in line else line for line in lines) for name, lines in sections.items())


def build_summary(scope: str, profile: dict, intelligence: dict, identity: tuple[str, list[str]], enrichment: dict | None = None) -> dict:
    """{"scope","version","text","sha256","counts"}: redacted, leak-checked (raises on a leak: fail closed). Counts only, no values, in `counts`."""
    from redact import find_leaks, redact_cv_text
    sections = summary_sections(scope, profile, intelligence, enrichment)
    text, removed = redact_cv_text(render_summary(sections), identity[0], identity[1])
    leaks = find_leaks(text, identity[0], identity[1])
    if leaks:
        raise ValueError("summary still holds " + ", ".join(leaks) + "; nothing is built")
    return {"scope": scope, "version": SUMMARY_VERSION, "promptVersion": PROMPT_VERSION, "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "counts": {"sections": {k: len(v) for k, v in sections.items()}, "chars": len(text), "redacted": removed}}


def public_cv_coverage(summary_text: str, public_cv_text: str) -> dict:
    """Which summary lines have no support in the public CV text (token overlap, offline). Counts and line numbers only; P-pub is meant to be 0 unsupported."""
    cv_tokens = set(re.findall(r"[a-z0-9]{3,}", public_cv_text.lower()))
    unsupported = []
    for n, line in enumerate(summary_text.splitlines(), 1):
        tokens = re.findall(r"[a-z0-9]{3,}", line.lower())
        if tokens and sum(t in cv_tokens for t in tokens) / len(tokens) < 0.6:
            unsupported.append(n)
    return {"lines": len(summary_text.splitlines()), "unsupportedLines": unsupported}


def build_prompt(summary: dict, job: dict, identity: tuple[str, list[str]] = ("", [])) -> str:
    """The request. The ad text goes through redact.py too (a recruiter's e-mail or phone in the ad is third-party data and trips the scan otherwise)."""
    from redact import redact_cv_text
    title, description, _ = ad_text(job)
    title, description = (redact_cv_text(t, identity[0], identity[1])[0] for t in (title, description))
    return PROMPT.format(summary=summary["text"], title=title, description=description)


def request_key(summary: dict, job: dict) -> str:
    """Cache key of one rating: the ad text, the summary hash, the prompt version."""
    title, description, _ = ad_text(job)
    return hashlib.sha256(f"{PROMPT_VERSION}|{summary['sha256']}|{title}|{description}".encode("utf-8")).hexdigest()[:32]


def valid_rating(out) -> dict | None:
    """The reply if it follows the schema's shape, else None (validated in code whatever the provider enforced)."""
    if not isinstance(out, dict):
        return None
    score = out.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        return None
    if out.get("domain_experience") not in SCHEMA["schema"]["properties"]["domain_experience"]["enum"]:
        return None
    if out.get("seniority") not in SCHEMA["schema"]["properties"]["seniority"]["enum"]:
        return None
    musts = out.get("must_haves")
    if not isinstance(musts, list) or len(musts) > 8 or not all(isinstance(m, dict) and m.get("status") in ("met", "partial", "unmet", "unclear") for m in musts):
        return None
    return out


def write_private_json(path: Path, data) -> None:
    from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic
    make_private_dirs(path.parent)
    write_text_atomic(path, json.dumps(data, indent=1, ensure_ascii=False), PRIVATE_FILE_MODE)
