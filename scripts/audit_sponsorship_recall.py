#!/usr/bin/env python3
"""Recall audit of the sponsorship block (offline, no model call, writes nothing).

    .venv/bin/python scripts/audit_sponsorship_recall.py [--scored FILE] [--discovered FILE] [--show-quotes]

Scans EVERY stored ad text (scored rows, then discovered ads that have no scored row) with a deterministic list of explicit
sponsorship-refusal phrases that does not depend on the extraction or on eligibility.py's own patterns, then lists the ads
that hold one and are not Blocked, with the stored eligibility state beside each. "Must be authorized to work" alone is not
a refusal here. Prints counts, ids and the phrase category; with --show-quotes the matched phrase (public ad text, at most 25
words). It never prints the profile.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python" / "job_scoring"))
import work_authorization as wa  # noqa: E402

JOBS = Path("/srv/holojob/data/jobs")
_GAP = r"(?:\w+\s+){0,4}?"
CATEGORIES = {
    "no_sponsorship": r"\bno\s+(?:\w+\s+){0,3}?(?:sponsorship|visa\s+support|visa\s+assistance|immigration\s+support)\b",
    "not_offer_provide": rf"\b(?:not|n't|never)\s+{_GAP}(?:offer|provide|extend|support|give|available)\w*\s+{_GAP}(?:sponsorship|visa|work\s+permit)",
    "unable_to_sponsor": r"\b(?:unable|not\s+able|cannot|can\s?not|can't|will\s+not|won't|do\s+not|don't|does\s+not|doesn't|not\s+in\s+a\s+position|are\s+not\s+willing|is\s+not\s+willing|not\s+willing)\s+(?:to\s+)?sponsor",
    "without_sponsorship": rf"\bwithout\s+{_GAP}(?:visa\s+)?sponsor\w*",
    "not_require_sponsorship": rf"\b(?:not|n't|never)\s+(?:\w+\s+){{0,2}}?(?:require|need)\s+{_GAP}sponsor\w*|\bno\s+need\s+for\s+{_GAP}sponsor\w*",
    "sponsorship_unavailable": r"\bsponsor\w*\s+(?:\w+\s+){0,3}?(?:is\s+|are\s+)?(?:not\s+available|unavailable|not\s+offered|not\s+provided|not\s+possible)\b",
    "now_or_future": r"\b(?:require|need)\w*\s+(?:\w+\s+){0,5}?sponsor\w*\s+(?:\w+\s+){0,6}?(?:now\s+or\s+in\s+the\s+future|in\s+the\s+future|at\s+any\s+time)",
}
COMPILED = {k: re.compile(v) for k, v in CATEGORIES.items()}


def clean(text: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    t = t.replace("’", "'").replace("‘", "'").replace("*", " ").replace("_", " ")
    return " ".join(t.split()).lower()


def hits(text: str) -> dict[str, str]:
    t, out = clean(text), {}
    for name, rx in COMPILED.items():
        m = rx.search(t)
        if m:
            out[name] = t[max(0, m.start() - 40): m.end() + 40]
    return out


def load(path: Path) -> list[dict]:
    data = json.load(open(path))
    return data["jobs"] if isinstance(data, dict) else data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", default=str(JOBS / "scored_jobs.json"))
    ap.add_argument("--discovered", default=str(JOBS / "discovered_jobs.json"))
    ap.add_argument("--show-quotes", action="store_true")
    args = ap.parse_args()
    scored = load(Path(args.scored))
    scored_ids = {str(r.get("jobId")) for r in scored}
    disc = [d for d in load(Path(args.discovered)) if str(d.get("jobId") or d.get("id")) not in scored_ids]
    print(f"scored rows: {len(scored)}; discovered ads without a scored row: {len(disc)}")

    with_phrase, missed = [], []
    for r in scored:
        h = hits(r.get("description"))
        if not h:
            continue
        with_phrase.append(r)
        if not r.get("blockedBy"):
            missed.append((r, h))
    print(f"scored rows holding a refusal phrase: {len(with_phrase)}; of them Blocked: {len(with_phrase) - len(missed)}; not Blocked: {len(missed)}")
    print("phrase categories over all scored rows with a phrase:", dict(Counter(k for r in with_phrase for k in hits(r.get('description')))))
    print("not Blocked, by phrase category:", dict(Counter(k for _, h in missed for k in h)))
    print("not Blocked, by stored eligibility kind:", dict(Counter(((r.get("eligibility") or {}).get("kind") or "dormant") for r, _ in missed)))
    print("not Blocked, by extraction visaSponsorship:", dict(Counter(((r.get("llmFacts") or {}).get("visaSponsorship") or "unread") for r, _ in missed)))
    print("\nnot Blocked rows (id | eligibility kind | country | extraction | categories | current-pattern hit on the extraction quote):")
    for r, h in missed:
        e, f = r.get("eligibility") or {}, r.get("llmFacts") or {}
        cur = wa.refuses_sponsorship(f.get("visaEvidence"))
        print(f"  {r.get('jobId')} | {e.get('kind') or 'dormant'}/{e.get('state')} | {e.get('country')} | {f.get('visaSponsorship') or 'unread'} | "
              f"{','.join(sorted(h))} | {cur}")
        if args.show_quotes:
            for k, v in h.items():
                print(f"      {k}: {' '.join(v.split()[:25])}")
    dh = [(d, hits(d.get("description"))) for d in disc]
    dh = [(d, h) for d, h in dh if h]
    print(f"\ndiscovered ads without a scored row holding a phrase: {len(dh)}")
    for d, h in dh:
        print(f"  {d.get('jobId') or d.get('id')} | {','.join(sorted(h))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
