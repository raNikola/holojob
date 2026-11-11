"""Which confirmed answer reaches a requirement (COMPETENCY_MEMORY_MVP_SPEC.md 4.4, A3).

An id match alone is not enough when the id came through a link the owner has not
reviewed: a requirement behind a `pending`, `auto` or `demoted` link gets the answer
only if the answer covered its text. Any status other than "reviewed" or None is
treated the same way, so an unrecognised one carries nothing.
"""

from __future__ import annotations

from functools import lru_cache

from .competencies import alias_key


@lru_cache(maxsize=None)
def _cached_mapper(family: str | None):
    from competency_mapping import load_mapper  # reads the aliases file, so only when a fact needs it

    return load_mapper(family)


def carries(req: dict, fact: dict, mapper) -> bool:
    """Whether `fact`, already matched on id, may settle `req`. No mapper means no alias is involved."""
    status = mapper.mapping_status(req) if mapper else None
    if status in (None, "reviewed"):
        return True
    return alias_key(req.get("text")) in {alias_key(text) for text in fact["coveredTexts"]}


def fact_for(req: dict, candidate: dict, mapper_for=None) -> dict | None:
    """The candidate's confirmed fact that reaches this requirement, or None."""
    fact = next((f for f in candidate.get("confirmedFacts") or [] if f["competencyId"] == req["id"]), None)
    if fact is None:
        return None
    mapper = (mapper_for or _cached_mapper)(candidate.get("roleFamily"))
    return fact if carries(req, fact, mapper) else None
