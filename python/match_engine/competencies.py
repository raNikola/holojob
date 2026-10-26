"""The curated competency list of a role family, and the checks that keep it sound.

DECISIONS.md, 2026-10-26 (stable requirement ids): one list per role family in
src/data/competencies/<family>.json, read by this module the way scorer.py
reads roleFamilies.json. Each competency has an id, a one-line definition (what
counts and what does not), a kind, aliases (normalized wordings of the same
requirement) and an optional parent. A parent is for display and evidence
retrieval only: evidence for a parent never satisfies a narrower child.

Competency ids and skills-dictionary ids share one namespace. A technology
term of src/data/skillsDictionary.js belongs to the dictionary, so no id or
alias here may equal one of its terms or contain one.

Nothing maps a requirement to a competency yet (step 2c); this module only
loads, validates and indexes the list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from enrich_jobs import REQUIREMENT_KINDS
from requirement_ids import canonical_id, dictionary_terms_in, load_dictionary

from .normalize import normalize

ROOT = Path(__file__).resolve().parents[2]
COMPETENCIES_DIR = ROOT / "src" / "data" / "competencies"

_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TRAILING_PUNCTUATION = ".,;:"


def alias_key(text: str | None) -> str:
    """The one form an alias and a requirement text are compared in.

    match_engine.normalize (NFKC, diacritics folded, whitespace collapsed, case
    folded), then typographic apostrophes straightened and trailing .,;:
    dropped, so "Bachelor’s degree." and "bachelor's degree" are one key.
    Nothing else is stripped: "strong communication skills" is its own alias.
    """
    key = normalize(text).replace("’", "'").replace("‘", "'")
    return key.rstrip(_TRAILING_PUNCTUATION).rstrip()


def load(family: str, directory: Path | None = None) -> list[dict]:
    """The competencies of a role family; an unknown family has no file and no list."""
    path = (directory or COMPETENCIES_DIR) / f"{family}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("competencies", [])


def alias_index(competencies: list[dict]) -> dict[str, str]:
    """alias key -> competency id. validate() guarantees an alias has one owner."""
    return {alias_key(a): c["id"] for c in competencies for a in c.get("aliases", [])}


def validate(competencies: list[dict], dictionary: list[str] | None = None) -> list[str]:
    """Every problem found, as readable lines; an empty list means the list is sound."""
    terms = load_dictionary() if dictionary is None else dictionary
    dictionary_ids = {canonical_id(t): t for t in terms}
    dictionary_keys = {alias_key(t): t for t in terms}
    problems: list[str] = []

    ids: dict[str, dict] = {}
    for c in competencies:
        cid = c.get("id")
        if not isinstance(cid, str) or not _KEBAB.match(cid):
            problems.append(f"id {cid!r} is not kebab-case")
            continue
        if cid in ids:
            problems.append(f"{cid}: duplicate id")
        ids[cid] = c
        if cid in dictionary_ids:
            problems.append(f"{cid}: id is the skills dictionary's id for {dictionary_ids[cid]!r}")

    owners: dict[str, str] = {}
    for c in competencies:
        cid = c.get("id")
        if cid not in ids:
            continue
        definition = c.get("definition")
        if not isinstance(definition, str) or not definition.strip() or "\n" in definition:
            problems.append(f"{cid}: definition must be one non-empty line")
        if c.get("kind") not in REQUIREMENT_KINDS:
            problems.append(f"{cid}: kind {c.get('kind')!r} is not a requirement kind")
        aliases = c.get("aliases")
        if not isinstance(aliases, list) or not aliases:
            problems.append(f"{cid}: needs at least one alias")
            aliases = []
        for alias in aliases:
            key = alias_key(alias) if isinstance(alias, str) else ""
            if not key:
                problems.append(f"{cid}: empty or non-string alias {alias!r}")
            elif alias != key:
                problems.append(f"{cid}: alias {alias!r} is not normalized (expected {key!r})")
            elif key in owners and owners[key] != cid:
                problems.append(f"alias {key!r} belongs to both {owners[key]} and {cid}")
            elif key in owners:
                problems.append(f"{cid}: alias {key!r} listed twice")
            else:
                owners[key] = cid
            if key in dictionary_keys:
                problems.append(f"{cid}: alias {key!r} is the skills dictionary term {dictionary_keys[key]!r}")
            elif key and dictionary_terms_in(key):
                problems.append(f"{cid}: alias {key!r} contains the skills dictionary term(s) {dictionary_terms_in(key)}")

        parent = c.get("parent")
        if parent is not None and parent not in ids:
            problems.append(f"{cid}: parent {parent!r} does not exist")

    for cid in ids:
        seen, node = [], cid
        while node is not None and node in ids:
            if node in seen:
                problems.append(f"{cid}: parent chain loops ({' -> '.join(seen + [node])})")
                break
            seen.append(node)
            node = ids[node].get("parent")
    return problems
