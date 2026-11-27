#!/usr/bin/env python3
"""Facts shown beside an ad that are worked out when they are read (list-cleanup, owner brief 2026-11-27): the package 4 text labels and the
package 7 repost count. Nothing here is stored, scores or filters: no ledger field, no score input, no row is dropped or collapsed.

  labels   the text rules of `text_rules.py` (language, years, on-site only, visa, employment type) run over the EFFECTIVE description, that is
           the owner's pasted or refreshed text when the ad has an overlay entry, else the scraped text (`description_overlay.effective`).
           A hand-entered job is never overlaid, and its notes and extra links are never read.
  reposts  `repost_counter.count_reposts` over the ledger; a posting's count is the number of OTHER postings of its group. The window is
           Settings `repostWindowDays` (`source_settings.repost_window`), read from the sources file of the given root.

  job_derived.py --root ROOT --job-id ID    prints {"ok": true, "jobId", "labels": [...], "labelsFrom", "repostCount"}; exit 0, or 3 with {"ok": false, "message"}

Stdlib only; the helper modules are loaded by file path, as `all_ads.py` loads `stale_rule.py`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    """Load a helper by file path without leaving a bytecode file beside it: the list route promises that it writes nothing."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return module


description_overlay = _load("_derived_description_overlay", _HERE / "description_overlay.py")
repost_counter = _load("_derived_repost_counter", _HERE / "repost_counter.py")
text_rules = _load("_derived_text_rules", _HERE.parent / "job_discovery" / "providers" / "text_rules.py")
source_settings = _load("_derived_source_settings", _HERE.parent / "job_discovery" / "source_settings.py")

EXIT_UNREADABLE = 3


def sources_file(root: Path) -> Path:
    """The sources file by the precedence `source_settings.sources_path` uses, with `root` in place of the code's own root."""
    explicit = os.environ.get("HOLOJOB_SOURCES")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("HOLOJOB_CONFIG_DIR") or Path(root) / "data" / "config") / "sources.json"


def repost_window_days(root: Path) -> int:
    """Settings `repostWindowDays`, else the default; an unreadable or missing file gives the default."""
    try:
        data = json.loads(sources_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    return source_settings.repost_window(data if isinstance(data, dict) else None)


def repost_counts(entries: dict, window_days: int) -> dict:
    """{jobId: number of other postings of its group}; an ad outside every group is not in the map."""
    return repost_counter.count_reposts(entries, window_days=window_days)["repostsOf"]


def labels_of(job: dict, overlay: dict | None) -> tuple[list[dict], str]:
    """([{rule, class, label}], where the text came from) for one ad, from its effective description. Pure: nothing is written back."""
    effective = description_overlay.effective(job, overlay or {})
    text = effective.get("description")
    fired = text_rules.evaluate(text_rules.fold(text if isinstance(text, str) else ""))
    source = effective.get("descriptionSource") if effective is not job else None
    return [{"rule": rule, "class": rule_class, "label": label} for rule, rule_class, label in fired], source or "scraped"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path.name} cannot be read ({type(exc).__name__})") from exc


def derived(root: Path, job_id: str) -> dict:
    """The answer for one ad. The ad is the ledger's, else the scored list's (a hand-entered job is there). Raises ValueError when a file is unreadable."""
    jobs_dir = Path(root) / "data" / "jobs"
    ledger = _read_json(jobs_dir / "job_history.json")
    entries = ledger.get("jobs") if isinstance(ledger, dict) and isinstance(ledger.get("jobs"), dict) else {}
    entry = entries.get(job_id)
    job = entry.get("job") if isinstance(entry, dict) and isinstance(entry.get("job"), dict) else None
    if job is None:
        scored = _read_json(jobs_dir / "scored_jobs.json")
        job = next((j for j in (scored or {}).get("jobs", []) if isinstance(j, dict) and j.get("jobId") == job_id), None)
    if job is None:
        return {"ok": True, "jobId": job_id, "known": False, "labels": [], "labelsFrom": None, "repostCount": 0}
    overlay = description_overlay.load(description_overlay.path_for(jobs_dir / "scored_jobs.json"))
    labels, source = labels_of({**job, "jobId": job_id}, overlay)
    count = repost_counts(entries, repost_window_days(root)).get(job_id, 0) if entry else 0
    return {"ok": True, "jobId": job_id, "known": True, "labels": labels, "labelsFrom": source, "repostCount": count}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    try:
        answer = derived(args.root, args.job_id)
    except ValueError as exc:
        print(json.dumps({"ok": False, "message": str(exc)}))
        return EXIT_UNREADABLE
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
