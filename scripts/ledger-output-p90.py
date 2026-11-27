#!/usr/bin/env python3
"""p90 of the measured output tokens per call in the AI usage ledger. Numbers only; read only.

    .venv/bin/python scripts/ledger-output-p90.py [--ledger FILE]

Counts successful calls whose result row carries measured (not estimated) tokens. Nearest-rank percentile.
The value is the suggested default of `estimatedOutputTokens` (Settings > AI budget).
"""
import argparse
import json
import math
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "data/ai/usage-ledger.jsonl"


def p90(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def measured_outputs(lines: list[str]) -> dict[str, list[int]]:
    """Feature -> measured output tokens of ok result rows (a result row carries no feature: it comes from its call)."""
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    feature = {r.get("id"): r.get("feature") or "-" for r in rows if r.get("type") == "call"}
    out: dict[str, list[int]] = {}
    for r in rows:
        if r.get("type") != "result" or not r.get("ok") or r.get("tokensAreEstimate"):
            continue
        tokens = r.get("outputTokens")
        if isinstance(tokens, int) and tokens > 0:
            out.setdefault(feature.get(r.get("id"), "-"), []).append(tokens)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    a = ap.parse_args(argv)
    lines = a.ledger.read_text(encoding="utf-8").splitlines() if a.ledger.exists() else []
    by_feature = measured_outputs(lines)
    allv = [v for vs in by_feature.values() for v in vs]
    for name in sorted(by_feature):
        print(f"{name}: n={len(by_feature[name])} p90={p90(by_feature[name])}")
    print(f"all: n={len(allv)} p90={p90(allv)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
