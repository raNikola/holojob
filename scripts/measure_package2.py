#!/usr/bin/env python3
"""Package 2 free measurements (no product change, no model call, no network).

    profile   one scoring pass on a COPY of the data in a temp dir, under cProfile (cause of the scoring slowdown)
    steps     step durations of the Re-scrape runs (data/analytics/runs), read-only
    prompts   section sizes of the model prompts and the shared prefix across calls (no call is made)
    negative  career-ops filter-audit applied to the title exclude list (unique drops per keyword)

Real data is read-only; every write goes to a temp dir. Output: counts, ids, code names and public rule terms only.
Usage: .venv/bin/python scripts/measure_package2.py {profile|steps|prompts|negative} [--top N]
"""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DATA = Path("/srv/holojob/data")
# What a scoring pass reads or writes. Secrets, backups, staging, resumes and applications are never copied.
COPY_FILES = [
    "intelligence/candidate-intelligence.json", "profile/candidate-profile.json",
    "jobs/discovered_jobs.json", "jobs/job_history.json", "jobs/manual_jobs.json", "jobs/job-state.json",
    "jobs/filtered_ads.json", "jobs/scored_jobs.json", "jobs/rescored_kept.json",
    "cache/llm_fit.json", "cache/fit3.json", "cache/engine.json", "cache/engine-calibration.json",
    "cache/requirement-frames.json", "cache/competency-evidence.json",
    "ai/settings.json", "competency-aliases.json", "profile-enrichment.json", "requirement-remap.json",
]


def mirror(tmp: Path) -> None:
    """Copy python/ and the scoring inputs into tmp, with the same layout, so ROOT-relative paths resolve there."""
    shutil.copytree(ROOT / "python", tmp / "python", ignore=shutil.ignore_patterns("__pycache__"))
    for sub in ("src", "config"):
        if (ROOT / sub).exists():
            shutil.copytree(ROOT / sub, tmp / sub, ignore=shutil.ignore_patterns("node_modules"))
    for rel in COPY_FILES:
        src = REAL_DATA / rel
        if src.exists():
            (tmp / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp / "data" / rel)
    for d in ("config",):
        if (REAL_DATA / d).is_dir():
            shutil.copytree(REAL_DATA / d, tmp / "data" / d, ignore=shutil.ignore_patterns("secrets"))


def cmd_profile(args) -> int:
    with tempfile.TemporaryDirectory(prefix="holojob-measure2-") as t:
        tmp = Path(t)
        t0 = time.time()
        mirror(tmp)
        print(f"copy: {time.time() - t0:.1f}s")
        sys.path.insert(0, str(tmp / "python" / "job_scoring"))
        sys.path.append(str(tmp / "python"))
        import run_scoring  # imported from the copy: its ROOT is tmp

        assert Path(run_scoring.ROOT) == tmp, run_scoring.ROOT
        out = tmp / "scored-profile.json"
        # --workers 1: cProfile sees only the calling thread, and score_jobs runs its rows on a thread pool.
        sys.argv = ["run_scoring.py", "--output", str(out), "--workers", "1"]
        ns = run_scoring.parse_args()
        prof = cProfile.Profile()
        t0 = time.time()
        prof.enable()
        code = run_scoring.score(ns)  # no pipeline lock: the copy is private
        prof.disable()
        wall = time.time() - t0
        try:
            rows = json.loads(out.read_text(encoding="utf-8")).get("jobs") or []
            print(f"rows scored: {len(rows)}")
        except (OSError, ValueError):
            pass
        st = pstats.Stats(prof)
        print(f"scoring pass: exit={code} wall(profiled)={wall:.1f}s total_calls={st.total_calls}")
        rows = []
        for (fn, line, name), (cc, nc, tt, ct, _callers) in st.stats.items():
            rows.append((ct, tt, nc, f"{Path(fn).name}:{line}:{name}"))
        rows.sort(reverse=True)
        print(f"top {args.top} by cumulative time (cum_s, self_s, calls, function):")
        for ct, tt, nc, label in rows[: args.top]:
            print(f"{ct:9.1f} {tt:9.1f} {nc:10d}  {label}")
        rows.sort(key=lambda r: -r[1])
        print(f"top {args.top} by self time:")
        for ct, tt, nc, label in rows[: args.top]:
            print(f"{ct:9.1f} {tt:9.1f} {nc:10d}  {label}")
    return 0


def _secs(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()


def cmd_steps(_args) -> int:
    runs = REAL_DATA / "analytics" / "runs"
    print("run, discovery_s, jobspy_read, scoring_s, scoring_prepare_s(each)")
    for f in sorted(os.listdir(runs)):
        if not f.endswith(".json"):
            continue
        try:
            r = json.loads((runs / f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        by = {}
        for s in r.get("steps", []):
            if s.get("startedAt") and s.get("finishedAt"):
                by.setdefault(s["name"], []).append(round(_secs(s["startedAt"], s["finishedAt"])))
        js = next((x for x in r.get("sources", []) if x.get("name") == "jobspy"), {})
        print(f[:16], by.get("discovery"), js.get("read"), by.get("scoring"), by.get("scoring-prepare"))
    return 0


def _ledger_ads() -> dict[str, dict]:
    doc = json.loads((REAL_DATA / "jobs" / "job_history.json").read_text(encoding="utf-8"))
    return doc.get("jobs") or {}


def _must_keep_ids() -> tuple[set[str], str]:
    """Saved and Rejected from job-state.json, Applied from the runner's exported id file (HOLOJOB_APPLICATION_JOB_IDS)."""
    state = json.loads((REAL_DATA / "jobs" / "job-state.json").read_text(encoding="utf-8")).get("jobs") or {}
    ids = {str(v.get("jobId") or k) for k, v in state.items() if v.get("status") in ("saved", "rejected")}
    path = os.environ.get("HOLOJOB_APPLICATION_JOB_IDS")
    note = "applied ids: not available (HOLOJOB_APPLICATION_JOB_IDS unset)"
    if path and Path(path).exists():
        applied = {ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()}
        ids |= applied
        note = f"applied ids read: {len(applied)}"
    return ids, note


def cmd_negative(_args) -> int:
    """career-ops filter-audit.mjs (`unique` = offers one keyword alone catches), turned round: it audits the NEGATIVE list
    (TITLE_EXCLUDE) over every title the filter has seen: ledger (kept) plus filtered_ads.json (dropped)."""
    sys.path.insert(0, str(ROOT / "python" / "job_discovery" / "providers"))
    import role_filter as rf

    ledger = _ledger_ads()
    filtered = json.loads((REAL_DATA / "jobs" / "filtered_ads.json").read_text(encoding="utf-8")).get("ads") or {}
    titles: list[tuple[str, str, str]] = []  # (id, title, where)
    for jid, row in ledger.items():
        titles.append((jid, (row.get("job") or {}).get("title") or "", "ledger"))
    for jid, row in filtered.items():
        if not row.get("inLedger"):
            titles.append((jid, row.get("title") or "", "filtered"))
    # The jobspy provider passes its search terms to role_tier (a title holding one is Near, never excluded for not matching).
    terms: tuple[str, ...] = ()
    staging = REAL_DATA / "jobs" / "staging"
    for f in sorted(staging.glob("*/jobspy.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:1]:
        for line in f.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("terms"):
                terms = tuple(row["terms"])
                break
    print(f"search terms taken from the latest jobspy staging header: {len(terms)}")
    keep_ids, note = _must_keep_ids()
    n_ledger = sum(1 for t in titles if t[2] == "ledger")
    print(f"titles replayed: {len(titles)} (ledger {n_ledger}, filtered-only {len(titles) - n_ledger}); must-keep ids {len(keep_ids)}; {note}")
    stats = {t: {"hits": 0, "unique": 0, "uniqueOnlyReason": 0, "inLedgerNow": 0, "mustKeep": 0, "examples": []} for t in rf.vocabulary().exclude}
    drops = Counter()
    for jid, title, where in titles:
        folded = rf._fold(title)
        hit = [t for t in rf.vocabulary().exclude if rf._has_phrase(folded, t)]
        # What the filter would do with the exclude list removed: the include and near lists alone.
        would_pass = any(rf._has_phrase(folded, t) for t in (*rf.vocabulary().include, *rf.vocabulary().near, *(rf._fold(x) for x in terms if x)))
        _tier, reason = rf.role_tier(title, "", terms)
        drops[(reason or "kept").split(":")[0]] += 1
        for t in hit:
            s = stats[t]
            s["hits"] += 1
            if len(hit) == 1:
                s["unique"] += 1
                if would_pass:
                    s["uniqueOnlyReason"] += 1  # without this keyword the title would go on to scoring
            if where == "ledger":
                s["inLedgerNow"] += 1
            if jid in keep_ids:
                s["mustKeep"] += 1
            if len(s["examples"]) < 3:
                s["examples"].append(title)
    print("final title decisions:", dict(drops))
    print("keyword | hits | unique | unique-and-only-reason | now in ledger | must-keep | examples (public titles)")
    for t, s in sorted(stats.items(), key=lambda kv: (-kv[1]["uniqueOnlyReason"], -kv[1]["hits"])):
        print(f"{t} | {s['hits']} | {s['unique']} | {s['uniqueOnlyReason']} | {s['inLedgerNow']} | {s['mustKeep']} | {s['examples']}")
    print("never matched:", [t for t, s in stats.items() if not s["hits"]])
    print("redundant (hits, but the title would be dropped anyway as title_not_matched):",
          [t for t, s in stats.items() if s["hits"] and not s["uniqueOnlyReason"]])
    return 0


def cmd_prompts(args) -> int:
    """Section sizes of the three prompts and the identical prefix across calls. Prompts are built, never sent.
    Tokens are estimated at 4 chars (the repo's input floor) and 3 chars (its upper bound): no tokenizer is available offline."""
    import re

    sys.path.insert(0, str(ROOT / "python" / "job_scoring"))
    sys.path.append(str(ROOT / "python"))
    import competency_mapping
    import enrich_jobs
    from match_engine import fit3, matcher

    ads = [(jid, r.get("job") or {}) for jid, r in _ledger_ads().items() if len((r.get("job") or {}).get("description") or "") > 400]
    ads = ads[: args.sample]
    print(f"ads sampled: {len(ads)} (ledger ads with a description over 400 chars, in file order)")

    def est(chars: int) -> str:
        return f"{chars} chars = ~{chars // 4} tokens at 4/token, ~{chars // 3} at 3/token"

    for name, tpl in (("reading (enrich_jobs.PROMPT)", enrich_jobs.PROMPT), ("engine (matcher.PROMPT)", matcher.PROMPT), ("fit3 (fit3.PROMPT)", fit3.PROMPT)):
        marks = [(m.group(0), m.start()) for m in re.finditer(r"(?<!\{)\{[a-z_]+\}", tpl)]
        print(f"\n{name}: template {len(tpl)} chars; placeholders at {marks}")
        print(f"  static text before the first placeholder: {est(marks[0][1])}")

    roles = fit3.load_roles()
    comps = fit3.closed_competencies()
    mapper = competency_mapping.load_mapper("product")
    blocks = {"fit3 ROLES list": json.dumps(list(roles), ensure_ascii=False),
              "fit3 COMPETENCIES list": "\n".join(f"{c['id']}: {c['definition']}" for c in comps),
              "reading competency block": mapper.prompt_block() if mapper else ""}
    print()
    for k, v in blocks.items():
        print(f"{k}: {est(len(v))}")

    posts = [{"title": j.get("title") or "", "description": j.get("description") or ""} for _, j in ads]
    prompts_by = {"reading": [enrich_jobs.build_prompt(j, None, mapper) for _, j in ads],
                  "fit3": [fit3.build_prompt(p, roles, comps) for p in posts]}
    avg_desc = sum(len(p["description"]) for p in posts) // max(1, len(posts))
    print(f"average ad description in the sample: {est(avg_desc)}")
    for name, prompts in prompts_by.items():
        lens = sorted(len(p) for p in prompts)
        cp = len(os.path.commonprefix(prompts))
        print(f"\n{name}: {len(prompts)} real prompts; total length median {est(lens[len(lens) // 2])}; "
              f"IDENTICAL PREFIX across all: {est(cp)}; reaches 1024 tokens: {'yes' if cp // 4 >= 1024 else 'no'}"
              f" (at 3 chars/token: {'yes' if cp // 3 >= 1024 else 'no'})")
    tpl = fit3.PROMPT
    alt = len(tpl[: tpl.index("{title}")]) + len("ROLES: \n\nCOMPETENCIES (id: definition):\n") + len(blocks["fit3 ROLES list"]) + len(blocks["fit3 COMPETENCIES list"])
    print(f"\nfit3 if the lists came before TITLE and AD (counterfactual, not built): shared prefix would be {est(alt)}")
    print("\nengine: the ad comes first after a short head, the candidate evidence last; the prefix identical across calls is the template head only "
          f"({est(matcher.PROMPT.index('{description}'))}). The evidence is the same across ads but sits after the ad text, so it cannot be a shared prefix.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=["profile", "steps", "prompts", "negative"])
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--sample", type=int, default=200)
    args = p.parse_args(argv)
    return {"profile": cmd_profile, "steps": cmd_steps, "prompts": cmd_prompts, "negative": cmd_negative}.get(args.what, lambda a: 2)(args)


if __name__ == "__main__":
    sys.exit(main())
