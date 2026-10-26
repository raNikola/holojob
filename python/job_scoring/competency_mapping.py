"""Competency ids for the requirements the extraction call read.

DECISIONS.md, 2026-10-26 (stable requirement ids). Id precedence, applied in
enrich_jobs._reuse_previous: previous frame id > exact alias (the seed's, then
the learned ones) > skills-dictionary term > the model's competencyId >
provisional hash. The model only proposes; this module accepts a proposal when
the id is on the family's list and its kind is the requirement's kind.

An accepted proposal is stored as a learned alias, status "pending", in
data/competency-aliases.json (private, like everything under data/). A seed
alias counts as "reviewed" without being stored. Whenever a provisional id
gains a canonical id, prov:<hash> -> canonical id goes into the remap table
data/requirement-remap.json, and requirement_frames rewrites frames with it.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path

from match_engine import competencies
from requirement_ids import PROVISIONAL_PREFIX, assign_id, provisional_id

ROOT = Path(__file__).resolve().parents[2]
ALIASES_PATH = ROOT / "data" / "competency-aliases.json"
REMAP_PATH = ROOT / "data" / "requirement-remap.json"

PENDING, REVIEWED = "pending", "reviewed"
NONE_ANSWERS = {"", "none", "null"}

COMPETENCIES_BLOCK = """
=== COMPETENCIES (a fixed list of requirement ids with their definitions) ===
{rows}
=== END COMPETENCIES ===
"""

COMPETENCY_FIELD = """,
      "competency_id": "<an id from COMPETENCIES, or null>\""""

COMPETENCY_RULE = """
13. competency_id: pick an id from COMPETENCIES only where the requirement is \
that competency at the same or a narrower scope, as its definition says. \
Answer null where the requirement is broader than the competency, names two \
competencies, or is not clearly covered by one. Never force a match, and \
never invent an id: null is the right answer for most requirements.
"""


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def load_remap(path: Path | None = None) -> dict[str, str]:
    """prov:<hash> -> canonical id."""
    return {k: v for k, v in _read(path or REMAP_PATH).items() if isinstance(v, str)}


def list_rows(comps: list[dict]) -> str:
    """The competency list as the prompt shows it: id, kind, definition. Nothing about the candidate."""
    return "\n".join(
        json.dumps({"id": c["id"], "kind": c["kind"], "definition": c["definition"]}, ensure_ascii=False)
        for c in comps
    )


class Mapper:
    """One role family's competencies, the learned aliases and the remap table, for one extraction run."""

    def __init__(self, comps: list[dict], aliases_path: Path | None = None, remap_path: Path | None = None):
        self.comps = comps
        self.by_id = {c["id"]: c for c in comps}
        self.seed = competencies.alias_index(comps)
        self.aliases_path = aliases_path or ALIASES_PATH
        self.remap_path = remap_path or REMAP_PATH
        self.learned: dict[str, dict] = {
            k: v for k, v in _read(self.aliases_path).items()
            if isinstance(v, dict) and v.get("competencyId") in self.by_id
        }
        self.remap = load_remap(self.remap_path)
        self.stats: Counter = Counter()
        self._lock = threading.Lock()
        self._dirty = False

    def prompt_block(self) -> str:
        return COMPETENCIES_BLOCK.format(rows=list_rows(self.comps))

    def alias_hit(self, text: str | None) -> str | None:
        key = competencies.alias_key(text)
        if key in self.seed:
            return self.seed[key]
        learned = self.learned.get(key)
        return learned["competencyId"] if learned else None

    def mapping_status(self, requirement: dict) -> str | None:
        """"reviewed" (seed alias or reviewed learned alias), "pending", or None when the id is not a mapped competency."""
        key = competencies.alias_key(requirement.get("text"))
        cid = requirement.get("id")
        if self.seed.get(key) == cid:
            return REVIEWED
        learned = self.learned.get(key)
        if learned and learned["competencyId"] == cid:
            return REVIEWED if learned.get("status") == REVIEWED else PENDING
        return None

    def _suggestion(self, requirement: dict, suggested: str | None) -> str | None:
        """The model's competencyId if code accepts it; every outcome is counted."""
        answer = (suggested or "").strip()
        if answer.lower() in NONE_ANSWERS:
            self.stats["none"] += 1
            return None
        comp = self.by_id.get(answer)
        if comp is None:
            self.stats["rejected: not on the list"] += 1
            return None
        if comp["kind"] != requirement.get("kind"):
            self.stats["rejected: kind differs"] += 1
            return None
        self.stats["accepted"] += 1
        return answer

    def resolve(self, requirement: dict, suggested: str | None = None) -> dict:
        """The requirement with `id` and `provisional` set: alias > dictionary term > accepted suggestion > hash."""
        text = requirement.get("text")
        with self._lock:
            cid = self.alias_hit(text)
            if cid:
                self._gain(text, cid)
                return {**requirement, "id": cid, "provisional": False}
            assigned = assign_id(requirement)
            if not assigned["provisional"]:
                return assigned
            cid = self._suggestion(requirement, suggested)
            if cid:
                self.learned[competencies.alias_key(text)] = {"competencyId": cid, "status": PENDING}
                self._gain(text, cid)
                self._dirty = True
                return {**requirement, "id": cid, "provisional": False}
            return assigned

    def _gain(self, text: str | None, cid: str) -> None:
        self.record_remap(provisional_id(text), cid)

    def record_remap(self, provisional: str, canonical: str) -> None:
        if provisional.startswith(PROVISIONAL_PREFIX) and self.remap.get(provisional) != canonical:
            self.remap[provisional] = canonical
            self._dirty = True

    def save(self) -> None:
        """Write the learned aliases and the remap table, only if this run changed them."""
        with self._lock:
            if not self._dirty:
                return
            _write(self.aliases_path, self.learned)
            _write(self.remap_path, self.remap)
            self._dirty = False

    def summary(self) -> str:
        return ", ".join(f"{k} {v}" for k, v in sorted(self.stats.items())) or "no suggestions"


def load_mapper(family: str | None) -> Mapper | None:
    """A mapper for the role family, or None: no family, no seed, or a seed that does not validate."""
    if not family:
        return None
    comps = competencies.load(family)
    if not comps:
        return None
    problems = competencies.validate(comps)
    if problems:
        print(f"competency list '{family}' is not usable, requirements stay unmapped:", *problems, sep="\n  ")
        return None
    return Mapper(comps)
