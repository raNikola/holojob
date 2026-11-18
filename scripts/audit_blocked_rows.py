#!/usr/bin/env python3
"""Audit of the Blocked rows against the Step 2 rule (offline, no model call, writes nothing).

    .venv/bin/python scripts/audit_blocked_rows.py [--scored FILE] [--sample N] [--seed N]

A block is allowed only for (1) sponsorship refused or (2) a language the ad REQUIRES and the declared profile list does not
contain, and only when (a) the stated quote is found verbatim in the stored ad text and (c) neither the quote's sentence nor its
neighbours carry a softening marker (nice to have, a plus, preferred ...). Prints counts, ids, reason types and ad quotes (public
ad text, at most 25 words). It never prints the profile: the declared language list is reported as a count only.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python" / "job_scoring"))
import eligibility  # noqa: E402
from match_engine import gates as g  # noqa: E402

SCORED = Path("/srv/holojob/data/jobs/scored_jobs.json")
ALLOWED_KINDS = {"sponsorship_refused", "language"}
SOFTENING = re.compile(
    r"\b(?:nice[- ]to[- ]have|a plus|plus\b|preferred|preferably|prefer|advantage|advantageous|bonus|desirable|desired|"
    r"beneficial|helpful|ideally|optional|an asset|asset|not required|not necessary|welcome|would be great|"
    r"considered a|is a plus|big plus)",
    re.I,
)


def clean(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(str(text or ""))).replace("’", "'").split())


def sentences(text: str) -> list[str]:
    # bullets ("* ", "- ", "•") and bold headings ("**Preferred Qualifications:**") start a new unit, so a heading's word is not read into the line before it
    parts = re.split(r"(?<=[.!?;])\s+|\s+(?=\*\s)|\s+(?=\*\*[^*]+\*\*)|\s*[\n•·▪●]\s*", text)
    return [s for s in parts if s.strip()]


def locate(quote: str, description: str) -> tuple[bool, list[str]]:
    """(found verbatim ignoring tags/spacing/case, the sentence index window text: [own, previous, next])."""
    ad, pieces = clean(description), [p.strip() for p in re.split(r"\.{3}|…", clean(quote)) if p.strip()]
    found = bool(pieces) and all(p.lower() in ad.lower() for p in pieces)
    if not found:
        return False, []
    sents, probe = sentences(ad), pieces[0].lower()
    for i, s in enumerate(sents):
        if probe[:60] in s.lower() or s.lower() in probe:
            return True, [s, sents[i - 1] if i else "", sents[i + 1] if i + 1 < len(sents) else ""]
    pos = ad.lower().find(probe)
    return True, [ad[max(0, pos - 150): pos + len(probe) + 150], "", ""]


def softening(window: list[str]) -> dict[str, list[str]]:
    own = SOFTENING.findall(window[0]) if window else []
    near = [m for part in window[1:] for m in SOFTENING.findall(part)]
    return {"own": own, "neighbour": near}


def words(text: str, n: int = 25) -> str:
    w = clean(text).split()
    return " ".join(w[:n]) + (" ..." if len(w) > n else "")


def entries(row: dict) -> list[dict]:
    """One entry per block: {id, kind, sub, language, quote}."""
    out = []
    desc = row.get("description") or ""
    for b in row.get("blockedBy") or []:
        if b["kind"] == "sponsorship_refused":
            e = row.get("eligibility") or {}
            out.append({"id": row["jobId"], "kind": b["kind"], "sub": e.get("kind"), "language": None, "quote": e.get("quote") or ""})
        elif b["kind"] == "language":
            names = (row.get("languageState") or {}).get("blocking") or []
            quotes = g.must_language_quotes((row.get("llmFacts") or {}).get("requirements"))
            for name in names or [None]:
                cand = [q for grp, qs in quotes.items() if " or ".join(sorted(grp)) == name for q in qs]
                good = [q for q in cand if eligibility.quote_in_text(q, desc)]
                out.append({"id": row["jobId"], "kind": b["kind"], "sub": None, "language": name, "quote": (good or cand or [""])[0]})
        else:
            out.append({"id": row["jobId"], "kind": b["kind"], "sub": None, "language": None, "quote": ""})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", default=str(SCORED))
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261118)
    args = ap.parse_args()
    data = json.load(open(args.scored))
    rows = [r for r in data["jobs"] if r.get("blockedBy")]
    print(f"blocked rows: {len(rows)} of {len(data['jobs'])}")
    flagged: dict[str, list[str]] = {}
    items = []
    for r in rows:
        for e in entries(r):
            e["row"] = r
            items.append(e)
            why = []
            if e["kind"] not in ALLOWED_KINDS:
                why.append(f"reason:{e['kind']}")
            if not e["quote"]:
                why.append("no_quote")
            else:
                ok, window = locate(e["quote"], r.get("description") or "")
                if not ok:
                    why.append("quote_not_verbatim")
                s = softening(window)
                e["soft"] = s
                if s["own"]:
                    why.append("softening_in_sentence")
                if s["neighbour"]:
                    why.append("softening_in_neighbour")
            if e["kind"] == "sponsorship_refused" and e["sub"] != "refused":
                why.append(f"sponsorship_subtype:{e['sub']}")
            if e["kind"] == "language" and not r.get("languageState", {}).get("listDeclared"):
                why.append("no_declared_list")
            e["why"] = why
            if why:
                flagged.setdefault(e["id"], []).extend(why)
    print("\nby reason type:", dict(Counter(e["kind"] for e in items)))
    print("sponsorship subtype:", dict(Counter(e["sub"] for e in items if e["kind"] == "sponsorship_refused")))
    print("by language:", dict(Counter(e["language"] for e in items if e["kind"] == "language")))
    print("blocked rows with two reasons:", sum(1 for r in rows if len(r["blockedBy"]) > 1))
    print(f"\nflagged blocks: {len(flagged)} rows")
    for jid, why in sorted(flagged.items()):
        print(f"  {jid}: {', '.join(sorted(set(why)))}")
    print("\nflag totals:", dict(Counter(w.split(':')[0] if w.startswith('reason') else w for ws in flagged.values() for w in set(ws))))
    rnd = random.Random(args.seed)
    print(f"\nrandom sample of {args.sample} (seed {args.seed}):")
    for e in rnd.sample(items, min(args.sample, len(items))):
        label = e["kind"] + (f"/{e['language']}" if e["language"] else f"/{e['sub']}")
        print(f"  {e['id']} | {label} | {words(e['quote'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
