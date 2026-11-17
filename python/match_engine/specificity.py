"""Which requirement units carry weight in Fit (plan 3.3, owner decision Q3). Code on extractor fields only; no model.

THE RULE (pre-registered in w2-report.md before any overlap number was read):

  A requirement unit is GENERIC, and weighs 0 in Fit and confidence, when its competency id is in GENERIC_COMPETENCY_IDS.
  Otherwise it is SPECIFIC when it maps to a canonical competency id (the extractor's `provisional` is false) or its kind is
  skill, domain, certification or language. Everything else (a non-canonical experience, education or other line) is
  GENERIC.

The generic ids are a named list because src/data/competencies/*.json has no soft-skill field. They are the competencies
whose whole content is a trait every posting lists (communication in its three forms, collaboration, problem solving).
Stakeholder management, cross-functional collaboration and leadership stay specific: they are what a product role is about.
Limit: a non-canonical ("q:") unit carries no competency id and, offline, no text, so a generic line the mapper could not
resolve is generic only through its kind.
"""

from __future__ import annotations

SPECIFIC_KINDS = frozenset({"skill", "domain", "certification", "language"})
GENERIC_COMPETENCY_IDS = frozenset({
    "communication", "written-communication", "verbal-communication", "collaboration", "problem-solving",
})


def is_specific(kind: str | None, competency_id: str | None, canonical: bool) -> bool:
    """The rule above. `competency_id` is read only when `canonical`."""
    if canonical and competency_id in GENERIC_COMPETENCY_IDS:
        return False
    return canonical or kind in SPECIFIC_KINDS


def requirement_is_specific(req: dict) -> bool:
    """The rule on one engine requirement (id, provisional, kind)."""
    canonical = bool(req.get("id")) and req.get("provisional") is False
    return is_specific(req.get("kind"), req.get("id"), canonical)
