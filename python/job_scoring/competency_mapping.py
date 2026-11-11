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

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic
from match_engine import competencies
from requirement_ids import PROVISIONAL_PREFIX, assign_id, provisional_id

ROOT = Path(__file__).resolve().parents[2]
ALIASES_PATH = ROOT / "data" / "competency-aliases.json"
REMAP_PATH = ROOT / "data" / "requirement-remap.json"

PENDING, REVIEWED, AUTO, DEMOTED = "pending", "reviewed", "auto", "demoted"
GROUP_PREFIX = "grp:"  # provisional id of a group of new texts (competency_grouping.py); not on the family list
NONE_ANSWERS = {"", "none", "null"}
COVERS = ("whole", "part", "none")

# Kinds the model and the seed may disagree about without a rejection. Each
# group is a set of interchangeable kinds; a kind in no group must match
# exactly. The soft kinds are interchangeable (audit 2c-2b: 17 of 23 kind
# rejections were between them); domain and education stay strict. An empty
# tuple makes the check strict again.
KIND_GROUPS: tuple[frozenset, ...] = (frozenset({"skill", "experience", "other"}),)


def kinds_compatible(requirement_kind: str | None, competency_kind: str | None) -> bool:
    return requirement_kind == competency_kind or any(
        requirement_kind in g and competency_kind in g for g in KIND_GROUPS
    )

COMPETENCIES_BLOCK = """
=== COMPETENCIES (a fixed list of requirement ids with their definitions) ===
{rows}
=== END COMPETENCIES ===
"""

COMPETENCY_FIELD = """,
      "competency_id": "<an id from COMPETENCIES, or null>",
      "covers": "whole" | "part" | "none\""""

COMPETENCY_RULE = """
13. competency_id and covers. A competency here is one fixed piece of content. \
Pick an id from COMPETENCIES only where the competency covers the requirement, \
and say how much of it with covers:
- "whole": the competency covers ALL of the requirement, every condition, \
domain, tool or second activity it names. Use it only for a requirement that \
names exactly one competency's content and nothing more.
- "part": the competency covers only one component of a requirement that \
names more than one thing, or the requirement adds a condition the \
competency does not carry (a number of years, a level, a named industry or \
tool). Give the id of the component it covers.
- "none": no competency fits; competency_id is then null.
When in doubt, answer "part" or "none". Never force a match and never invent \
an id: use only ids listed in COMPETENCIES. null is the right answer for most \
requirements.

Illustration only, with an invented list: lantern-making ("making lanterns"), \
bridge-inspection ("inspecting bridges for faults"). Not part of COMPETENCIES.
- "Lantern making skills" -> lantern-making, whole
- "Able to inspect bridges for faults" -> bridge-inspection, whole
- "5+ years of lantern making" -> lantern-making, part (adds a number of years)
- "Lantern making for museum exhibitions" -> lantern-making, part (adds a named domain)
- "Inspects bridges and writes the repair budget" -> bridge-inspection, part (a second activity)
- "Lantern making or bridge inspection" -> lantern-making, part (names two competencies)
- "Cheerful and punctual" -> null, none
- "Comfortable working near the harbour" -> null, none
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
    make_private_dirs(path.parent)
    write_text_atomic(path, json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True), PRIVATE_FILE_MODE)


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
            if isinstance(v, dict) and (v.get("competencyId") in self.by_id
                                        or str(v.get("competencyId")).startswith(GROUP_PREFIX))
        }
        self.remap = load_remap(self.remap_path)
        self.stats: Counter = Counter()  # what the model's suggestions came to
        self.routes: Counter = Counter()  # how each requirement got its id: frame, alias, dictionary, model, provisional
        self.picks: list[tuple[str, str]] = []  # (text, competency id) of every accepted suggestion
        self.parts: list[tuple[str, str]] = []  # (text, competency id) of every "part" answer
        self.kind_rejections: Counter = Counter()  # (requirement kind, competency kind) of picks the kind check refused
        self.decisions: list[dict] = []  # every suggestion consulted: text, id, covers, outcome
        self._lock = threading.Lock()
        self._dirty = False

    def prompt_block(self) -> str:
        return COMPETENCIES_BLOCK.format(rows=list_rows(self.comps))

    @staticmethod
    def demoted_ids(entry: dict | None) -> set[str]:
        """The competency ids the owner rejected for this text: `demotedIds`, plus the entry's own id when its status is demoted
        (a flat entry written before `demotedIds` existed blocks its own pair only)."""
        if not entry:
            return set()
        ids = {str(i) for i in entry.get("demotedIds") or []}
        if entry.get("status") == DEMOTED and entry.get("competencyId"):
            ids.add(str(entry["competencyId"]))
        return ids

    def is_demoted(self, text: str | None, cid: str | None) -> bool:
        """True when the owner rejected exactly this text-id pair."""
        return cid is not None and str(cid) in self.demoted_ids(self.learned.get(competencies.alias_key(text)))

    def _entry(self, text: str | None, cid: str, status: str) -> dict:
        """A learned entry for (text, cid) that keeps every id already rejected for the text."""
        old = self.demoted_ids(self.learned.get(competencies.alias_key(text)))
        demoted = sorted(old | {cid}) if status == DEMOTED else sorted(old - {cid})
        entry = {"competencyId": cid, "status": status}
        if demoted:
            entry["demotedIds"] = demoted
        return entry

    def alias_hit(self, text: str | None, cid: str | None = None) -> str | None:
        """The id a seed or learned alias gives the text. `cid` is the id being asked about (default: the alias's own); a demoted pair gives None."""
        key = competencies.alias_key(text)
        if key in self.seed:
            return self.seed[key]
        learned = self.learned.get(key)
        if not learned:
            return None
        demoted = self.demoted_ids(learned)
        if (cid or learned["competencyId"]) in demoted or learned["competencyId"] in demoted:
            return None
        return learned["competencyId"]

    def link(self, text: str | None, cid: str, status: str) -> bool:
        """Store a learned link (grouping); the caller saves. A demoted text-id pair is refused (returns False)."""
        with self._lock:
            if status != DEMOTED and self.is_demoted(text, cid):
                return False
            self.learned[competencies.alias_key(text)] = self._entry(text, cid, status)
            self._dirty = True
            return True

    def mapping_status(self, requirement: dict) -> str | None:
        """"reviewed" (seed alias or reviewed learned alias), "auto", "pending", "demoted", or None when the id is not a mapped competency."""
        key = competencies.alias_key(requirement.get("text"))
        cid = requirement.get("id")
        if self.seed.get(key) == cid:
            return REVIEWED
        learned = self.learned.get(key)
        if learned and cid in self.demoted_ids(learned):
            return DEMOTED
        if learned and learned["competencyId"] == cid:
            return learned["status"] if learned.get("status") in (REVIEWED, AUTO) else PENDING
        return None

    def _suggestion(self, requirement: dict, suggested: str | None, covers: str | None = None) -> str | None:
        """The model's competencyId if code accepts it; every outcome is counted.

        Accepted only for covers "whole", an id on the list, and a compatible kind.
        "part" leaves the requirement provisional and stores nothing. A covers
        that contradicts the id (whole with no id, none with an id, part with
        no id, or no readable covers with an id) is an inconsistency, treated as none.
        """
        answer = (suggested or "").strip()
        has_id = answer.lower() not in NONE_ANSWERS
        said = (covers or "").strip().lower()
        covers_read = said if said in COVERS else None
        text = str(requirement.get("text"))

        def decide(outcome: str, result: str | None = None) -> str | None:
            self.stats[outcome] += 1
            self.decisions.append({"text": text, "id": answer if has_id else None, "covers": covers_read or "unreadable",
                                   "outcome": outcome})
            return result

        if not has_id:
            if covers_read == "whole" or covers_read == "part":
                return decide("inconsistent")
            return decide("none")
        if covers_read in (None, "none"):
            return decide("inconsistent")
        comp = self.by_id.get(answer)
        if comp is None:
            return decide("rejected: not on the list")
        if covers_read == "part":
            self.parts.append((text, answer))
            return decide("part")
        if not kinds_compatible(requirement.get("kind"), comp["kind"]):
            self.kind_rejections[(requirement.get("kind"), comp["kind"])] += 1
            return decide("rejected: kind differs")
        return decide("accepted", answer)

    def resolve(self, requirement: dict, suggested: str | None = None, covers: str | None = None) -> dict:
        """The requirement with `id` and `provisional` set: alias > dictionary term > accepted suggestion > hash."""
        resolved, route = self.resolve_with_route(requirement, suggested, covers)
        self.count_route(route)
        return resolved

    def resolve_with_route(
        self, requirement: dict, suggested: str | None = None, covers: str | None = None
    ) -> tuple[dict, str]:
        """resolve(), and the route taken: "alias", "dictionary", "model" or "provisional"."""
        text = requirement.get("text")
        with self._lock:
            cid = self.alias_hit(text)
            if cid:
                self._gain(text, cid)
                return {**requirement, "id": cid, "provisional": False}, "alias"
            assigned = assign_id(requirement)
            if not assigned["provisional"]:
                return assigned, "dictionary"
            cid = self._suggestion(requirement, suggested, covers)
            if cid and self.is_demoted(text, cid):
                return assigned, "provisional"  # the owner rejected this text-id pair; never proposed again (other ids are allowed)
            if cid:
                self.learned[competencies.alias_key(text)] = self._entry(text, cid, PENDING)
                self.picks.append((str(text), cid))
                self._gain(text, cid)
                self._dirty = True
                return {**requirement, "id": cid, "provisional": False}, "model"
            return assigned, "provisional"

    def count_route(self, route: str) -> None:
        with self._lock:
            self.routes[route] += 1

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
