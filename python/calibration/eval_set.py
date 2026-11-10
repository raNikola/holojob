#!/usr/bin/env python3
"""P1 Stage B, S0: the fixed test set. ran's 45 ad labels and 70 requirement-line labels, frozen, with a dev/test split by ad.

    python python/calibration/eval_set.py freeze [--out DIR] [--seed N] [--force]
    python python/calibration/eval_set.py check  [--out DIR]       # has a live label file changed since the freeze?

The labels are the only ground truth. `freeze` copies them into eval-set.json (ids, kinds, modes and ran's answers; never ad,
requirement, profile or CV text) together with the hash of each source file, and refuses to overwrite an existing freeze unless
--force. Later work is measured against this file, not against the live label files, so editing a label cannot silently move a
metric; `check` says when the live files no longer match the freeze.

Split: by ad, so every line of an ad sits on the same side. Inside each of ran's overall levels the ads are ordered by a hash of
the seed and dealt alternately to dev and test, which keeps every level on both sides. Tune on dev, report on test.

READ THIS WITH EVERY RESULT: the 45 ads and the 70 lines are a small, purpose-chosen diagnostic sample (the 70 lines were picked
by kind quota, disagreements first, plus 10 probe items), labelled by one person. They are not proof of reliability for every
profession, and per-kind counts are small. Always read a rate with its n.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("job_scoring", "llm"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402

STAGE_DIR = ROOT / "data" / "calibration" / "stage-a"
EVAL_NAME = "eval-set.json"
SEED = 11
SOURCES = {"adLabels": "ran-labels.json", "lineLabels": "ran-must-labels.json", "lineSample": "must-sample.json"}
CAVEAT = ("Small, purpose-chosen diagnostic sample (45 ads; 60 must lines picked by kind quota with disagreements first, plus 10 probe "
          "lines), one labeller. Not proof of reliability for all professions. Read every rate with its n.")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash(*parts) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def split_ads(levels: dict[str, int], seed: int) -> dict[str, str]:
    """{jobId: "dev" | "test"}: per ran level, ads ordered by hash and dealt alternately starting with dev."""
    out = {}
    for level in sorted(set(levels.values())):
        ids = sorted((j for j, lv in levels.items() if lv == level), key=lambda j: _hash(seed, j))
        for n, job_id in enumerate(ids):
            out[job_id] = "dev" if n % 2 == 0 else "test"
    return out


def build(ad_labels: dict, line_labels: dict, sample_items: list[dict], seed: int, hashes: dict) -> dict:
    split = split_ads({j: lb["overall"] for j, lb in ad_labels.items()}, seed)
    by_id = {i["itemId"]: i for i in sample_items}
    ads = {j: {"overall": lb["overall"], "functionFit": lb["functionFit"], "hardRequirements": lb["hardRequirements"], "split": split[j]}
           for j, lb in sorted(ad_labels.items())}
    lines = {}
    for item_id, lb in sorted(line_labels.items()):
        item = by_id[item_id]
        lines[item_id] = {"jobId": item["jobId"], "kind": item["kind"], "mode": item["mode"], "probe": bool(item["probe"]),
                          "modelImportance": item["importance"], "first": {"isMust": lb["first"]["isMust"], "meets": lb["first"]["meets"]},
                          "split": split[item["jobId"]]}
    return {"version": 1, "seed": seed, "frozenAt": datetime.now(timezone.utc).isoformat(), "caveat": CAVEAT, "sourceHashes": hashes,
            "ads": ads, "lines": lines, "counts": counts(ads, lines)}


def counts(ads: dict, lines: dict) -> dict:
    return {
        "ads": len(ads), "adsBySplit": dict(Counter(a["split"] for a in ads.values())),
        "adLevelsBySplit": {s: dict(sorted(Counter(a["overall"] for a in ads.values() if a["split"] == s).items())) for s in ("dev", "test")},
        "lines": len(lines), "linesBySplit": dict(Counter(x["split"] for x in lines.values())),
        "probeLines": sum(1 for x in lines.values() if x["probe"]),
    }


def freeze(out: Path, seed: int = SEED, force: bool = False) -> dict:
    target = out / EVAL_NAME
    if target.exists() and not force:
        raise SystemExit(f"{EVAL_NAME} already exists: the test set is frozen (use --force to replace it on purpose)")
    docs = {k: json.loads((out / name).read_text(encoding="utf-8")) for k, name in SOURCES.items()}
    ad_labels, line_labels = docs["adLabels"]["labels"], docs["lineLabels"]["labels"]
    if isinstance(ad_labels, list):
        ad_labels = {x["jobId"]: x for x in ad_labels}
    missing = [i for i in line_labels if i not in {x["itemId"] for x in docs["lineSample"]["items"]}]
    if missing:
        raise SystemExit("a labelled line is not in the sample")
    frozen = build(ad_labels, line_labels, docs["lineSample"]["items"], seed, {k: _sha(out / name) for k, name in SOURCES.items()})
    make_private_dirs(out)
    write_text_atomic(target, json.dumps(frozen, indent=2), PRIVATE_FILE_MODE)
    return frozen


def load(out: Path) -> dict:
    path = out / EVAL_NAME
    if not path.exists():
        raise SystemExit(f"no {EVAL_NAME}: run `eval_set.py freeze` first")
    return json.loads(path.read_text(encoding="utf-8"))


def drift(out: Path, frozen: dict | None = None) -> list[str]:
    """The source files whose live hash no longer matches the freeze (empty when nothing changed)."""
    frozen = frozen or load(out)
    return [name for key, name in SOURCES.items() if (out / name).exists() and _sha(out / name) != frozen["sourceHashes"].get(key)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("freeze", "check"))
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "freeze":
        print(json.dumps(freeze(args.out, args.seed, args.force)["counts"], indent=1))
        return 0
    changed = drift(args.out)
    print("live label files match the freeze" if not changed else "CHANGED since the freeze: " + ", ".join(changed))
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
