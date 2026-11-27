#!/usr/bin/env python3
"""List-cleanup brief, measurements B1, B2 and B4 (B3 is `scripts/measure-list-cleanup-order.js`, the server's own list code).

  B1  Per package 4 label (visa, language, on-site only, employment type, years): how many ads that carry it reached paid reading, and
      the paid share. "Paid reading" is the state the data holds now: enrichment (the ledger entry has `llmFacts`), the evidence engine
      (the scored row's `engineCoverage` is `answered`: the matcher and the engine fill write the same answer, so they cannot be told apart
      afterwards) and Fit 3 (the scored row has a role class). The population is the ads the latest runs found.
  B2  The owner's statuses (Saved, Rejected from job-state.json; Applied = an application with the ad's job id) against each label.
  B4  On the latest scan day: the ads package 3 lets in that the previous rules dropped (seniority no longer dropped; a title miss kept by the
      text check or by an empty text), and how many of them are in the scored list, open, and reached paid reading.

A label is the one `role_filter.assess` gives on the ad's effective text (the owner's pasted / employer text when there is one, else the ledger's).
Labels are not stored on the ledger, so they are recomputed here. Unknown stays unknown: an ad that is not in the scored list has no engine or
Fit 3 state and is counted as "not in the scored list", never as "not read".

No model call, no network, no write, no copy of data: real data is opened in place, read only. Output: counts, ids, label names only.
Usage: .venv/bin/python scripts/measure_list_cleanup.py [--runs N] [--day YYYY-MM-DD]
Pattern: scripts/measure_package3.py (imported for the filter set-up and the old-rule replay).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_package3 as m3  # noqa: E402  (sets HOLOJOB_AI_DIR to the real Settings, read only, and the import paths)

sys.path.insert(0, str(m3.ROOT / "python" / "job_scoring"))
import description_overlay  # noqa: E402

rf = m3.rf
RULES = ("visa", "language", "onsite", "employment", "years")
NOT_SCORED = "not in the scored list"


def applied_ids() -> set[str]:
    """Job ids of the applications (read in place; only the ids are taken)."""
    apps = (m3._read("applications/applications.json").get("applications") or {}).values()
    return {a["posting"]["jobId"] for a in apps if isinstance(a, dict) and isinstance(a.get("posting"), dict) and a["posting"].get("jobId")}


def statuses() -> dict[str, set]:
    out: dict[str, set] = defaultdict(set)
    for key, value in (m3._read("jobs/job-state.json").get("jobs") or {}).items():
        if value.get("status") in ("saved", "rejected"):
            out[str(value.get("jobId") or key)].add(value["status"])
    for job_id in applied_ids():
        out[job_id].add("applied")
    return out


def label_names(labels: tuple) -> set[str]:
    """The package 4 labels of a decision, as rule names and sub-labels (visa:no_sponsorship, employment:contract, ...)."""
    out: set[str] = set()
    for label in labels:
        rule = label.split(":")[0]
        if rule in RULES:
            out.add(rule)
            if rule in ("visa", "onsite", "employment"):
                out.add(label)
    return out


def paid_state(entry: dict, scored: dict | None) -> dict:
    """{step: True/False/None}: None is unknown (the ad is not in the scored list, so there is no engine or role class to read)."""
    enrich = bool(entry.get("llmFacts"))
    if scored is None:
        engine = fit3 = None
    else:
        engine = (scored.get("engineCoverage") or {}).get("status") == "answered"
        fit3 = scored.get("roleClass") not in (None, "not available")
    known = [v for v in (enrich, engine, fit3) if v is not None]
    return {"enrichment": enrich, "engine": engine, "fit3": fit3, "any": any(known), "complete": scored is not None}


def table(title: str, header: list[str], rows: list[list]) -> None:
    print(f"\n{title}")
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for r in [header, *rows]:
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3, help="how many of the latest runs make the 'latest runs' population (by last sighting)")
    parser.add_argument("--day", help="scan day for B4 (default: the latest lastSeen day of an ad of a title-filtered source)")
    args = parser.parse_args()

    ledger_doc = m3._read("jobs/job_history.json")
    ledger = ledger_doc.get("jobs") or {}
    scored = {r["jobId"]: r for r in (m3._read("jobs/scored_jobs.json").get("jobs") or []) if isinstance(r, dict) and r.get("jobId")}
    overlay = description_overlay.load(m3.REAL_DATA / "jobs" / "pasted_descriptions.json")
    terms = m3.search_terms()
    print(f"ledger ads {len(ledger)}, scored rows {len(scored)}, owner-text overlay entries {len(overlay)}, search terms {len(terms)}")

    def decision(entry: dict):
        job = description_overlay.effective({**(entry.get("job") or {})}, overlay)
        return rf.assess(job.get("title") or "", job.get("standardizedPosition") or "", terms, job.get("description") or "")

    # --- the latest runs: runs ordered by the last sighting of any of their ads
    last_seen_of_run: dict[str, str] = {}
    for entry in ledger.values():
        run = entry.get("lastRunId")
        if run:
            last_seen_of_run[run] = max(last_seen_of_run.get(run, ""), str(entry.get("lastSeen") or ""))
    latest = sorted(last_seen_of_run, key=lambda r: last_seen_of_run[r])[-args.runs:]
    print(f"latest {len(latest)} runs of {len(last_seen_of_run)} (by last sighting): last seen {', '.join(sorted(last_seen_of_run[r][:10] for r in latest))}")

    population = {i: e for i, e in ledger.items() if e.get("lastRunId") in latest and (e.get("job") or {}).get("provider") in m3.FILTERED_SOURCES}
    print(f"B1/B2 population: {len(population)} ads of the title-filtered sources found by those runs "
          f"({sum(1 for i in population if i in scored)} in the scored list)")

    # --- B1
    labels_of = {i: label_names(decision(e).labels) for i, e in population.items()}
    state = {i: paid_state(e, scored.get(i)) for i, e in population.items()}
    all_labels = sorted({n for names in labels_of.values() for n in names}, key=lambda n: (n.split(":")[0], n))
    groups = [("all ads", set(population)), ("no package 4 label", {i for i, n in labels_of.items() if not n}),
              *[(name, {i for i, n in labels_of.items() if name in n}) for name in all_labels]]
    total_paid = sum(1 for s in state.values() if s["any"])
    rows = []
    for name, ids in groups:
        n = len(ids)
        enrich = sum(1 for i in ids if state[i]["enrichment"])
        engine = sum(1 for i in ids if state[i]["engine"])
        fit3 = sum(1 for i in ids if state[i]["fit3"])
        anyp = sum(1 for i in ids if state[i]["any"])
        unknown = sum(1 for i in ids if not state[i]["complete"])
        rows.append([name, n, enrich, engine, fit3, f"{anyp} ({pct(anyp, n)})", pct(anyp, total_paid) if name not in ("all ads",) else "-", unknown])
    table("B1. ads carrying each label, and how many reached paid reading (state now)",
          ["label", "ads", "enrichment", "evidence engine", "Fit 3", "any paid step (paid share)", "of all paid-read ads", f"{NOT_SCORED}"], rows)
    print(f"  all paid-read ads in this population: {total_paid}. Engine counts the matcher and the engine fill together. "
          f"A label can sit on an ad in several rows; the 'no package 4 label' row is the baseline.")

    # --- B2
    status_of = statuses()
    keep = {i: s for i, s in status_of.items()}
    in_ledger = {i: s for i, s in keep.items() if i in ledger}
    print(f"\nB2. owner statuses: {len(keep)} ads ({Counter(x for s in keep.values() for x in s)}); {len(in_ledger)} in the ledger, "
          f"{len(keep) - len(in_ledger)} not (history-only or hand-entered)")
    keep_labels = {i: label_names(decision(ledger[i]).labels) for i in in_ledger}
    rows = []
    for name in ["any label", *all_labels]:
        cell = {}
        for status in ("saved", "applied", "rejected"):
            ids = [i for i, s in in_ledger.items() if status in s]
            cell[status] = sum(1 for i in ids if (keep_labels[i] if name == "any label" else name in keep_labels[i]))
        rows.append([name, cell["saved"], cell["applied"], cell["rejected"], sum(1 for i in in_ledger if (keep_labels[i] if name == "any label" else name in keep_labels[i]))])
    totals = {s: sum(1 for x in in_ledger.values() if s in x) for s in ("saved", "applied", "rejected")}
    rows.append(["(all must-keep in the ledger)", totals["saved"], totals["applied"], totals["rejected"], len(in_ledger)])
    table("B2. must-keep ads by label and status (an ad with two statuses counts in both columns; the last column counts it once)",
          ["label", "saved", "applied", "rejected", "ads"], rows)
    print("  per ad (id, statuses, labels):")
    for i in sorted(in_ledger):
        print(f"    {i}  {'/'.join(sorted(in_ledger[i]))}  {sorted(keep_labels[i]) or '-'}")

    # --- B4
    # The ledger only holds ads the previous rules let in, so the ads package 3 adds are not in it: they are in filtered_ads.json, which keeps
    # no text. What can be replayed exactly is the seniority drop (the title alone decides, except that a title miss now also needs a text);
    # a title miss that the text check may now keep cannot be replayed (no text), so it is bounded, not counted.
    filtered = m3._read("jobs/filtered_ads.json").get("ads") or {}
    filtered_ledger = {i: e for i, e in ledger.items() if (e.get("job") or {}).get("provider") in m3.FILTERED_SOURCES}
    scan = args.day or max(str(e.get("lastSeen") or "")[:10] for e in filtered_ledger.values())
    seen_ledger = {i: e for i, e in filtered_ledger.items() if str(e.get("lastSeen") or "")[:10] == scan}
    records = {i: r for i, r in filtered.items() if str(r.get("lastSeen") or "")[:10] == scan and r.get("source") in m3.FILTERED_SOURCES}
    old_seniority = {f"title_excluded:{w}" for w in m3.OLD_SENIORITY_EXCLUDES}
    print(f"\nB4. scan day {scan}: {len(seen_ledger)} ads in the ledger and {len(records)} filtered records seen that day (title-filtered sources). "
          f"The ledger holds only what the previous rules let in, so it shows no extra ad: the extras are among the filtered records.")
    by_reason = Counter((r.get("reason") or "").split(":")[0] if not (r.get("reason") or "").startswith("title_excluded") else r["reason"] for r in records.values())
    print(f"  filtered records by reason: {dict(by_reason.most_common())}")
    seniority = {i: r for i, r in records.items() if r.get("reason") in old_seniority}
    kept_title_only = {i for i, r in seniority.items() if rf.assess(r.get("title") or "", "", terms, None).reason is None}
    kept_if_empty = {i for i, r in seniority.items() if rf.assess(r.get("title") or "", "", terms, "").reason is None}
    misses = {i: r for i, r in records.items() if r.get("reason") == "title_not_matched"}
    empty_share = {}
    for source in m3.FILTERED_SOURCES:
        kept = [e for e in seen_ledger.values() if e["job"].get("provider") == source]
        empty_share[source] = (sum(1 for e in kept if not (e["job"].get("description") or "").strip()), len(kept))
    miss_by_source = Counter(r.get("source") for r in misses.values())
    bound = sum(n * (empty_share[s][0] / empty_share[s][1] if empty_share[s][1] else 0.0) for s, n in miss_by_source.items())
    rows = [
        ["seniority drop, title still matches (exact)", len(kept_title_only), "kept now: the title decides, no text needed"],
        ["seniority drop, title misses, text unknown", len(kept_if_empty) - len(kept_title_only), "kept only if its text is empty or names a product role (not replayable)"],
        ["title miss (title_not_matched), text unknown", len(misses), "kept only if its text names a product role (or is empty: no source returned an empty text on that day, see the next line)"],
    ]
    table("B4. ads package 3 lets in on that scan, against the previous rules", ["kind", "ads", "note"], rows)
    print(f"  empty-text share of the ads the ledger kept that day, per source: "
          f"{ {s: f'{a}/{b}' for s, (a, b) in empty_share.items() if b} }")
    # Into Active and paid reading: these ads were never scored under the new rules, so there is no row to read. Estimate only: the average
    # ad of the latest runs (B1 population) reached each step at these rates; an extra ad is assumed to behave like it.
    n = len(population)
    rate = {k: sum(1 for s in state.values() if s[k]) / n for k in ("enrichment", "engine", "fit3", "any")} if n else {}
    exact = len(kept_title_only)
    print(f"  ESTIMATE (the average ad of the latest runs reached enrichment {rate.get('enrichment', 0):.0%}, the evidence engine {rate.get('engine', 0):.0%}, "
          f"Fit 3 {rate.get('fit3', 0):.0%}, any paid step {rate.get('any', 0):.0%}): the exact seniority extra(s) = {exact} ad(s), "
          f"about {exact * rate.get('any', 0):.1f} paid-read.")
    undecided = len(misses) + len(kept_if_empty - kept_title_only)
    print(f"  The {undecided} ads that only a text check can keep are not countable here (no text kept). Each 1% of them that passes is "
          f"{undecided / 100:.1f} ads, about {undecided / 100 * rate.get('any', 0):.1f} of them paid-read, if they behave like the average ad.")
    print("  Not measurable until a scan runs under the new rules: whether they land in Active (depends on the 14-day window and the owner's "
          "filters) and which are read (tier, Settings limits).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
