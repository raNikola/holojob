"""The store of answers the user gave to engine questions (ENGINE_CONTRACT.md 1.1).

Each fact is `{competencyId, answer, qualifier, note, answeredAt, overrules,
coveredTexts, history}` (COMPETENCY_MEMORY_MVP_SPEC.md 3.1): `competencyId` is a
requirement id (canonical or `prov:`) or a gate name, `answer` is yes / partly /
no / unknown, `qualifier` is `{"kind": "years", "value": 0-40}` or null,
`coveredTexts` the normalized requirement texts the answer covers, `history` up
to 20 earlier answers. `note` is owner-only. A confirmed fact outranks inferred
evidence.

File (data/profile/, git-ignored like the rest of the profile):

    {"version": 2, "facts": [fact]}

A v1 file (`{competencyId, has, note}`) reads as v2 (true -> yes, false -> no) and is
rewritten only on the next save. A missing file is an empty store. A malformed entry is dropped on read, so a
hand edit can never put a wrong fact in front of the scorer.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic

ROOT = Path(__file__).resolve().parents[2]
CONFIRMED_FACTS_PATH = ROOT / "data" / "profile" / "confirmed-facts.json"
STORE_VERSION = 2
ANSWERS = ("yes", "partly", "no", "unknown")
VIAS = ("queue", "edit", "revoke", "conflict", "cv_confirm")
HISTORY_LIMIT = 20


class ConfirmedFact(TypedDict):
    competencyId: str
    answer: str
    qualifier: dict | None
    note: str
    answeredAt: str | None
    overrules: list[str]
    coveredTexts: list[str]
    history: list[dict]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _qualifier(value) -> tuple[bool, dict | None]:
    """(valid, qualifier): null is valid, a years value must be an int 0-40 (not a bool)."""
    if value is None:
        return True, None
    if isinstance(value, dict) and value.get("kind") == "years":
        years = value.get("value")
        if isinstance(years, int) and not isinstance(years, bool) and 0 <= years <= 40:
            return True, {"kind": "years", "value": years}
    return False, None


def _strings(value) -> list[str]:
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def _history_entry(item) -> dict | None:
    if not isinstance(item, dict) or item.get("answer") not in ANSWERS or item.get("via") not in VIAS:
        return None
    ok, qualifier = _qualifier(item.get("qualifier"))
    at = item.get("at")
    if not ok or not (at is None or isinstance(at, str)):
        return None
    return {"answer": item["answer"], "qualifier": qualifier, "at": at, "via": item["via"]}


def _valid(item) -> ConfirmedFact | None:
    if not isinstance(item, dict):
        return None
    competency = item.get("competencyId")
    if not isinstance(competency, str) or not competency.strip():
        return None
    if "answer" in item:
        answer = item["answer"]
    elif isinstance(item.get("has"), bool):  # v1
        answer = "yes" if item["has"] else "no"
    else:
        return None
    ok, qualifier = _qualifier(item.get("qualifier"))
    if answer not in ANSWERS or not ok:
        return None
    note = item.get("note", "")
    at = item.get("answeredAt")
    history = item.get("history")
    entries = [e for e in (_history_entry(h) for h in history) if e] if isinstance(history, list) else []
    return {
        "competencyId": competency.strip(),
        "answer": answer,
        "qualifier": qualifier,
        "note": note if isinstance(note, str) else "",
        "answeredAt": at if isinstance(at, str) else None,
        "overrules": _strings(item.get("overrules")),
        "coveredTexts": _strings(item.get("coveredTexts")),
        "history": entries[-HISTORY_LIMIT:],
    }


def load(path: Path = CONFIRMED_FACTS_PATH) -> list[ConfirmedFact]:
    """The stored facts, one per competency (the last answer wins), sorted by id. Never writes."""
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
    by_id = {f["competencyId"]: f for f in (_valid(item) for item in facts) if f}
    clean = [by_id[k] for k in sorted(by_id)]
    make_private_dirs(path.parent)
    write_text_atomic(path, json.dumps({"version": STORE_VERSION, "facts": clean}, indent=2), new_file_mode=PRIVATE_FILE_MODE)


def record_answer(
    competency_id: str,
    answer: str,
    *,
    via: str,
    qualifier: dict | None = None,
    note: str = "",
    covered_texts: list[str] | None = None,
    overrules: list[str] | None = None,
    path: Path = CONFIRMED_FACTS_PATH,
    now: Callable[[], str] = _now,
) -> ConfirmedFact:
    """Record the owner's answer; the previous answer moves to history with this `via`."""
    fact = _valid({
        "competencyId": competency_id, "answer": answer, "qualifier": qualifier, "note": note,
        "answeredAt": now(), "overrules": overrules, "coveredTexts": covered_texts,
    })
    if not fact or via not in VIAS:
        raise ValueError("invalid confirmed fact")
    facts = {f["competencyId"]: f for f in load(path)}
    old = facts.get(fact["competencyId"])
    if old:
        entry = {"answer": old["answer"], "qualifier": old["qualifier"], "at": old["answeredAt"], "via": via}
        fact["history"] = (old["history"] + [entry])[-HISTORY_LIMIT:]
    facts[fact["competencyId"]] = fact
    save(list(facts.values()), path)
    return fact


def revoke(competency_id: str, *, path: Path = CONFIRMED_FACTS_PATH, now: Callable[[], str] = _now) -> ConfirmedFact | None:
    """Move a fact to `unknown`, keeping its history. None if there is no such fact."""
    old = next((f for f in load(path) if f["competencyId"] == competency_id), None)
    if not old:
        return None
    return record_answer(competency_id, "unknown", via="revoke", note=old["note"], path=path, now=now)
