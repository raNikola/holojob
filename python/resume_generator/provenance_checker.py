"""Verify resume content traces to candidate profile/intelligence only."""

from __future__ import annotations

import re

# The whole number ("1.5%", "1,000 users") and the whole unit word ("5 xylophones"), so that a metric is compared as
# one token. Finds a metric in the same places as a plain number and unit would; only the matched text is longer.
METRIC_RE = re.compile(r"\b\d+(?:[.,]\d+)*(?:%|\s*(?:users|customers|ms|x)\w*|\s*[km]\b)", re.I)


def build_canonical_facts(profile: dict, intelligence: dict) -> set[str]:
    facts: set[str] = set()
    basic = profile.get("basicProfile") or {}
    for v in basic.values():
        if isinstance(v, str) and v.strip():
            facts.add(v.strip().lower())

    resume = profile.get("resume") or {}
    parsed = resume.get("parsedData") or {}
    for key in ("skills", "projects", "education", "workExperience", "certifications"):
        for item in parsed.get(key) or []:
            if isinstance(item, str) and item.strip():
                facts.add(item.strip().lower())

    raw = resume.get("rawText") or ""
    for line in raw.splitlines():
        line = line.strip()
        if len(line) > 4:
            facts.add(line.lower())

    exp_map = intelligence.get("experienceMap") or {}
    for key in ("projectHighlights", "ownershipExamples", "leadershipExamples", "businessImpactExamples"):
        for item in exp_map.get(key) or []:
            if isinstance(item, str) and item.strip():
                facts.add(item.strip().lower())

    skills_map = intelligence.get("skillsMap") or {}
    for items in skills_map.values():
        if isinstance(items, list):
            for s in items:
                if str(s or "").strip():
                    facts.add(str(s).strip().lower())

    return facts


def metric_in_fact(metric: str) -> re.Pattern[str]:
    """A metric as a whole token: 50% is not in 150% or 1.50%, 10m is not in 10ms. A letter before it changes no number."""
    after = "" if metric.endswith("%") else r"(?!\w)"
    return re.compile(r"(?<!\d)(?<!\d[.,])" + re.escape(metric) + after)


def check_provenance(content: str, facts: set[str]) -> tuple[bool, list[str]]:
    """Return (passed, issues). Flags metrics not found in source facts.

    Only a fact that states the metric can vouch for it. A fact inside the metric never does: years of experience "5"
    say nothing about 5% or 500%, and a skill "R" says nothing about 870 users.
    """
    issues: list[str] = []
    for match in METRIC_RE.finditer(content):
        pattern = metric_in_fact(match.group(0).lower())
        if not any(pattern.search(f) for f in facts):
            issues.append(f"Unverified metric or number: {match.group(0)}")

    return len(issues) == 0, issues
