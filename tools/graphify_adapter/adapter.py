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
import ast
import hashlib
import json
import os
import re
import sys
from collections import Counter
from importlib.machinery import all_suffixes
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
        """source_file -> id of the node that stands for the whole file.

        Its label is the basename, or a longer path suffix where Graphify disambiguates
        (`match_engine/__init__.py`).
        """
        found: dict[str, list[str]] = {}
        for entry in self.nodes:
            node = entry["n"]
            path = node.get("source_file") or ""
            label = node.get("label") or ""
            if path and label and (path == label or path.endswith("/" + label)) \
                    and node.get("source_location") in ("L1", None):
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


# --------------------------------------------------- S2: Python imports
#
# Graphify leaves a bare `import x` as a stub node when x lives in another folder
# and a JavaScript file of the same stem exists (ai_gate.py / ai-gate.js), and a
# package import (`from match_engine import shadow`) as a stub too. The proof
# used here does not depend on sys.path order: every directory of the repo is
# treated as one that could be on sys.path (a superset of every run context:
# script, pytest, the Node-spawned CLIs), plus the installed packages and the
# standard library. When exactly one regular module or package of that name
# exists in that whole set, any successful import of the name loads that file,
# in every context. Anything else stays unresolved.

STDLIB = frozenset(sys.stdlib_module_names) | frozenset(sys.builtin_module_names)
MODULE_SUFFIXES = tuple(sorted(set(all_suffixes()), key=len, reverse=True))
STUB_PREFIX = "ambiguous_python_import_"
IMPORT_EDGE_RELATIONS = frozenset({"imports", "imports_from"})


def module_name(filename: str):
    for suffix in MODULE_SUFFIXES:
        if filename.endswith(suffix):
            name = filename[: -len(suffix)]
            return name if name.isidentifier() else None
    return None


def norm_module_id(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def is_stub(node) -> bool:
    return bool(node) and not node.get("source_file") and (
        bool(node.get("external")) or node["id"].startswith(STUB_PREFIX))


def touches_path(tree: ast.AST) -> bool:
    """A package __init__ that rewrites __path__ can load submodules from anywhere."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__path__" and isinstance(node.ctx, ast.Store):
            return True
        if isinstance(node, ast.Attribute) and node.attr == "__path__" and isinstance(node.ctx, ast.Store):
            return True
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in ("extend_path", "declare_namespace"):
                return True
    return False


def module_level_names(tree: ast.Module) -> set[str]:
    """Names a module binds at top level (any statement outside a def or class body)."""
    names: set[str] = set()

    def stores(node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                names.add(sub.id)

    def visit(stmts):
        for st in stmts:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(st.name)
            elif isinstance(st, ast.Import):
                names.update(a.asname or a.name.split(".")[0] for a in st.names)
            elif isinstance(st, ast.ImportFrom):
                names.update(a.asname or a.name for a in st.names)
            else:
                for field in ("targets", "target", "items"):
                    value = getattr(st, field, None)
                    for item in value if isinstance(value, list) else [value] if value is not None else []:
                        stores(item)
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(st, field, []) or [])
                for handler in getattr(st, "handlers", []) or []:
                    if handler.name:
                        names.add(handler.name)
                    visit(handler.body)
    visit(tree.body)
    return names


class PythonIndex:
    """Every Python module and package file in the repo, by name; parsed lazily."""

    def __init__(self, root: Path, files: list[str]):
        self.root = root
        self.top: dict[str, set[tuple[str, str]]] = {}
        self.by_dir: dict[str, list[str]] = {}
        for path in files:
            parent, _, base = path.rpartition("/")
            self.by_dir.setdefault(parent, []).append(base)
        for parent, bases in self.by_dir.items():
            for base in bases:
                name = module_name(base)
                if name and name != "__init__":
                    self.top.setdefault(name, set()).add(("module", f"{parent}/{base}" if parent else base))
                elif name == "__init__" and parent:
                    pkg = parent.rsplit("/", 1)[-1]
                    if pkg.isidentifier():
                        self.top.setdefault(pkg, set()).add(("package", f"{parent}/{base}"))
        self.py_files = sorted(p for p in files if p.endswith(".py"))
        self._trees: dict[str, object] = {}

    def tree(self, path: str):
        if path not in self._trees:
            try:
                source = (self.root / path).read_text(encoding="utf-8")
                self._trees[path] = (ast.parse(source), source)
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                self._trees[path] = None
        found = self._trees[path]
        return found[0] if found else None

    def source(self, path: str):
        self.tree(path)
        found = self._trees.get(path)
        return found[1] if found else None

    def children(self, init_file: str, part: str) -> set[tuple[str, str]]:
        parent = init_file.rpartition("/")[0]
        found = set()
        for base in self.by_dir.get(parent, []):
            if module_name(base) == part:
                found.add(("module", f"{parent}/{base}"))
        for base in self.by_dir.get(f"{parent}/{part}", []):
            if module_name(base) == "__init__":
                found.add(("package", f"{parent}/{part}/{base}"))
        return found


def installed_top_level(root: Path):
    """Top-level names the repo's .venv can import, or (None, reason) when that cannot be listed."""
    venv = root / ".venv"
    cfg = venv / "pyvenv.cfg"
    if not cfg.is_file():
        return None, "no .venv/pyvenv.cfg"
    if re.search(r"include-system-site-packages\s*=\s*true", cfg.read_text(encoding="utf-8"), re.I):
        return None, ".venv includes the system site-packages"
    site_dirs = sorted(venv.glob("lib/python*/site-packages"))
    if not site_dirs:
        return None, "no site-packages folder in .venv"
    names: set[str] = set()
    pending = list(site_dirs)
    seen: set[Path] = set()
    while pending:
        site = pending.pop()
        if site in seen or not site.is_dir():
            continue
        seen.add(site)
        for entry in sorted(site.iterdir()):
            if entry.suffix == ".pth" and entry.is_file():
                for line in entry.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith(("import ", "import\t")):
                        return None, f"{entry.name} runs code at interpreter start"
                    pending.append((site / line).resolve())
            elif entry.is_dir():
                if entry.name.endswith((".dist-info", ".egg-info", ".data")) or entry.name == "__pycache__":
                    continue
                if any(module_name(p.name) == "__init__" for p in entry.iterdir() if p.is_file()):
                    names.add(entry.name)
            else:
                name = module_name(entry.name)
                if name:
                    names.add(name)
    return names, None


def _is_sys_attr(node, attr: str) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == attr and isinstance(node.value, ast.Name) and node.value.id == "sys"


def scan_import_state(index: PythonIndex) -> list[dict]:
    """Every write to sys.path, sys.modules or the import hooks in the repo's Python files."""
    found = []
    for path in index.py_files:
        tree, source = index.tree(path), index.source(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            kind, name = None, None
            if isinstance(node, ast.ImportFrom) and node.module == "sys" and \
                    {a.name for a in node.names} & {"path", "modules", "meta_path", "path_hooks"}:
                kind = "sys.path"
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                fn = node.func
                if _is_sys_attr(fn.value, "path") and fn.attr in ("insert", "append", "extend", "remove", "pop", "clear"):
                    kind = "sys.path"
                elif _is_sys_attr(fn.value, "meta_path") or _is_sys_attr(fn.value, "path_hooks") or fn.attr == "addsitedir":
                    kind = "import-hook"
                elif _is_sys_attr(fn.value, "modules") and fn.attr in ("update", "setdefault", "__setitem__"):
                    kind = "sys.modules"
                    first = node.args[0] if node.args else None
                    name = first.value if fn.attr != "update" and isinstance(first, ast.Constant) else None
                elif fn.attr == "setitem" and node.args and _is_sys_attr(node.args[0], "modules"):
                    kind = "sys.modules"
                    second = node.args[1] if len(node.args) > 1 else None
                    name = second.value if isinstance(second, ast.Constant) else None
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    base = target.value if isinstance(target, ast.Subscript) else target
                    if _is_sys_attr(base, "path"):
                        kind = "sys.path"
                    elif _is_sys_attr(base, "meta_path") or _is_sys_attr(base, "path_hooks"):
                        kind = "import-hook"
                    elif isinstance(target, ast.Subscript) and _is_sys_attr(target.value, "modules"):
                        kind = "sys.modules"
                        name = target.slice.value if isinstance(target.slice, ast.Constant) else None
            if kind:
                code = " ".join((ast.get_source_segment(source, node) or "").split())
                found.append({"file": path, "line": node.lineno, "kind": kind, "name": name, "code": code})
    return found


def load_review(review_path: Path) -> set[tuple[str, str]]:
    try:
        data = json.loads(review_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as exc:
        raise AdapterError(f"{review_path} is unreadable: {exc}") from exc
    return {(item["file"], item["code"]) for item in data.get("reviewed", [])}


class Resolver:
    def __init__(self, index: PythonIndex, installed, installed_reason, blocked: set[str]):
        self.index = index
        self.installed = installed
        self.installed_reason = installed_reason
        self.blocked = blocked

    def _one(self, found: set, what: str):
        if len(found) != 1:
            listed = ", ".join(sorted(f for _, f in found))
            return "unresolved", f"{len(found)} candidate files for {what}: {listed}"
        kind, path = next(iter(found))
        if kind == "package":
            tree = self.index.tree(path)
            if tree is None:
                return "unresolved", f"{path} could not be parsed"
            if touches_path(tree):
                return "unresolved", f"{path} changes __path__"
        return "resolved", (kind, path)

    def resolve(self, dotted: str):
        """("resolved", (kind, file)) | ("unresolved", reason) | ("external", None)."""
        parts = dotted.split(".")
        top = parts[0]
        found = self.index.top.get(top, set())
        if not found:
            return "external", None
        if self.installed is None:
            return "unresolved", f"installed packages cannot be listed ({self.installed_reason})"
        if top in STDLIB:
            return "unresolved", f"'{top}' is also a standard-library module"
        if top in self.installed:
            return "unresolved", f"an installed package is also named '{top}'"
        if top in self.blocked:
            return "unresolved", f"the repo writes sys.modules['{top}']"
        status, value = self._one(found, f"'{top}'")
        for i, part in enumerate(parts[1:], start=1):
            if status != "resolved":
                break
            kind, path = value
            if kind != "package":
                return "unresolved", f"'{'.'.join(parts[:i])}' is a module, not a package"
            status, value = self._one(self.index.children(path, part), f"'{'.'.join(parts[:i + 1])}'")
        return status, value


def import_statement(tree: ast.Module, line: int, stub_id: str):
    """(statement, module name) of the import on `line` that produced the stub, if exactly one matches."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)) or node.lineno != line:
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and (norm_module_id(node.module) == stub_id or stub_id.startswith(STUB_PREFIX)):
                hits.append((node, node.module))
        else:
            for alias in node.names:
                if norm_module_id(alias.name) == stub_id or stub_id.startswith(STUB_PREFIX):
                    hits.append((node, alias.name))
    return hits[0] if len(hits) == 1 else None


def resolve_python_imports(work: Work, resolver: Resolver) -> tuple[list[str], Counter, dict]:
    counts: Counter = Counter()
    resolved, unresolved, added = [], [], []
    existing = {(e["e"]["source"], e["e"]["target"], e["e"]["relation"]) for e in work.live_edges()}
    touched_stubs: set[str] = set()
    for entry in work.live_edges():
        edge = entry["e"]
        importer = edge.get("source_file") or ""
        if edge["relation"] not in IMPORT_EDGE_RELATIONS or not importer.endswith(".py"):
            continue
        stub = work.node(edge["target"])
        if not is_stub(stub):
            continue
        counts["stub import edges"] += 1
        line = int(str(edge.get("source_location", "L0")).lstrip("L") or 0)
        where = f"{importer}:{line}"
        tree = resolver.index.tree(importer)
        hit = import_statement(tree, line, stub["id"]) if tree is not None else None
        if hit is None:
            if stub["id"].startswith(STUB_PREFIX) or tree is None:
                counts["candidates"] += 1
                unresolved.append((where, stub["id"], "the import statement could not be matched to the edge"))
            else:
                counts["no statement matched (left as is)"] += 1
            continue
        statement, module = hit
        status, value = resolver.resolve(module)
        if status == "external":
            counts["external (standard library, installed or missing)"] += 1
            continue
        counts["candidates"] += 1
        if status == "unresolved":
            unresolved.append((where, module, value))
            continue
        kind, path = value
        target = work.file_nodes.get(path)
        if target is None:
            unresolved.append((where, module, f"{path} has no file node in the graph"))
            continue
        touched_stubs.add(stub["id"])
        key = (edge["source"], target, edge["relation"])
        if key in existing:
            work.kill(entry, "duplicate of an existing edge once re-pointed")
            counts["resolved, already present (stub edge dropped)"] += 1
        else:
            work.replace(entry, {**edge, "target": target, "_origin": "adapter", "provenance": "reconstructed",
                                 "original_target": stub["id"], "resolved_module": module}, "reconstructed")
            existing.add(key)
            counts["resolved (re-pointed)"] += 1
        resolved.append((where, module, path))
        if isinstance(statement, ast.ImportFrom) and kind == "package":
            init_tree = resolver.index.tree(path)
            bound = module_level_names(init_tree) if init_tree is not None else None
            for alias in statement.names:
                if alias.name == "*" or bound is None or alias.name in bound or "__getattr__" in bound:
                    continue
                sub_status, sub_value = resolver._one(resolver.index.children(path, alias.name), f"'{module}.{alias.name}'")
                if sub_status != "resolved":
                    continue
                sub_target = work.file_nodes.get(sub_value[1])
                if sub_target is None:
                    continue
                key = (edge["source"], sub_target, "imports_from")
                if key in existing:
                    counts["submodule edges already present"] += 1
                    continue
                existing.add(key)
                work.add_edge({"source": edge["source"], "target": sub_target, "relation": "imports_from",
                               "confidence": "EXTRACTED", "confidence_score": 1.0, "context": "import",
                               "source_file": importer, "source_location": edge.get("source_location"),
                               "weight": 1.0, "_origin": "adapter", "provenance": "reconstructed",
                               "resolved_module": f"{module}.{alias.name}"}, "reconstructed")
                counts["submodule edges added"] += 1
                added.append((where, f"{module}.{alias.name}", sub_value[1]))
    work.compact()
    in_hyperedges = {n for h in work.graph["hyperedges"] for n in h.get("nodes", [])}
    used = {e["e"]["source"] for e in work.edges} | {e["e"]["target"] for e in work.edges}
    for stub_id in sorted(touched_stubs):
        if stub_id not in used and stub_id not in in_hyperedges:
            work.remove_node(stub_id, "stub with no edges left after S2")
            counts["stub nodes removed"] += 1
    counts["unresolved"] = len(unresolved)
    lines = ["## Python imports (S2)", "",
             "An import is re-pointed only when exactly one module or package of that name exists across every "
             "folder of the repo, the installed packages and the standard library, so it is the same file in every "
             "run context. Everything else stays as Graphify left it.", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(counts.items())]
    by_module = Counter(m for _, m, _ in resolved)
    if resolved:
        lines += ["", "Re-pointed, by module:", ""]
        lines += [f"- `{m}` -> `{p}`: {by_module[m]}" for m, p in sorted({(m, p) for _, m, p in resolved})]
    if added:
        lines += ["", "Submodule edges added (`from package import submodule`):", ""]
        lines += [f"- `{w}` -> `{p}`" for w, _, p in added]
    if unresolved:
        lines += ["", "Unresolved, with the reason:", ""]
        lines += [f"- `{w}` `{m}`: {r}" for w, m, r in unresolved]
    return lines, counts, {"resolved": resolved, "added": added, "unresolved": unresolved}


def check_import_state(index: PythonIndex, review_path: Path) -> set[str]:
    """Refuse unreviewed sys.path / import-hook writes; return names the repo injects into sys.modules."""
    reviewed = load_review(review_path)
    blocked: set[str] = set()
    problems = []
    for item in scan_import_state(index):
        if item["kind"] == "sys.modules" and item["name"]:
            blocked.add(str(item["name"]).split(".")[0])
        elif (item["file"], item["code"]) not in reviewed:
            problems.append(f"{item['file']}:{item['line']} {item['kind']}: {item['code']}")
    if problems:
        raise AdapterError(
            "unreviewed import-state changes (check each target stays inside the repo, then add it to "
            f"{review_path.name}; `adapter.py import-state` lists them):\n  " + "\n  ".join(problems))
    return blocked


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


def build(root: Path, graph_path: Path, out_dir: Path | None, remove: bool = True, review_path: Path | None = None) -> dict:
    """Run every pass; write the outputs to out_dir (None: write nothing, for validate.py)."""
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
    details: dict = {}

    files = list(walk_repo(root))
    index = PythonIndex(root, files)
    blocked = check_import_state(index, review_path or HERE / "sys_path_review.json")
    installed, installed_reason = installed_top_level(root)
    resolver = Resolver(index, installed, installed_reason, blocked)
    lines, s2, details["imports"] = resolve_python_imports(work, resolver)
    sections.append(lines)
    counts.update({f"S2 {k}": v for k, v in s2.items()})

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
    for name, text in outputs.items() if out_dir is not None else ():
        write_atomic(out_dir / name, text)
    return {"summary": summary, "index": index, "counts": counts, "details": details, "resolver": resolver}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="read graph.json, write graphify-out/holojob/")
    b.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    b.add_argument("--graph", type=Path, default=None, help="default <root>/graphify-out/graph.json")
    b.add_argument("--out", type=Path, default=None, help="default <root>/graphify-out/holojob")
    b.add_argument("--no-remove", action="store_true", help="report proven-wrong edges but keep them")
    b.add_argument("--review", type=Path, default=None, help="default tools/graphify_adapter/sys_path_review.json")
    s = sub.add_parser("import-state", help="list every sys.path / sys.modules / import-hook write (JSON)")
    s.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "import-state":
        print(json.dumps(scan_import_state(PythonIndex(root, list(walk_repo(root)))), indent=1))
        return 0
    graph_path = args.graph or root / "graphify-out" / "graph.json"
    out_dir = args.out or root / "graphify-out" / OUT_SUBDIR
    try:
        result = build(root, graph_path, out_dir, remove=not args.no_remove, review_path=args.review)
    except AdapterError as exc:
        print(f"graph adapter: refused: {exc}", file=sys.stderr)
        return 3
    s = result["summary"]
    print(f"graph adapter: wrote {out_dir} ({s['edges_out']} edges, {s['nodes_out']} nodes); "
          f"code graph {s['freshness']['code']['status']}, semantic docs {s['freshness']['semantic']['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
