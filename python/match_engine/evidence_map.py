"""Competency evidence map: what a verified CV verdict proved, remembered per competency (spec 3.5 and 4.1). CHECK MODE ONLY.

The map is written and compared, and the matcher is still asked for every requirement; `checks` count how often it agrees. Nothing here
replaces a call or changes a verdict. Stored: ids, hashes, a status, a strength. No candidate text, and never a confirmed fact (a user fact always wins).

Learned only from a MET with a verified quote, on a requirement with no level, reached through the seed, a reviewed link, or an `auto` link whose text
the owner's answer covers, and only when stable: both readings agree and the line is not flagged, or, with one reading, strength 3-4.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic

from . import competencies

ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = ROOT / "data" / "cache" / "competency-evidence.json"
MAP_VERSION = 1
ONE_READING_MIN_STRENGTH = 3


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_level(req: dict) -> bool:
    return bool(req.get("qualifier") or req.get("requirementLevel"))


class EvidenceMap:
    """Passed to ShadowEngine as `memory`. `already_matched` holds cache keys known before this run: a repeated cached verdict is not a new check."""

    def __init__(self, candidate: dict, mapper=None, path: Path = MAP_PATH, already_matched=(), now=lambda: datetime.now(timezone.utc)):
        self.path, self.mapper, self.now, self.already_matched = path, mapper, now, set(already_matched)
        self.version = candidate["evidenceVersion"]
        self.items = {item["id"]: item for item in candidate.get("evidence") or []}
        facts = candidate.get("confirmedFacts") or []
        self.fact_ids = {f["competencyId"] for f in facts}
        self.covered = {competencies.alias_key(t) for f in facts for t in f.get("coveredTexts") or []}
        self.entries, self.dirty = self._load()

    def _load(self) -> tuple[dict, bool]:
        """Stored entries still true of this CV. A changed evidence version empties the map; a changed item drops its entry."""
        if not self.path.exists():
            return {}, False
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("evidenceVersion") != self.version:
            return {}, True
        stored = data.get("entries") or {}
        kept = {cid: e for cid, e in stored.items() if e.get("evidenceId") in self.items and e.get("evidenceTextHash") == text_hash(self.items[e["evidenceId"]]["text"])}
        return kept, len(kept) != len(stored)

    def _route(self, req: dict) -> str | None:
        """How the requirement reached its competency, or None when that route may not carry evidence."""
        status = self.mapper.mapping_status(req) if self.mapper else None
        if status == "reviewed":
            return "reviewed"
        if status is None:
            return None if str(req["id"]).startswith("prov:") else "seed"
        return "covered" if status == "auto" and competencies.alias_key(req.get("text")) in self.covered else None

    @staticmethod
    def _stability(req: dict) -> str | None:
        """Two-reading verdicts carry `flagged` (matcher_v3.aggregate_two)."""
        if "flagged" in req:
            return None if req["flagged"] else "two_readings"
        return "one_reading" if (req.get("strength") or 0) >= ONE_READING_MIN_STRENGTH else None

    def _learn(self, req: dict, job_id, route: str) -> None:
        item, stability = self.items.get(req.get("evidenceId")), self._stability(req)
        if req["status"] != "MET" or req.get("quoteVerified") is not True or not req.get("evidenceQuote") or item is None or stability is None:
            return
        self.entries[req["id"]] = {
            "status": "MET", "evidenceId": item["id"], "evidenceTextHash": text_hash(item["text"]), "strength": req["strength"], "stability": stability,
            "learnedFrom": {"jobId": job_id, "requirementId": req["id"], "via": route},
            "learnedAt": self.now().isoformat().replace("+00:00", "Z"), "checks": {"agree": 0, "disagree": 0},
        }
        self.dirty = True

    def observe(self, posting: dict, output: dict) -> None:
        """Learn from, or check against, one fresh matcher output. A line a fact or the language list settled is not a matcher verdict."""
        if output.get("cacheKey") in self.already_matched:
            return
        for req in output["requirements"]:
            if req["id"] in self.fact_ids or req.get("kind") == "language" or _has_level(req):
                continue
            route = self._route(req)
            if route is None:
                continue
            entry = self.entries.get(req["id"])
            if entry is None:
                self._learn(req, posting.get("id"), route)
            else:
                entry["checks"]["agree" if req["status"] == entry["status"] else "disagree"] += 1
                self.dirty = True

    def summary(self) -> dict:
        checks = [e["checks"] for e in self.entries.values()]
        return {"entries": len(checks), "agree": sum(c["agree"] for c in checks), "disagree": sum(c["disagree"] for c in checks)}

    def save(self) -> None:
        if not self.dirty:
            return
        make_private_dirs(self.path.parent)
        write_text_atomic(self.path, json.dumps({"version": MAP_VERSION, "evidenceVersion": self.version, "entries": self.entries}, indent=1), new_file_mode=PRIVATE_FILE_MODE)
        self.dirty = False
        s = self.summary()
        print(f"evidence map (check mode, nothing replaced): {s['entries']} entries, matcher agreed {s['agree']}, disagreed {s['disagree']}")
