#!/usr/bin/env python3
"""Look at a private file without printing what it holds: its shape, counts and hashes only.

    .venv/bin/python scripts/inspect-private-data.py FILE [--depth N]

For the owner's files under data/ (profile, intelligence, CVs, resumes). Read only, standard library only. A JSON file gives one
line per field: path, type, number of items or characters, longest entry in words, first 12 hex digits of the SHA-256. Any other
file gives its size and hash. No value is ever printed, and a key is printed only if it looks like a field name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

FIELD_NAME = re.compile(r"^[a-z][a-zA-Z0-9_]{0,60}$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _strings(inner)


def _line(path: str, value) -> str:
    kind = type(value).__name__
    size = len(value) if isinstance(value, (str, list, dict)) else "-"
    longest = max((len(text.split()) for text in _strings(value)), default=0)
    return f"{path or '.'}\t{kind}\tsize={size}\tlongestWords={longest}\tsha={digest(_encoded(value))}"


def describe(value, path: str = "", depth: int = 3) -> list[str]:
    lines = [_line(path, value)]
    if isinstance(value, dict) and depth > 0:
        for index, (key, inner) in enumerate(value.items()):
            name = key if isinstance(key, str) and FIELD_NAME.match(key) else f"<key{index}>"
            lines += describe(inner, f"{path}.{name}" if path else name, depth - 1)
    return lines


def inspect(file: Path, depth: int = 3) -> list[str]:
    data = file.read_bytes()
    summary = f"file\tbytes={len(data)}\tsha={digest(data)}"
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return [summary, "not JSON: no fields listed"]
    return [summary, *describe(parsed, depth=depth)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--depth", type=int, default=3)
    args = parser.parse_args(argv)
    if not args.file.is_file():
        print("no such file", file=sys.stderr)
        return 1
    print("\n".join(inspect(args.file, max(0, args.depth))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
