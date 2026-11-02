"""Truth/provenance safety audit for generated assets."""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESUME_GEN = SCRIPT_DIR.parent / "resume_generator"
if str(RESUME_GEN) not in sys.path:
    sys.path.insert(0, str(RESUME_GEN))

from provenance_checker import build_canonical_facts, check_provenance, metric_in_fact  # noqa: E402

COMPANY_RE = re.compile(
    r"(?:at|@)\s+([A-Z][A-Za-z0-9&.\-\s]{2,40})(?:\s*[,–-]|\s*\n)",
)
DEGREE_RE = re.compile(
    r"\b(B\.?S\.?|M\.?S\.?|MBA|Ph\.?D|Bachelor|Master|Doctorate)"
    r"[^.\n]{0,80}",
    re.I,
)
CERT_RE = re.compile(
    r"\b(certified|certification|certificate)\b[^.\n]{0,80}",
    re.I,
)
# The whole number ("1.5%", "1,000 users"), so that a metric is compared as one token.
METRIC_RE = re.compile(
    r"\b\d+(?:[.,]\d+)*(?:%|\+?\s*(?:years?|users|customers)\b)",
    re.I,
)
YEARS_RE = re.compile(r"(\d+)\+?\s*years?", re.I)


def _known_companies(profile: dict, intelligence: dict) -> set[str]:
    known: set[str] = set()
    raw = (profile.get("resume") or {}).get("rawText") or ""
    for line in raw.splitlines():
        if "—" in line or " - " in line:
            parts = re.split(r"[—\-]", line, maxsplit=1)
            if parts:
                known.add(parts[0].strip().lower())
    for item in (intelligence.get("experienceMap") or {}).get("domainsWorkedIn") or []:
        known.add(str(item).lower())
    return known


def _certification_names(profile: dict) -> set[str]:
    """The profile's own certification list: such a name is a certification even without the word "certified"."""
    parsed = (profile.get("resume") or {}).get("parsedData") or {}
    return {item.strip().lower() for item in parsed.get("certifications") or [] if isinstance(item, str) and item.strip()}


def _metric_supported(metric: str, facts: set[str]) -> bool:
    if any(metric_in_fact(metric).search(f) for f in facts):
        return True
    # experienceYears is a bare number ("12", "12+"); it does state "12 years", and only that.
    years = YEARS_RE.fullmatch(metric)
    return bool(years) and any(f.rstrip("+") == years.group(1) for f in facts)


def _names_the_claim(fact: str, keyword: str) -> bool:
    """A fact can back a longer claim only if it names the degree or certification, and more than the word itself."""
    if not re.search(r"(?<!\w)" + re.escape(keyword), fact):
        return False
    return len(re.sub(r"\W", "", fact)) > len(re.sub(r"\W", "", keyword))


def _claim_supported(match: re.Match, content: str, facts: set[str], names: set[str] = frozenset()) -> bool:
    """The claim inside a fact, or a fact inside the claim, on word boundaries. A short or unrelated fact never counts."""
    claim = match.group(0).lower().rstrip()
    keyword = match.group(1).lower()
    # The regex stops at 80 characters, possibly inside a word; the rest of that word is not known to differ.
    next_char = content[match.end():match.end() + 1]
    cut_mid_word = len(claim) == len(match.group(0)) and next_char.isalnum() and claim[-1:].isalnum()
    inside_fact = re.compile(r"(?<!\w)" + re.escape(claim) + ("" if cut_mid_word else r"(?!\w)"))
    if any(inside_fact.search(f) for f in facts):
        return True
    return any(
        re.search(r"(?<!\w)" + re.escape(f) + r"(?!\w)", claim)
        for f in facts | names
        if f in names or _names_the_claim(f, keyword)
    )


def audit_provenance(
    content: str,
    profile: dict,
    intelligence: dict,
) -> dict:
    facts = build_canonical_facts(profile, intelligence)
    passed, metric_issues = check_provenance(content, facts)
    issues: list[str] = list(metric_issues)
    severe: list[str] = []

    known_companies = _known_companies(profile, intelligence)
    for match in COMPANY_RE.finditer(content):
        company = match.group(1).strip()
        cl = company.lower()
        if cl and not any(cl in k or k in cl for k in known_companies):
            if len(company) > 3 and company not in ("HR", "IT"):
                issues.append(f"Unknown company reference: {company}")
                severe.append(f"Unknown company: {company}")

    for match in DEGREE_RE.finditer(content):
        if not _claim_supported(match, content, facts):
            issues.append(f"Unverified degree claim: {match.group(0)[:60]}")
            severe.append(f"Unverified degree: {match.group(0)[:40]}")

    certification_names = _certification_names(profile)
    for match in CERT_RE.finditer(content):
        if not _claim_supported(match, content, facts, certification_names):
            issues.append(f"Unverified certification: {match.group(0)[:60]}")

    for match in METRIC_RE.finditer(content):
        snippet = match.group(0).lower()
        if not _metric_supported(snippet, facts):
            if snippet not in [i.lower() for i in metric_issues]:
                issues.append(f"Unsupported metric: {match.group(0)}")

    safe = len(severe) == 0 and passed
    return {
        "provenanceSafe": safe,
        "provenanceStatus": "approved" if safe else "needs_review",
        "provenanceIssues": issues[:20],
        "severeProvenanceIssues": severe[:10],
        "severeCount": len(severe),
    }
