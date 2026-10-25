"""The last requirement frame read from each ad, fed back to its next extraction.

DECISIONS.md principle 9 and ENGINE_CONTRACT.md section 6: the same ad read
twice must name the same requirement with the same id. Provisional ids hash
the requirement's text (requirement_ids.py), so an extractor that rewords a
requirement gives it a new id. The previous frame (id, text, kind,
importance per requirement) goes into the extraction prompt, the model
points at the previous id of a requirement it reads again, and code reuses
that id and its text (enrich_jobs._reuse_previous).

Where it lives: data/cache/requirement-frames.json, on the server like every
other file generated from an ad, gitignored. One entry per ad, keyed by
frame_key(): the ad's content without the prompt version, so a frame
survives what job_fingerprint deliberately does not (a prompt bump re-reads
every ad, and that re-read is when the old ids matter most). An ad whose text
changes gets a new key and no frame; a job record's own llmFacts, read under
an earlier prompt, is the fallback for that (previous_for).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from job_fingerprint import MAX_DESCRIPTION_CHARS

ROOT = Path(__file__).resolve().parents[2]
FRAMES_PATH = ROOT / "data" / "cache" / "requirement-frames.json"
FRAME_FIELDS = ("id", "text", "kind", "importance")


def frame_key(job: dict) -> str:
    """What job_fingerprint covers, less the prompt version."""
    raw = "|".join([
        job.get("title") or "",
        job.get("company") or "",
        (job.get("description") or "")[:MAX_DESCRIPTION_CHARS],
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load(path: Path | None = None) -> dict:
    path = path or FRAMES_PATH
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(frames: dict, path: Path | None = None) -> None:
    path = path or FRAMES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(frames, indent=1, ensure_ascii=False), encoding="utf-8")


def frame_of(requirements: list[dict]) -> list[dict]:
    return [{k: r.get(k) for k in FRAME_FIELDS} for r in requirements if r.get("id")]


def previous_for(frames: dict, job: dict) -> list[dict]:
    """The stored frame for this ad, else the requirements on the job's own llmFacts, else none."""
    stored = frames.get(frame_key(job))
    if stored:
        return stored
    return frame_of(((job.get("llmFacts") or {}).get("requirements")) or [])


def remember(frames: dict, job: dict, facts: dict) -> None:
    """Store the frame just read; an extraction with no requirements leaves the old one."""
    frame = frame_of(facts.get("requirements") or [])
    if frame:
        frames[frame_key(job)] = frame
