"""The store of answers the user gave to engine questions (ENGINE_CONTRACT.md 1.1).

Each fact is `{competencyId, has, note}`: `competencyId` is a requirement id
(canonical or `prov:`) or a gate name, `has` says whether the candidate has it,
`note` is free text that may be empty. A confirmed fact outranks inferred
evidence. Nothing writes here yet; the question flow of a later step does.

File (data/profile/, git-ignored like the rest of the profile):

    {"version": 1, "facts": [{"competencyId": "...", "has": true, "note": ""}]}

A missing file is an empty store. A malformed entry is dropped on read, so a
hand edit can never put a wrong fact in front of the scorer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic

ROOT = Path(__file__).resolve().parents[2]
CONFIRMED_FACTS_PATH = ROOT / "data" / "profile" / "confirmed-facts.json"
STORE_VERSION = 1


class ConfirmedFact(TypedDict):
    competencyId: str
    has: bool
    note: str


def _valid(item) -> ConfirmedFact | None:
    if not isinstance(item, dict):
        return None
    competency = item.get("competencyId")
    has = item.get("has")
    note = item.get("note", "")
    if not isinstance(competency, str) or not competency.strip() or not isinstance(has, bool):
        return None
    return {"competencyId": competency.strip(), "has": has, "note": note if isinstance(note, str) else ""}


def load(path: Path = CONFIRMED_FACTS_PATH) -> list[ConfirmedFact]:
    """The stored facts, one per competency (the last answer wins), sorted by id."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id: dict[str, ConfirmedFact] = {}
    for item in (data.get("facts") if isinstance(data, dict) else None) or []:
        fact = _valid(item)
        if fact:
            by_id[fact["competencyId"]] = fact
    return [by_id[k] for k in sorted(by_id)]


def save(facts: list[ConfirmedFact], path: Path = CONFIRMED_FACTS_PATH) -> None:
    clean = [f for f in (_valid(item) for item in facts) if f]
    make_private_dirs(path.parent)
    write_text_atomic(path, json.dumps({"version": STORE_VERSION, "facts": clean}, indent=2), new_file_mode=PRIVATE_FILE_MODE)
