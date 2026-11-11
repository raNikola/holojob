"""What applying an import would do to the things that depend on the profile (Wave 7, confirm screen).

Read-only and local: no model, no network, nothing written. The answer holds counts, the two profile versions (16 hex characters) and flags;
no profile text, no job text, no file name. `profileVersion` is computed by the same code the scorer and the matcher use
(job_scoring.evidence_index). An import changes neither the confirmed facts nor the gates, so "changes: no" means every cached matcher answer still matches.

Which cache depends on what (docs/DECISIONS.md, Wave 7):
  - matcher cache (data/cache/engine.json): the key holds evidenceVersion, so any change of the evidence misses every entry;
  - fit judge cache: the intelligence digest, not the profile: unchanged until the intelligence is regenerated;
  - job-analysis findings (data/ai/findings/job): a hash that includes a profile summary; they may miss when those fields change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for part in ("python", "python/job_scoring"):
    if str(ROOT / part) not in sys.path:
        sys.path.insert(0, str(ROOT / part))

from evidence_index import build_candidate  # noqa: E402

ENGINE_CACHE = ROOT / "data" / "cache" / "engine.json"
INTELLIGENCE = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
FINDINGS_JOBS = ROOT / "data" / "ai" / "findings" / "job"

# What the browser AI features' profile summary is built from (profile fields only; the intelligence is separate).
_SUMMARY_FIELDS = ("currentRole", "experienceYears", "targetRoles", "preferredLocations")


def _summary_inputs(profile: dict) -> dict:
    basic = (profile or {}).get("basicProfile") or {}
    parsed = ((profile or {}).get("resume") or {}).get("parsedData") or {}
    return {**{f: basic.get(f) for f in _SUMMARY_FIELDS}, "skills": parsed.get("skills")}


def matcher_versions(keys) -> dict[str, int]:
    """Entries per evidenceVersion, from the cache key names only (`ad:evidenceVersion:prompt:...`)."""
    counts: dict[str, int] = {}
    for key in keys:
        parts = str(key).split(":")
        if len(parts) > 2:
            counts[parts[1]] = counts.get(parts[1], 0) + 1
    return counts


def profile_impact(before: dict, after: dict, intelligence: dict, facts: list, cache_keys=(), findings_count: int = 0) -> dict:
    """Pure: the impact of replacing profile `before` by `after`. The caller supplies what it read from disk."""
    cand_before = build_candidate(before, intelligence, facts)
    cand_after = build_candidate(after, intelligence, facts)
    ids_before = {e["id"] for e in cand_before["evidence"]}
    ids_after = {e["id"] for e in cand_after["evidence"]}
    changed = cand_before["profileVersion"] != cand_after["profileVersion"]
    versions = matcher_versions(cache_keys)
    evidence_before, evidence_after = cand_before["evidenceVersion"], cand_after["evidenceVersion"]
    evidence_changed = evidence_before != evidence_after
    summary_changed = _summary_inputs(before) != _summary_inputs(after)
    return {
        "profileVersion": {"before": cand_before["profileVersion"], "after": cand_after["profileVersion"], "changed": changed},
        "evidence": {
            "before": len(ids_before), "after": len(ids_after),
            "added": len(ids_after - ids_before), "removed": len(ids_before - ids_after),
        },
        "matcher": {
            "entriesTotal": sum(versions.values()),
            "matchingNow": versions.get(evidence_before, 0),
            "stopMatching": versions.get(evidence_before, 0) if evidence_changed else 0,
            "alreadyMatchingAfter": versions.get(evidence_after, 0) if evidence_changed else 0,
        },
        "judge": {"changes": False},
        "findings": {"stored": findings_count, "mayMiss": summary_changed},
    }


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def impact_from_disk(before: dict, after: dict) -> dict:
    """The same, reading the intelligence, the confirmed facts and the cache key names from data/ (read only)."""
    from confirmed_facts import load as load_confirmed_facts  # noqa: E402

    intelligence = _read_json(INTELLIGENCE, {})
    cache = _read_json(ENGINE_CACHE, {})
    try:
        findings = sum(1 for p in FINDINGS_JOBS.iterdir() if p.suffix == ".json")
    except OSError:
        findings = 0
    return profile_impact(before, after, intelligence if isinstance(intelligence, dict) else {}, load_confirmed_facts(),
                          cache.keys() if isinstance(cache, dict) else (), findings)
