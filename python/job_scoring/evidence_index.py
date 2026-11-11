"""The candidate's evidence index: one item per piece of text their history offers.

ENGINE_CONTRACT.md sections 1.1 and 4.3. Built in code from the profile and the
intelligence, with no model call; the matcher (a later step) may cite these
items and quote them, never add to them or raise their strength.

Where each item comes from, in this order:

  * role       - the description and each bullet of `resume.parsedData.experienceDetail`. A profile
                 whose CV analysis was never applied has no experienceDetail;
                 its `workExperience` lines ("Title — Company | dates | text")
                 are read instead, one item per sentence of the text.
  * project    - `resume.parsedData.projects`, then
                 `experienceMap.projectHighlights` of the intelligence.
  * example    - `experienceMap` ownership, leadership and impact examples.
  * fact       - what is only listed: `competencyGroups` and `toolGroups`
                 entries, `parsedData.skills`, certifications and education.

Like the résumé rule, nothing is filled in: a date that cannot be read to a
month is null, a part that is missing gives no items.

Every text is passed through redact.py first (DECISIONS.md principle 14): no
name, e-mail, phone or link of the candidate reaches an evidence item, and so
none can reach a provider through one.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_CV_ANALYSIS = Path(__file__).resolve().parents[1] / "cv_analysis"
if str(_CV_ANALYSIS) not in sys.path:
    sys.path.append(str(_CV_ANALYSIS))

from redact import identity_of, redact_cv_text  # noqa: E402

SOURCES = ("role", "project", "example", "questionnaire", "fact")

# --- strength (section 4.3) -------------------------------------------------
#
# The heuristic, deliberately simple and deterministic:
#   1 claim        - a listed entry (a skill, a tool, a certificate, a degree):
#                    every `fact` item, whatever it says.
#   2 contextual   - any other text that does not open with a work verb:
#                    "Product strategy, discovery, roadmap ownership".
#   3 demonstrated - the text, or the part after a "Label:" prefix as in
#                    "RUTE INC — TMS: Led product strategy", opens with one of
#                    WORK_VERBS: something the candidate did.
#   4 outcome      - a 3 that also holds a number: 40%, 3x, 250+, 3,000, $2M,
#                    "11 people". A four-digit year (19xx/20xx) is a date, not
#                    an outcome, and does not count.
# Strength 0 is "no evidence" and is never given to an item that exists.

WORK_VERBS = frozenset(
    """
    achieved architected automated built championed coached created cut decreased defined
    delivered designed developed directed doubled drove established expanded grew hired
    implemented improved increased introduced launched led managed mentored migrated
    modernized optimized organized orchestrated owned pioneered planned prioritized
    rebuilt redesigned reduced refactored released ran scaled set shipped spearheaded
    started streamlined supervised supported transformed tripled
    """.split()
)

_LABEL_PREFIX = re.compile(r"^[^:]{1,120}:\s+")
_FIRST_WORD = re.compile(r"[A-Za-z]+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_METRIC = re.compile(r"\d")


def opens_with_work_verb(text: str) -> bool:
    for candidate in (text, _LABEL_PREFIX.sub("", text, count=1)):
        word = _FIRST_WORD.match(candidate.lstrip(" -•*–—\t"))
        if word and word.group(0).lower() in WORK_VERBS:
            return True
    return False


def has_metric(text: str) -> bool:
    return bool(_METRIC.search(_YEAR.sub("", text)))


def grade(text: str, source: str) -> int:
    if source == "fact":
        return 1
    if not opens_with_work_verb(text):
        return 2
    return 4 if has_metric(text) else 3


# --- dates -----------------------------------------------------------------

_MONTHS = {
    m: i
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
         ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
         ("oct", "october"), ("nov", "november"), ("dec", "december")],
        start=1,
    )
    for m in names
}


def to_month(value) -> str | None:
    """`YYYY-MM` from "Apr 2024", "April 2024", "2024-04" or "04/2024"; else None.

    A year alone ("2014") and "Present" are not a month and give None.
    """
    text = str(value or "").strip().lower().rstrip(".")
    if m := re.fullmatch(r"([a-z]+)\.?\s+(\d{4})", text):
        month = _MONTHS.get(m.group(1))
        return f"{m.group(2)}-{month:02d}" if month else None
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", text):
        year, month = m.group(1), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})[/.](\d{4})", text):
        year, month = m.group(2), int(m.group(1))
    else:
        return None
    return f"{year}-{month:02d}" if 1 <= month <= 12 else None


# --- sources ----------------------------------------------------------------

_DASH = re.compile(r"\s+[—–]\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _role_name(title, company) -> str | None:
    parts = [str(p).strip() for p in (title, company) if str(p or "").strip()]
    return " — ".join(parts) or None


def _split_period(period: str) -> tuple[str | None, str | None]:
    pieces = re.split(r"\s*[–—-]\s*|\s+to\s+", period.strip(), maxsplit=1)
    return to_month(pieces[0]), to_month(pieces[1]) if len(pieces) > 1 else None


def _work_experience_line(line: str) -> tuple[str | None, str | None, str | None, list[str]]:
    """(role, start, end, sentences) of a "Title — Company | dates | text" line."""
    parts = [p.strip() for p in str(line).split("|")]
    if len(parts) < 3:
        return None, None, None, [s for s in _SENTENCE_END.split(str(line).strip()) if s]
    head, period, text = parts[0], parts[1], " | ".join(parts[2:])
    title, _, company = head.partition(_DASH.search(head).group(0)) if _DASH.search(head) else (head, "", None)
    start, end = _split_period(period)
    return _role_name(title, company), start, end, [s for s in _SENTENCE_END.split(text) if s]


def _strings(value) -> list[str]:
    return [str(v).strip() for v in value if str(v or "").strip()] if isinstance(value, list) else []


def _group_items(groups) -> list[str]:
    out = []
    for group in groups if isinstance(groups, list) else []:
        if isinstance(group, dict):
            out.extend(_strings(group.get("items")))
    return out


def _raw_items(profile: dict, intelligence: dict):
    """(source, role, start, end, text) in index order, before redaction and ids."""
    parsed = ((profile.get("resume") or {}).get("parsedData")) or {}

    detail = [d for d in parsed.get("experienceDetail") or [] if isinstance(d, dict)]
    if detail:
        for d in detail:
            role = _role_name(d.get("title"), d.get("company"))
            start, end = to_month(d.get("start")), to_month(d.get("end"))
            for bullet in _strings(([d["description"]] if isinstance(d.get("description"), str) else []) + (d.get("bullets") or [])):
                yield "role", role, start, end, bullet
    else:
        for line in _strings(parsed.get("workExperience")):
            role, start, end, sentences = _work_experience_line(line)
            for sentence in sentences:
                yield "role", role, start, end, sentence

    experience_map = intelligence.get("experienceMap") or {}
    for text in _strings(parsed.get("projects")):
        # "RUTE INC — Transportation Management System: Led ..." belongs to the
        # employer and project its label names.
        label = _LABEL_PREFIX.match(text)
        yield "project", label.group(0).rstrip(": \t") if label else None, None, None, text
    for text in _strings(experience_map.get("projectHighlights")):
        yield "project", None, None, None, text
    for key in ("ownershipExamples", "leadershipExamples", "businessImpactExamples"):
        for text in _strings(experience_map.get(key)):
            yield "example", None, None, None, text

    for text in _group_items(parsed.get("competencyGroups")) + _group_items(parsed.get("toolGroups")):
        yield "fact", None, None, None, text
    for key in ("skills", "certifications", "education"):
        for text in _strings(parsed.get(key)):
            yield "fact", None, None, None, text


def evidence_id(source: str, role: str | None, text: str) -> str:
    """Derived from the item's own content, so it is stable within a profile version."""
    raw = "\0".join([source, role or "", text])
    return "ev-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build_evidence(profile: dict, intelligence: dict) -> list[dict]:
    """The evidence index of section 1.1, in a deterministic order.

    An item already in the index (same source, role and text, for example a skill
    that is both listed and in a tool group) is kept once.
    """
    profile = profile or {}
    intelligence = intelligence or {}
    full_name, links = identity_of(profile)

    seen: dict[str, None] = {}
    index = []
    for source, role, start, end, text in _raw_items(profile, intelligence):
        text, _ = redact_cv_text(text, full_name, links)
        text = text.strip()
        if not text:
            continue
        if role:
            role, _ = redact_cv_text(role, full_name, links)
        key = (source, (role or "").lower(), " ".join(text.lower().split()))
        if key in seen:
            continue
        seen[key] = None
        index.append({
            "id": evidence_id(source, role, text),
            "text": text,
            "source": source,
            "role": role,
            "start": start,
            "end": end,
            "strength": grade(text, source),
        })
    return index


def build_gates(intelligence: dict) -> dict:
    """`candidate.gates` (section 1.1) from the intelligence's own fields; nothing defaulted.

    The last four are what location_match.py reads to decide whether the
    candidate can get to the work; the location gate reuses that logic, so
    they belong to the profile version like every other gate input.
    """
    prefs = (intelligence or {}).get("jobFitPreferences") or {}
    floor = prefs.get("minSalaryEur")
    return {
        "workAuthorization": prefs.get("workAuthorization") or {},
        "allowedLocations": _strings(prefs.get("allowedLocations")),
        "languages": _strings((intelligence or {}).get("languages")),
        "minSalaryEur": floor if isinstance(floor, (int, float)) and not isinstance(floor, bool) and floor >= 0 else None,
        "preferredLocations": _strings(prefs.get("preferredLocations")),
        "remotePreference": str(prefs.get("remotePreference") or "").strip() or None,
        "relocation": str(prefs.get("relocation") or "").strip() or None,
        "country": str(prefs.get("country") or "").strip() or None,
    }


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def profile_version(evidence: list[dict], confirmed_facts: list[dict], gates: dict, role_family: str | None) -> str:
    """Hash of everything under `candidate` that can change a result (sections 1.1 and 6).

    Any change to an evidence item (text, dates, strength, order), a confirmed
    fact, a gate or the role family gives a different version.
    """
    return _hash({
        "evidence": evidence,
        "confirmedFacts": confirmed_facts,
        "gates": gates,
        "roleFamily": role_family,
    })


def evidence_version(evidence: list[dict], role_family: str | None) -> str:
    """Hash of what a cached matcher verdict depends on (contract 6.1): the only candidate input in the cache key."""
    return _hash({"evidence": evidence, "roleFamily": role_family})


def answers_version(confirmed_facts: list[dict], gates: dict) -> str:
    """Hash of what code applies on top of the cached verdicts (contract 6.1); it never invalidates them."""
    return _hash({"confirmedFacts": confirmed_facts, "gates": gates})


def build_candidate(profile: dict, intelligence: dict, confirmed_facts: list[dict]) -> dict:
    """The engine's `candidate` input, minus nothing; `roleFamily` is null when the profile sets none."""
    evidence = build_evidence(profile, intelligence)
    gates = build_gates(intelligence)
    role_family = (intelligence or {}).get("roleFamily") or None
    return {
        "profileVersion": profile_version(evidence, confirmed_facts, gates, role_family),
        "evidenceVersion": evidence_version(evidence, role_family),
        "answersVersion": answers_version(confirmed_facts, gates),
        "roleFamily": role_family,
        "evidence": evidence,
        "confirmedFacts": confirmed_facts,
        "gates": gates,
    }
