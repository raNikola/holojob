"""The owner's profile enrichment: domain entries, work-history entries and experience boundaries, each with its source tag.

File (data/profile-enrichment.json, private, git-ignored, written 600 through the atomic helper):

    {"version": 1,
     "employers": [str],                                   # names the Experiment B summary masks
     "domains":    [{"id", "source", "title", "text"}],
     "history":    [{"id", "source", "role", "period", "text"}],
     "boundaries": [{"id", "source", "stance", "text"}]}   # stance: direct | none | limited

`source` is "CV" (verified against the public CV and its PDFs) or "owner-confirmed" (confirmed by the owner, not in the CV). Text is stored word for
word as the owner gave it; nothing here rewrites it. Contact data never belongs in this file.

The evidence index reads it (`evidence_items`): a domain entry is an `example` item, a history entry a `role` item with its dates, a boundary a `fact`
item. A boundary with stance "none" is marked `negative`: the matcher may quote it to show an area is MISSING, and `verify.apply_proposal` turns a
MET/PARTIAL that cites it into MISSING, so a statement of absence can never be evidence of experience.

A missing file is an empty enrichment. A malformed entry is dropped on read.
"""

from __future__ import annotations

import json
from pathlib import Path

from atomic_write import PRIVATE_FILE_MODE, write_text_atomic

ROOT = Path(__file__).resolve().parents[2]
ENRICHMENT_PATH = ROOT / "data" / "profile-enrichment.json"
VERSION = 1
SOURCES = ("CV", "owner-confirmed")
STANCES = ("direct", "none", "limited")
SECTIONS = {"domains": ("id", "source", "title", "text"), "history": ("id", "source", "role", "period", "text"), "boundaries": ("id", "source", "stance", "text")}


def _valid(section: str, item) -> bool:
    if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in SECTIONS[section]):
        return False
    if item["source"] not in SOURCES:
        return False
    return section != "boundaries" or item["stance"] in STANCES


def normalize(data) -> dict:
    data = data if isinstance(data, dict) else {}
    out = {"version": VERSION, "employers": [e for e in data.get("employers") or [] if isinstance(e, str) and e.strip()]}
    for section in SECTIONS:
        out[section] = [i for i in data.get(section) or [] if _valid(section, i)]
    return out


def load(path: Path | None = None) -> dict:
    path = Path(path or ENRICHMENT_PATH)
    try:
        return normalize(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return normalize({})


def save(data: dict, path: Path | None = None) -> None:
    path = Path(path or ENRICHMENT_PATH)
    write_text_atomic(path, json.dumps(normalize(data), indent=1, ensure_ascii=False) + "\n", new_file_mode=PRIVATE_FILE_MODE)


def evidence_items(enrichment: dict | None) -> list[dict]:
    """(source, role, period, text, negative) dicts for the evidence index, in file order: domains, history, boundaries."""
    data = normalize(enrichment)
    items = [{"source": "example", "role": None, "period": None, "text": d["text"], "negative": False} for d in data["domains"]]
    items += [{"source": "role", "role": h["role"], "period": h["period"], "text": h["text"], "negative": False} for h in data["history"]]
    items += [{"source": "fact", "role": None, "period": None, "text": b["text"], "negative": b["stance"] == "none"} for b in data["boundaries"]]
    return items
