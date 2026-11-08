"""The shape of `lastImport.meta` (Wave 4, n): one function builds it, one function checks it.

`meta` v2 keeps every key v1 had (the view and the lifecycle code read them) and adds:

  metaVersion  2
  kind         "full": only a complete-plan import writes `lastImport`; a cancelled run writes `lastPartial` instead
  sources      one row per source of the run: name, state, readClass, read, kept, reportedTotal, proven, why
  filterReasons  per source, how many ads its filters dropped by reason (`title_not_matched`, ...). Counts only.

A v1 meta (no `metaVersion`) stays valid and is read as it is; nothing is migrated. Nothing here makes a lifecycle decision.
"""

from __future__ import annotations

META_VERSION = 2
KIND_FULL = "full"

# Keys the view (`view_guard.view_payload`) and `all_ads` need. A ledger whose meta lacks one is not usable as a view.
REQUIRED_KEYS = ("searchTerms", "locations", "remoteFilters", "country", "providers", "providerCounts", "rawCount", "dedupedCount", "history", "sourceRunId")


def source_row(name: str, state: str, footer: dict | None, proof_row: dict | None) -> dict:
    """One source of the run, as `meta.sources` keeps it. Reads the staging footer and the importer's proof; decides nothing."""
    footer = footer or {}
    why = list((proof_row or {}).get("why") or [])
    return {
        "name": name,
        "state": state,
        "readClass": footer.get("readClass"),
        "read": footer.get("read"),
        "kept": footer.get("kept"),
        "reportedTotal": footer.get("total"),
        "proven": bool((proof_row or {}).get("proven")),
        "why": why[:5],
    }


def build_import_meta(
    manifest: dict, providers: list[str], provider_counts: dict, raw_count: int, deduped_count: int, history: dict,
    run_id: str, sources: list[dict], filter_reasons: dict,
) -> dict:
    return {
        "metaVersion": META_VERSION,
        "kind": KIND_FULL,
        "searchTerms": manifest.get("terms") or [],
        "locations": manifest.get("locations") or [],
        "remoteFilters": manifest.get("remoteFilters") or [],
        "country": manifest.get("country") or "",
        "providers": providers,
        "providerCounts": provider_counts,
        "rawCount": raw_count,
        "dedupedCount": deduped_count,
        "history": history,
        "sourceRunId": run_id,
        "sources": sources,
        "filterReasons": {name: dict(reasons) for name, reasons in (filter_reasons or {}).items()},
    }


def missing_keys(meta) -> list[str]:
    """The required keys a meta lacks (all of them when it is not a dict). Empty means usable. v1 and v2 pass alike."""
    if not isinstance(meta, dict):
        return list(REQUIRED_KEYS)
    return [key for key in REQUIRED_KEYS if key not in meta]


def build_last_partial(run_id: str, at: str, reason: str, saved: int) -> dict:
    """`ledger.lastPartial`: the latest cancelled run that was imported, kept apart from `lastImport` so no lifecycle code sees it."""
    return {"runId": run_id, "at": at, "reason": reason, "saved": int(saved or 0)}
