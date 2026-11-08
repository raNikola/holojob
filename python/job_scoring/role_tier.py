"""The role-family config read by scoring (src/data/roleFamilies.json), and the vocabulary it holds for titles.

A family without a `titleRules` entry has no vocabulary: nothing about a title is decided for it.
"""

from __future__ import annotations

import json
from pathlib import Path

from text_utils import normalize_text

ROLE_FAMILIES_FILE = Path(__file__).resolve().parents[2] / "src" / "data" / "roleFamilies.json"
ROLE_FAMILIES = json.loads(ROLE_FAMILIES_FILE.read_text(encoding="utf-8"))


def title_rules(family: str | None) -> dict:
    """The family's title vocabulary; empty for no family or a family that has none."""
    return (ROLE_FAMILIES.get(family) or {}).get("titleRules") or {} if family else {}


def names_another_job(title: str, family: str | None) -> bool:
    """A target phrase inside a title for another function: "Head of Product Marketing" holds "head of product"."""
    normalized = normalize_text(title)
    return any(phrase in normalized for phrase in title_rules(family).get("notTargetPhrases") or [])
