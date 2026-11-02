#!/usr/bin/env python3
"""Multi-provider job discovery runner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dedupe_jobs import _crosspost_key, dedupe_jobs  # noqa: E402
from discovery_common import (  # noqa: E402
    INTELLIGENCE_PATH,
    load_intelligence,
    resolve_search_config,
)
from export_jobs import (  # noqa: E402
    export_discovered_json,
    export_normalized_json,
    export_raw_csv,
)
from providers.jobspy_provider import JobSpyProvider  # noqa: E402
from providers.provider_registry import PROVIDER_GROUPS, get_provider, resolve_providers  # noqa: E402
import source_settings  # noqa: E402

# The ledger lives beside the scorer's shared modules; it is loaded by path so
# that module's siblings do not shadow this package's.
_history_spec = importlib.util.spec_from_file_location(
    "job_history", SCRIPT_DIR.parent / "job_scoring" / "job_history.py"
)
job_history = importlib.util.module_from_spec(_history_spec)
_history_spec.loader.exec_module(job_history)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multi-provider job discovery.")
    parser.add_argument(
        "--providers",
        default="serbia",
        help=(
            "Comma-separated provider names or group: "
            f"{', '.join(PROVIDER_GROUPS)}"
        ),
    )
    parser.add_argument(
        "--country",
        help="Country filter. Overrides the country in the candidate intelligence.",
    )
    parser.add_argument(
        "--locations",
        nargs="+",
        help="Location filters. Overrides intelligence locationFilters.",
    )
    parser.add_argument(
        "--intelligence",
        type=Path,
        default=INTELLIGENCE_PATH,
        help="Path to candidate-intelligence.json",
    )
    return parser.parse_args()


def effective_provider_names(spec: str | None) -> list[str]:
    """The providers this run uses: the request, with the owner's opt-in switches applied.

    The switches in data/config/sources.json are the gate, not the request: an opt-in
    source that is off never runs, even when the request names it.
    """
    try:
        settings = source_settings.read()
    except source_settings.SourcesError as exc:
        logger.warning("Source settings unusable (%s); every opt-in source is off for this run", exc)
        settings = None
    names, dropped = source_settings.effective_providers(spec, resolve_providers(spec), settings)
    for name in dropped:
        logger.warning("Skipping %s: an opt-in source that is off; %s", name, source_settings.OFF_HINT)
    return names


def main() -> int:
    args = parse_args()
    source_run_id = uuid.uuid4().hex[:12]

    intelligence = load_intelligence(args.intelligence)
    try:
        config = resolve_search_config(
            intelligence,
            country=args.country,
            locations=args.locations,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    search_terms = config["search_terms"]
    locations = config["locations"]
    remote_filters = config["remote_filters"]
    country = config["country"]

    if not search_terms:
        logger.error("No jobSpySearchTerms found in intelligence file.")
        return 1

    provider_names = effective_provider_names(args.providers)
    if not provider_names:
        logger.error("No valid providers resolved from: %s", args.providers)
        return 1

    all_jobs: list[dict] = []
    provider_counts: dict[str, int] = {}
    failed_boards: dict[str, set[str] | None] = {}
    raw_df = pd.DataFrame()

    for name in provider_names:
        logger.info("Running provider: %s", name)
        provider = get_provider(name)
        jobs = provider.fetch_jobs(search_terms, locations, remote_filters, country)
        provider_counts[name] = len(jobs)
        all_jobs.extend(jobs)
        logger.info("Provider %s returned %d jobs", name, len(jobs))
        if provider.failed_boards:
            failed_boards[name] = set(provider.failed_boards)
            logger.warning("Provider %s could not read: %s", name, ", ".join(provider.failed_boards))

        if name == "jobspy" and isinstance(provider, JobSpyProvider):
            raw_df = provider.last_raw_df

    raw_count = len(all_jobs)

    deduped = dedupe_jobs(all_jobs)
    found_count = len(deduped)

    # Facts from the file this run replaces seed a ledger that has not seen the
    # jobs yet, so a first run on an existing install keeps what enrichment read.
    jobs_file = ROOT / "data" / "jobs" / "discovered_jobs.json"
    previous_facts: dict[str, dict] = {}
    seen_before: dict[str, str] = {}
    if jobs_file.exists():
        try:
            previous = json.loads(jobs_file.read_text(encoding="utf-8"))
            previous_jobs = previous.get("jobs") if isinstance(previous, dict) else previous
            previous_facts = {
                j["jobId"]: j["llmFacts"] for j in previous_jobs or [] if j.get("jobId") and j.get("llmFacts")
            }
            written = (previous.get("meta") or {}).get("generatedAt") if isinstance(previous, dict) else None
            seen_before = {j["jobId"]: written for j in previous_jobs or [] if j.get("jobId") and written}
        except (OSError, ValueError):
            previous_facts = {}

    ledger_file = job_history.ledger_path(jobs_file)
    ledger = job_history.load(ledger_file)
    to_write, history_stats = job_history.apply_run(
        ledger,
        deduped,
        now=job_history.now_iso(),
        providers_returned=provider_counts,
        key=job_history.search_key(search_terms, locations, country, remote_filters),
        role_key=_crosspost_key,
        previous_facts=previous_facts,
        seen_before=seen_before,
        failed_boards=failed_boards,
    )
    job_history.save(ledger_file, ledger)

    export_raw_csv(raw_df, ROOT)
    export_normalized_json(all_jobs, ROOT)
    discovered_path = export_discovered_json(
        to_write,
        ROOT,
        search_terms=search_terms,
        locations=locations,
        remote_filters=remote_filters,
        raw_count=raw_count,
        country=country,
        source_run_id=source_run_id,
        providers=provider_names,
        provider_counts=provider_counts,
        deduped_count=found_count,
        history=history_stats,
    )

    print("")
    print("===================================")
    print("MULTI-PROVIDER DISCOVERY SUMMARY")
    print("===================================")
    print("")
    print("Providers:", ", ".join(provider_names))
    print("Country:", country)
    print("Search Terms:", ", ".join(search_terms))
    print("Locations:", ", ".join(locations))
    print("Remote Filters:", ", ".join(remote_filters))
    print("")
    for name in provider_names:
        print(f"  {name}: {provider_counts.get(name, 0)} jobs")
    print("")
    print(f"Raw Jobs: {raw_count}")
    print(f"Deduped Jobs: {found_count}")
    print(f"Duplicates Removed: {max(0, raw_count - found_count)}")
    print("")
    print("Job history:")
    print(f"  new {history_stats['new']}, already known {history_stats['known']}, "
          f"reopened {history_stats['reopened']}, closed this run {history_stats['closed']}")
    print(f"  facts carried over {history_stats['carriedFacts']}, "
          f"ads changed since last run {history_stats['changed']}, "
          f"fuller description kept over a throttled one {history_stats['keptFullerDescription']}")
    print(f"  ads of unread boards kept open: {history_stats['keptFailedBoard']}")
    closed_written = len(to_write) - found_count - history_stats["keptFailedBoard"]
    print(f"  jobs written: {len(to_write)} ({closed_written} closed, kept {job_history.CLOSED_KEEP_DAYS} days)")
    print("")
    print(f"Output: {discovered_path.relative_to(ROOT)}")
    print("===================================")
    print("")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
