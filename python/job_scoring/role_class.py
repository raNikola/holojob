"""Role class stamp (Fit 3, production): `roleClass` / `roleName` on scored rows, from the stored classification in data/cache/fit3.json.

Badge, filter and (1.6) the role ceiling of ceilings.py: nothing here orders or calls a model. Every path that scores rows (a full run, a manual job, a kept ad's Re-score) calls
`label` before scoring and `ceiling` after it (1.7), so a row is the same whichever path wrote it. The classification key carries the prompt version, so the lookup runs under the frozen candidate i1
(`fit3.PRODUCTION_CANDIDATE`); a prompt change needs a new classification run.
"""

from __future__ import annotations

import json
import sys

import ceilings

from match_engine import fit3, shadow


def store_path():
    """fit3.json next to the engine cache (the shadow's own rule), read at call time so a test that moves the cache moves this too."""
    return shadow.CACHE_PATH.with_name("fit3.json")


def label(rows: list[dict], path=None) -> dict[str, int]:
    """Stamp `roleClass` / `roleName` on every row, BEFORE scoring (1.7: the scorer's gate and caps read the class). No store or an unreadable one means
    every ad is "not available". Returns the counts per class."""
    path = path or store_path()
    store = None
    if path.exists():
        try:
            store = (json.loads(path.read_text(encoding="utf-8")) or {}).get("entries") or {}
        except (OSError, ValueError) as exc:
            print(f"role class: fit3.json unreadable ({type(exc).__name__}), every ad is 'not available'", file=sys.stderr)
    with fit3.production_candidate():
        return fit3.role_labels(rows, store, fit3.load_roles(), fit3.closed_competencies("product"))


def ceiling(scored: list[dict]) -> int:
    """Scoring 1.6: a class of other / not available caps the Fit Score at Weak. Runs AFTER scoring (it caps the finished score). Returns rows lowered."""
    return ceilings.apply_role_ceiling(scored)
