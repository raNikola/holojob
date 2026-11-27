#!/usr/bin/env python3
"""Package 3 round-1 measurement: the title filter before and after round 1, replayed on the must-keep set and the ledger.

Round 1 (owner plan 2026-11-25): seniority words left the exclude list (labels only), and a title miss goes to a free-text check on
the ad's text (an empty text continues, never drops). "Before" is the same Settings vocabulary plus the four seniority words it held,
title only (no text check); "after" is `role_filter.assess` with the text the ledger holds for the ad.

No model call, no network, no write: real data is read-only. Output: counts, ids and public ad titles only.
Usage: .venv/bin/python scripts/measure_package3.py [--examples N]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DATA = Path("/srv/holojob/data")
OLD_SENIORITY_EXCLUDES = ("junior", "intern", "praktikant", "pripravnik")  # the default exclude entries round 1 removed

# The production Settings file (read only); without one the defaults apply, as in production.
os.environ.setdefault("HOLOJOB_AI_DIR", str(REAL_DATA / "ai"))
sys.path.insert(0, str(ROOT / "python" / "job_discovery" / "providers"))
sys.path.insert(0, str(ROOT / "python" / "llm"))
sys.path.insert(0, str(ROOT / "python" / "job_discovery"))
import role_filter as rf  # noqa: E402
import staging  # noqa: E402

FILTERED_SOURCES = ("jobspy", "workable", "infostud", "joberty")  # the providers that call role_filter


def _read(rel: str) -> dict:
    path = REAL_DATA / rel
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def must_keep() -> tuple[dict[str, set], str]:
    """{id: {"saved"|"rejected"|"applied"}}: Saved and Rejected from job-state.json, Applied from HOLOJOB_APPLICATION_JOB_IDS."""
    out: dict[str, set] = {}
    for key, value in (_read("jobs/job-state.json").get("jobs") or {}).items():
        if value.get("status") in ("saved", "rejected"):
            out.setdefault(str(value.get("jobId") or key), set()).add(value["status"])
    path = os.environ.get("HOLOJOB_APPLICATION_JOB_IDS")
    note = "applied ids: not available (HOLOJOB_APPLICATION_JOB_IDS unset)"
    if path and Path(path).exists():
        applied = {ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()}
        for job_id in applied:
            out.setdefault(job_id, set()).add("applied")
        note = f"applied ids read: {len(applied)}"
    return out, note


def before(title: str, position: str, terms: tuple = ()) -> str | None:
    """The drop reason of the filter before round 1: the seniority words in exclude, title only."""
    vocab = rf.vocabulary()
    old = dataclasses.replace(vocab, exclude=(*vocab.exclude, *(w for w in OLD_SENIORITY_EXCLUDES if w not in vocab.exclude)))
    saved = rf.vocabulary
    rf.vocabulary = lambda: old
    try:
        return rf.assess(title, position, terms, None).reason
    finally:
        rf.vocabulary = saved


def after(title: str, position: str, text: str | None, terms: tuple = ()) -> rf.Decision:
    return rf.assess(title, position, terms, text)


def run_folders(limit: int) -> list[Path]:
    staging = REAL_DATA / "jobs" / "staging"
    return sorted((p for p in staging.iterdir() if p.is_dir()), key=lambda p: p.name)[-limit:] if staging.is_dir() else []


def search_terms() -> tuple:
    """The search terms of the latest jobspy staging header (the provider passes them to the title filter)."""
    for folder in reversed(run_folders(50)):
        stage = staging.read_source(folder / "jobspy.jsonl") if (folder / "jobspy.jsonl").exists() else None
        if stage and stage.header and stage.header.get("terms"):
            return tuple(stage.header["terms"])
    return ()


def outcome(decision: rf.Decision) -> str:
    if decision.reason:
        return f"drop:{decision.reason.split(':')[0]}"
    return {None: "keep:title", rf.SOFT: "keep:text_match", rf.UNKNOWN: "keep:no_text"}[decision.rule]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples", type=int, default=5)
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()

    ledger = _read("jobs/job_history.json").get("jobs") or {}
    filtered = _read("jobs/filtered_ads.json").get("ads") or {}
    manual = _read("jobs/manual_jobs.json")
    manual_ids = {str(j.get("jobId") or j.get("id")) for j in (manual.get("jobs") if isinstance(manual, dict) else manual) or []
                  if isinstance(j, dict)}
    keep, note = must_keep()
    vocab = rf.vocabulary()
    print(f"vocabulary: include {len(vocab.include)}, near {len(vocab.near)}, exclude {len(vocab.exclude)} "
          f"(settings file {'present' if rf.ai_gate.settings_path().exists() else 'absent: defaults'})")
    print(f"must-keep ids: {len(keep)} ({Counter(s for v in keep.values() for s in v)}); {note}")

    # 1. The must-keep set.
    where = Counter()
    table = Counter()
    lost, gained = [], []
    labels = Counter()
    for job_id, statuses in sorted(keep.items()):
        entry = ledger.get(job_id)
        if entry is None:
            where["manual (no role filter)" if job_id in manual_ids else "filtered_ads only" if job_id in filtered else "not found"] += 1
            continue
        where["ledger"] += 1
        job = entry.get("job") or {}
        title, position = job.get("title") or "", job.get("standardizedPosition") or ""
        old = before(title, position)
        new = after(title, position, job.get("description") or "")
        table[("drop" if old else "keep", outcome(new))] += 1
        labels.update(new.labels)
        if new.reason and not old:
            lost.append((job_id, sorted(statuses), job.get("provider"), title, new.reason))
        if old and not new.reason:
            gained.append((job_id, sorted(statuses), job.get("provider"), title, old))
    print("\n1. must-keep set")
    print("   where found:", dict(where))
    print("   before -> after (ledger ads):", {f"{a} -> {b}": n for (a, b), n in sorted(table.items())})
    print("   labels after:", dict(labels))
    print(f"   kept before, dropped after (STOP RULE if > 0): {len(lost)}")
    for row in lost:
        print("     ", row)
    print(f"   dropped before, kept after: {len(gained)}")
    for row in gained[: args.examples]:
        print("     ", row)

    # 2. The ledger ads of the sources that run the title filter, with the search terms they pass (a title holding one is Near).
    # Greenhouse and Ashby never call role_filter: their ads are left out (a replay of them would only show artifacts).
    terms = search_terms()
    table = Counter()
    by_provider = Counter()
    examples: dict[str, list] = {}
    include_only = 0
    skipped = Counter()
    for job_id, entry in ledger.items():
        job = entry.get("job") or {}
        if job.get("provider") not in FILTERED_SOURCES:
            skipped[job.get("provider")] += 1
            continue
        title, position = job.get("title") or "", job.get("standardizedPosition") or ""
        old = before(title, position, terms)
        new = after(title, position, job.get("description") or "", terms)
        key = ("drop" if old else "keep", outcome(new))
        table[key] += 1
        if new.rule == rf.SOFT and any(rf._has_phrase(rf._fold(job.get("description") or ""), t) for t in vocab.include):
            include_only += 1
        if key[0] != key[1].split(":")[0]:
            by_provider[(f"{key[0]} -> {key[1]}", job.get("provider"))] += 1
            examples.setdefault(f"{key[0]} -> {key[1]}", []).append(title)
    print(f"\n2. ledger ads of the title-filtered sources: {sum(table.values())} (search terms {len(terms)}; "
          f"left out, no title filter: {dict(skipped)})")
    print("   before -> after:", {f"{a} -> {b}": n for (a, b), n in sorted(table.items())})
    print("   changed, by provider:", {f"{a} [{p}]": n for (a, p), n in sorted(by_provider.items(), key=str)})
    print(f"   text matches that an include-only text check would also keep: {include_only}")
    for change, titles in sorted(examples.items()):
        print(f"   examples {change}: {titles[: args.examples]}")

    # 3. filtered_ads.json: dropped sightings. They keep no text, so the text check is bounded: no text at all (title only,
    # the drop as before) and an empty text (unknown: continues).
    reasons = Counter((r.get("reason") or "").split(":")[0] if not (r.get("reason") or "").startswith("title_excluded")
                      else r.get("reason") for r in filtered.values())
    print(f"\n3. filtered records: {len(filtered)}; reasons: {dict(reasons.most_common())}")
    seniority = [r for r in filtered.values() if r.get("reason") in {f"title_excluded:{w}" for w in OLD_SENIORITY_EXCLUDES}]
    lower = Counter(outcome(after(r.get("title") or "", "", None)) for r in seniority)
    upper = Counter(outcome(after(r.get("title") or "", "", "")) for r in seniority)
    print(f"   seniority drops: {len(seniority)}; title-only replay now: {dict(lower)}; with an empty text: {dict(upper)}")
    print(f"   examples: {[r.get('title') for r in seniority][: args.examples]}")
    misses = sum(1 for r in filtered.values() if r.get("reason") == "title_not_matched")
    print(f"   title_not_matched records: {misses} (each now goes to the text check on the text its source has; not replayable here)")

    # 4. What "an empty text continues" can cost per run: per source, the title misses dropped per run, and the share of the ads
    # it kept that had no description in staging. Their product bounds the extra ads a run sends on (upper bound: it assumes
    # a title miss is as often empty as a kept ad). Joberty judges a miss on its detail, so each miss costs one detail request.
    print(f"\n4. last {args.runs} staged runs, per title-filtered source")
    totals = {s: Counter() for s in FILTERED_SOURCES}
    for folder in run_folders(args.runs):
        discards = staging.read_discards(folder / staging.DISCARDS) if (folder / staging.DISCARDS).exists() else None
        for source in FILTERED_SOURCES:
            path = folder / f"{source}.jsonl"
            if not path.exists():
                continue
            jobs = staging.read_source(path).jobs
            t = totals[source]
            t["runs"] += 1
            t["kept"] += len(jobs)
            t["keptEmpty"] += sum(1 for j in jobs if not (j.get("description") or "").strip())
            if discards is not None:
                t["titleMisses"] += sum(1 for r in discards.by_source(source) if r["reason"] == "title_not_matched")
                t["seniorityDrops"] += sum(1 for r in discards.by_source(source)
                                           if r["reason"] in {f"title_excluded:{w}" for w in OLD_SENIORITY_EXCLUDES})
    for source, t in totals.items():
        if not t["runs"]:
            print(f"   {source}: no staged run")
            continue
        share = t["keptEmpty"] / t["kept"] if t["kept"] else 0.0
        per_run = t["titleMisses"] / t["runs"]
        print(f"   {source}: runs {t['runs']}, kept {t['kept']} (empty description {t['keptEmpty']}, {share:.1%}), "
              f"title misses {t['titleMisses']} ({per_run:.1f}/run), seniority drops {t['seniorityDrops']}; "
              f"bound on extra 'no_text' ads per run ~{per_run * share:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
