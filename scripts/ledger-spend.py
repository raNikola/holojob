#!/usr/bin/env python3
"""What the AI usage ledger recorded after a given line: calls, refusals, tokens and cost per feature. Numbers only; read only.

    .venv/bin/python scripts/ledger-spend.py --mark                    # prints the current number of ledger lines
    .venv/bin/python scripts/ledger-spend.py --since N [--billed USD]  # spend of the lines after N, against the provider's figure
"""
import argparse
import json
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "data/ai/usage-ledger.jsonl"


def summarise(lines):
    rows = [json.loads(l) for l in lines if l.strip()]
    results = {r["id"]: r for r in rows if r.get("type") == "result"}
    out = {}
    for r in rows:
        if r.get("type") != "call":
            continue
        f = out.setdefault(r.get("feature") or "unspecified", {"calls": 0, "refused": 0, "in": 0, "out": 0, "cost": 0.0, "noResult": 0})
        if r.get("decision") == "refused":
            f["refused"] += 1
            continue
        f["calls"] += 1
        res = results.get(r["id"])
        if res is None:
            f["noResult"] += 1
            f["cost"] += float(r.get("cost") or 0)
            continue
        f["in"] += int(res.get("inputTokens") or 0)
        f["out"] += int(res.get("outputTokens") or 0)
        f["cost"] += float(res.get("cost") or 0)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--mark", action="store_true")
    ap.add_argument("--since", type=int, default=0)
    ap.add_argument("--billed", type=float, default=None)
    a = ap.parse_args(argv)
    lines = a.ledger.read_text(encoding="utf-8").splitlines() if a.ledger.exists() else []
    if a.mark:
        print(len(lines))
        return 0
    out = summarise(lines[a.since:])
    for name, f in sorted(out.items()):
        print(f"{name}: {f['calls']} calls, {f['refused']} refused, {f['in']} in / {f['out']} out tokens, cost {f['cost']:.4f}"
              + (f", {f['noResult']} without a result row (counted at estimate)" if f["noResult"] else ""))
    total = round(sum(f["cost"] for f in out.values()), 6)
    print(f"ledger total since line {a.since}: {total:.4f} USD (price table x measured tokens)")
    if a.billed is not None:
        diff = round(a.billed - total, 6)
        print(f"provider billed {a.billed:.4f}; difference {diff:+.4f} USD ({(diff / total * 100 if total else 0):+.1f}% of the ledger)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
