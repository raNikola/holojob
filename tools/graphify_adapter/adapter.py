#!/usr/bin/env python3
"""Holojob Graphify adapter: a small, removable step after `graphify update .`.

It reads graphify-out/graph.json and the source files and writes derived files to
graphify-out/holojob/. graph.json itself is never written. Decisions:
docs/DECISIONS.md, "Graph tooling". Standard library only: no network, no
subprocess, no model call, and no project module is imported or executed.

Every edge the adapter changes or adds carries `_origin: "adapter"` and a
`provenance`; every other edge and node is checked to be unchanged (fail closed).

Usage:  python3 tools/graphify_adapter/adapter.py build [--no-remove]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PINNED_GRAPHIFY_VERSION = "0.9.103"
SCHEMA_VERSION = 1
TOP_KEYS = frozenset({"directed", "multigraph", "graph", "nodes", "links", "hyperedges", "built_at_commit"})
HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parents[1]
OUT_SUBDIR = "holojob"
# Never walked: tool caches, build output, the graph itself, and data/ (personal
# data; only data/examples is tracked and indexed by Graphify).
SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "dist", "graphify-out", "__pycache__",
    "claude-config", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})
# Keys the adapter may change on an existing edge; everything else must stay equal.
CHANGEABLE_EDGE_KEYS = frozenset({"target", "_origin", "provenance", "original_target", "resolved_module"})


class AdapterError(Exception):
    """The input cannot be processed safely; nothing is written."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


# ------------------------------------------------------------------ loading


def check_schema(graph) -> None:
    if not isinstance(graph, dict) or set(graph) != TOP_KEYS:
        found = sorted(graph) if isinstance(graph, dict) else type(graph).__name__
        raise AdapterError(f"unexpected graph.json top-level keys: {found}")
    meta = graph["graph"]
    version = meta.get("graphify_version") if isinstance(meta, dict) else None
    schema = meta.get("schema_version") if isinstance(meta, dict) else None
    if version != PINNED_GRAPHIFY_VERSION or schema != SCHEMA_VERSION:
        raise AdapterError(
            f"graph.json comes from graphify {version!r} (schema {schema!r}); the adapter is pinned to "
            f"{PINNED_GRAPHIFY_VERSION} (schema {SCHEMA_VERSION}). Re-check the adapter before moving the pin."
        )
    ids = set()
    for node in graph["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise AdapterError("a node has no string id")
        if node["id"] in ids:
            raise AdapterError(f"duplicate node id {node['id']!r}")
        ids.add(node["id"])
    for edge in graph["links"]:
        if not isinstance(edge, dict) or not all(isinstance(edge.get(k), str) for k in ("source", "target", "relation")):
            raise AdapterError("an edge lacks source, target or relation")


def walk_repo(root: Path):
    """Yield repo-relative POSIX paths, sorted, skipping SKIP_DIRS and data/ except data/examples."""
    def walk(base: Path, prefix: str):
        for dirpath, dirnames, filenames in os.walk(base):
            rel = Path(dirpath).relative_to(base).as_posix()
            rel = prefix if rel == "." else (f"{prefix}/{rel}" if prefix else rel)
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not (rel == "" and d == "data"))
            for name in sorted(filenames):
                yield f"{rel}/{name}" if rel else name

    yield from walk(root, "")
    examples = root / "data" / "examples"
    if examples.is_dir():
        yield from walk(examples, "data/examples")


class Work:
    """The graph being rewritten, with every change tracked for the invariant check."""

    def __init__(self, graph: dict):
        self.graph = graph
        self.edges = [{"i": i, "e": e, "tag": None} for i, e in enumerate(graph["links"])]
        self.nodes = [{"i": i, "n": n} for i, n in enumerate(graph["nodes"])]
        self.removed_edges: dict[int, str] = {}
        self.removed_nodes: dict[str, str] = {}
        self._reindex()

    def _reindex(self) -> None:
        self.by_id = {entry["n"]["id"]: entry["n"] for entry in self.nodes}
        self.file_nodes = self._file_nodes()

    def _file_nodes(self) -> dict[str, str]:
        """source_file -> id of the node that stands for the whole file (label = basename)."""
        found: dict[str, list[str]] = {}
        for entry in self.nodes:
            node = entry["n"]
            path = node.get("source_file") or ""
            if path and node.get("label") == path.rsplit("/", 1)[-1] and node.get("source_location") in ("L1", None):
                found.setdefault(path, []).append(node["id"])
        return {path: ids[0] for path, ids in found.items() if len(ids) == 1}

    def node(self, node_id: str):
        return self.by_id.get(node_id)

    def live_edges(self):
        return [entry for entry in self.edges if "dead" not in entry]

    def replace(self, entry: dict, new_edge: dict, tag: str) -> None:
        entry["e"], entry["tag"] = new_edge, tag

    def kill(self, entry: dict, reason: str) -> None:
        if entry["i"] is None:
            raise AdapterError("an added edge cannot be removed")
        entry["dead"] = reason
        self.removed_edges[entry["i"]] = reason

    def add_edge(self, edge: dict, tag: str) -> None:
        self.edges.append({"i": None, "e": edge, "tag": tag})

    def add_node(self, node: dict) -> None:
        if node["id"] in self.by_id:
            raise AdapterError(f"added node id {node['id']!r} already exists")
        self.nodes.append({"i": None, "n": node})
        self._reindex()

    def remove_node(self, node_id: str, reason: str) -> None:
        self.nodes = [entry for entry in self.nodes if entry["n"]["id"] != node_id]
        self.removed_nodes[node_id] = reason
        self._reindex()

    def compact(self) -> None:
        self.edges = self.live_edges()

    def result(self, adapter_meta: dict) -> dict:
        graph = self.graph
        return {
            "directed": graph["directed"],
            "multigraph": graph["multigraph"],
            "graph": {**graph["graph"], "holojob_adapter": adapter_meta},
            "nodes": [entry["n"] for entry in self.nodes],
            "links": [entry["e"] for entry in self.live_edges()],
            "hyperedges": graph["hyperedges"],
            "built_at_commit": graph["built_at_commit"],
        }


def verify_invariant(raw_input: bytes, work: Work) -> None:
    """Fail closed unless every edge and node outside the declared changes equals the input."""
    fresh = json.loads(raw_input)
    in_edges, in_nodes = fresh["links"], fresh["nodes"]
    seen: set[int] = set()
    for entry in work.live_edges():
        edge, index = entry["e"], entry["i"]
        if index is None:
            if edge.get("_origin") != "adapter" or not edge.get("provenance"):
                raise AdapterError(f"added edge without adapter provenance: {edge}")
            continue
        if index in seen:
            raise AdapterError(f"input edge {index} appears twice")
        seen.add(index)
        if entry["tag"] is None:
            if canon(edge) != canon(in_edges[index]):
                raise AdapterError(f"input edge {index} changed without being declared")
        else:
            if edge.get("_origin") != "adapter" or not edge.get("provenance"):
                raise AdapterError(f"changed edge {index} lacks adapter provenance")
            kept = {k: v for k, v in edge.items() if k not in CHANGEABLE_EDGE_KEYS}
            original = {k: v for k, v in in_edges[index].items() if k not in CHANGEABLE_EDGE_KEYS}
            if canon(kept) != canon(original):
                raise AdapterError(f"changed edge {index} differs in more than its target and provenance")
    removed = set(work.removed_edges)
    if seen & removed or seen | removed != set(range(len(in_edges))):
        raise AdapterError("input edges are not each kept, changed or removed exactly once")
    live_ids = set()
    for entry in work.nodes:
        node, index = entry["n"], entry["i"]
        live_ids.add(node["id"])
        if index is None:
            if node.get("_origin") != "adapter":
                raise AdapterError(f"added node without adapter origin: {node['id']}")
        elif canon(node) != canon(in_nodes[index]):
            raise AdapterError(f"input node {node['id']} changed")
    for node in in_nodes:
        if node["id"] not in live_ids and node["id"] not in work.removed_nodes:
            raise AdapterError(f"input node {node['id']} disappeared without being declared")
    for node_id in work.removed_nodes:
        if node_id in live_ids:
            raise AdapterError(f"removed node {node_id} is still present")
    endpoints = live_ids
    for entry in work.live_edges():
        if entry["e"]["source"] not in endpoints or entry["e"]["target"] not in endpoints:
            raise AdapterError(f"edge points to a missing node: {entry['e']['source']} -> {entry['e']['target']}")


# ---------------------------------------------------------------- freshness


def read_head(root: Path):
    """The commit HEAD points to, read from .git without running git; None if unknown."""
    git = root / ".git"
    try:
        if git.is_file():
            pointer = git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git = (root / pointer[len("gitdir:"):].strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if re.fullmatch(r"[0-9a-f]{40}", head) else None
        ref = head[4:].strip()
        common = git
        commondir = git / "commondir"
        if commondir.is_file():
            common = (git / commondir.read_text(encoding="utf-8").strip()).resolve()
        for base in (git, common):
            if (base / ref).is_file():
                return (base / ref).read_text(encoding="utf-8").strip()
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        return None
    return None


def md5_file(path: Path):
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()  # Graphify's manifest uses md5 of content
    except OSError:
        return None


def freshness(root: Path, graph: dict, manifest) -> dict:
    """Code and semantic freshness. "current" only when every check could be made and passed."""
    head = read_head(root)
    built = graph.get("built_at_commit")
    code = {"head": head, "built_at_commit": built, "changed": [], "missing": [], "new": [], "unchecked": []}
    semantic = {"changed": [], "never_extracted": []}
    if not isinstance(manifest, dict) or not manifest:
        code["status"] = "unknown"
        code["reason"] = "graphify-out/manifest.json is missing or unreadable, so file contents cannot be compared"
        semantic["status"] = "unknown"
        semantic["reason"] = code["reason"]
        return {"code": code, "semantic": semantic}
    hex32 = re.compile(r"[0-9a-f]{32}")
    for path in sorted(manifest):
        entry = manifest[path]
        recorded = entry.get("ast_hash") if isinstance(entry, dict) else None
        if not isinstance(recorded, str) or not hex32.fullmatch(recorded):
            code["unchecked"].append(path)
            continue
        current = md5_file(root / path)
        if current is None:
            code["missing"].append(path)
        elif current != recorded:
            code["changed"].append(path)
    suffixes = {Path(p).suffix for p in manifest if Path(p).suffix}
    code["new"] = [p for p in walk_repo(root) if Path(p).suffix in suffixes and p not in manifest]
    graph_files = {n.get("source_file") for n in graph["nodes"] if n.get("source_file")}
    code["unchecked"] += sorted(f for f in graph_files if f not in manifest)
    if code["changed"] or code["missing"] or code["new"]:
        code["status"] = "possibly stale"
    elif code["unchecked"] or head is None:
        code["status"] = "unknown"
    else:
        code["status"] = "current"
    if code["status"] == "current" and built != head:
        code["note"] = "file contents match the manifest; the graph was built at an earlier commit"
    semantic_files = sorted({n.get("source_file") for n in graph["nodes"]
                             if n.get("_origin") == "semantic" and n.get("source_file")})
    for path in semantic_files:
        entry = manifest.get(path)
        recorded = entry.get("semantic_hash") if isinstance(entry, dict) else None
        if not isinstance(recorded, str) or md5_file(root / path) != recorded:
            semantic["changed"].append(path)
    semantic["never_extracted"] = [p for p in code["new"] if p.endswith(".md")]
    if semantic["changed"] or semantic["never_extracted"]:
        semantic["status"] = "possibly stale"
    else:
        semantic["status"] = "current"
    return {"code": code, "semantic": semantic}


# ------------------------------------------------------------------ report


def _list(items, limit=40) -> list[str]:
    lines = [f"  - `{item}`" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"  - ... and {len(items) - limit} more")
    return lines


def render_report(summary: dict) -> str:
    fresh = summary["freshness"]
    code, semantic = fresh["code"], fresh["semantic"]
    out = [
        "# Holojob graph adapter report",
        "",
        f"Input: `graphify-out/graph.json` sha256 `{summary['input_sha256']}` (unchanged by this run), "
        f"graphify {summary['graphify_version']}, built at commit `{code.get('built_at_commit')}`.",
        "",
        "## Freshness",
        "",
        f"- **Code graph: {code['status']}.** "
        + {
            "current": "Every indexed file matches the content recorded in the manifest, and no new indexable file was found.",
            "possibly stale": "Some files differ from the manifest; run `graphify update .` (AST only, no LLM).",
            "unknown": code.get("reason", "Some files could not be checked against the manifest."),
        }[code["status"]]
        + f" HEAD `{code.get('head')}`."
        + (f" {code['note']}." if code.get("note") else ""),
    ]
    for label, key in (("changed since the build", "changed"), ("missing", "missing"),
                       ("new, not in the graph (may include files Graphify skips on purpose)", "new"),
                       ("not checkable", "unchecked")):
        if code[key]:
            out.append(f"  - {len(code[key])} {label}:")
            out += ["  " + line for line in _list(code[key])]
    out.append(f"- **Doc-to-code links: {summary['doc_links_status']}.**")
    out.append(
        f"- **Semantic documentation: {semantic['status']}.** "
        + ("The LLM-extracted layer may describe older text until a separately approved refresh "
           "(`/graphify --update`); `graphify update .` does not refresh it."
           if semantic["status"] != "current" else
           "No document with extracted concepts changed since the last semantic run.")
    )
    for label, key in (("changed since extraction", "changed"), ("never extracted", "never_extracted")):
        if semantic.get(key):
            out.append(f"  - {len(semantic[key])} {label}:")
            out += ["  " + line for line in _list(semantic[key])]
    for section in summary["sections"]:
        out += ["", *section]
    out += ["", "## Integrity", "",
            f"- Edges: {summary['edges_in']} in, {summary['edges_out']} out; nodes: {summary['nodes_in']} in, {summary['nodes_out']} out.",
            "- Every edge and node outside the changes listed above was checked equal to the input.", ""]
    return "\n".join(out)


# ------------------------------------------------------------------- build


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build(root: Path, graph_path: Path, out_dir: Path, remove: bool = True, review_path: Path | None = None) -> dict:
    raw = graph_path.read_bytes()
    input_sha = sha256_bytes(raw)
    graph = json.loads(raw)
    check_schema(graph)
    manifest_path = graph_path.parent / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None

    work = Work(graph)
    sections: list[list[str]] = []
    counts: Counter = Counter()

    verify_invariant(raw, work)
    index = work.result({"version": 1, "removals": remove, "counts": dict(sorted(counts.items()))})
    summary = {
        "input_sha256": input_sha,
        "graphify_version": graph["graph"].get("graphify_version"),
        "freshness": freshness(root, graph, manifest),
        "doc_links_status": "not built",
        "sections": sections,
        "edges_in": len(graph["links"]),
        "edges_out": len(index["links"]),
        "nodes_in": len(graph["nodes"]),
        "nodes_out": len(index["nodes"]),
    }
    outputs = {"index.json": json.dumps(index, ensure_ascii=False) + "\n", "report.md": render_report(summary)}
    if sha256_bytes(graph_path.read_bytes()) != input_sha:
        raise AdapterError("graph.json changed while the adapter ran; nothing written")
    for name, text in outputs.items():
        write_atomic(out_dir / name, text)
    return {"summary": summary, "index": index, "counts": counts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="read graph.json, write graphify-out/holojob/")
    b.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    b.add_argument("--graph", type=Path, default=None, help="default <root>/graphify-out/graph.json")
    b.add_argument("--out", type=Path, default=None, help="default <root>/graphify-out/holojob")
    b.add_argument("--no-remove", action="store_true", help="report proven-wrong edges but keep them")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    graph_path = args.graph or root / "graphify-out" / "graph.json"
    out_dir = args.out or root / "graphify-out" / OUT_SUBDIR
    try:
        result = build(root, graph_path, out_dir, remove=not args.no_remove)
    except AdapterError as exc:
        print(f"graph adapter: refused: {exc}", file=sys.stderr)
        return 3
    s = result["summary"]
    print(f"graph adapter: wrote {out_dir} ({s['edges_out']} edges, {s['nodes_out']} nodes); "
          f"code graph {s['freshness']['code']['status']}, semantic docs {s['freshness']['semantic']['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
