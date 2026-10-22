"""Shared discovery configuration loaders."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"


def load_intelligence(path: Path | None = None) -> dict:
    intel_path = path or INTELLIGENCE_PATH
    if not intel_path.exists():
        raise FileNotFoundError(
            f"Intelligence file not found: {intel_path}\n"
            "Export candidate-intelligence.json from Module 2 and save it there."
        )
    return json.loads(intel_path.read_text(encoding="utf-8"))


def should_use_remote(remote_filters: list[str], location: str) -> bool:
    loc = (location or "").lower()
    if loc == "remote":
        return True
    filters = [f.lower() for f in remote_filters]
    return "remote" in filters and loc == "remote"


def resolve_search_config(intelligence: dict, *, country: str | None, locations: list[str] | None) -> dict:
    """The search settings: the flags first, then the candidate's own intelligence.

    There is no default country. One that was not given, or not in the
    candidate's intelligence, is an error: a hard-coded market would search
    the wrong one without saying so.
    """
    strategy = intelligence.get("searchStrategy") or {}
    job_fit = intelligence.get("jobFitPreferences") or {}

    resolved_country = country or strategy.get("country") or job_fit.get("country")
    if not resolved_country:
        raise ValueError(
            "No country to search: pass --country, or set searchStrategy.country "
            "or jobFitPreferences.country in the candidate intelligence."
        )

    return {
        "search_terms": strategy.get("jobSpySearchTerms") or [],
        "locations": locations or strategy.get("locationFilters") or ["Remote"],
        "remote_filters": strategy.get("remoteFilters") or [],
        "country": resolved_country,
    }
