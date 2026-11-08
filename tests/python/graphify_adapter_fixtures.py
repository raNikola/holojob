"""Synthetic repositories and graphs for the Graphify adapter tests (no real graph needed)."""

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "tools" / "graphify_adapter" / "adapter.py"
VALIDATE_PATH = ROOT / "tools" / "graphify_adapter" / "validate.py"


_LOADED = {}


def load_module(name, path):
    """Load a tool module by path, once, without registering it as an importable name."""
    if name not in _LOADED:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED[name] = module
    return _LOADED[name]


def adapter():
    return load_module("holojob_graphify_adapter", ADAPTER_PATH)


def node_id(path):
    return path.replace("/", "_").replace(".", "_").replace("-", "_").lower()


class Repo:
    """A tiny repo on disk plus a Graphify-shaped graph.json that describes it."""

    def __init__(self, root: Path):
        self.root = root
        self.nodes = []
        self.links = []
        self.hyperedges = []
        (root / ".venv" / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
        (root / ".venv" / "pyvenv.cfg").write_text("include-system-site-packages = false\n")

    def write(self, path, text="", node=True, file_type="code"):
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        if node:
            self.add_node(node_id(path), path.rsplit("/", 1)[-1], path, file_type=file_type)
        return node_id(path)

    def add_node(self, nid, label, source_file, file_type="code", location="L1", **extra):
        self.nodes.append({"id": nid, "label": label, "file_type": file_type, "source_file": source_file,
                           "source_location": location, "_origin": extra.pop("_origin", "ast"), **extra})
        return nid

    def stub(self, name):
        if not any(n["id"] == name for n in self.nodes):
            self.nodes.append({"id": name, "label": name, "file_type": "concept", "source_file": "",
                               "external": True, "type": "external"})
        return name

    def edge(self, source, target, relation, source_file, line, confidence="EXTRACTED", **extra):
        self.links.append({"source": source, "target": target, "relation": relation, "_origin": extra.pop("_origin", "ast"),
                           "confidence": confidence, "confidence_score": 1.0 if confidence == "EXTRACTED" else 0.85,
                           "source_file": source_file, "source_location": f"L{line}", "weight": 1.0, **extra})

    def graph(self):
        return {"directed": False, "multigraph": False,
                "graph": {"hyperedges": self.hyperedges, "schema_version": 1, "graphify_version": "0.9.103"},
                "nodes": self.nodes, "links": self.links, "hyperedges": self.hyperedges,
                "built_at_commit": None}

    def save(self, manifest=True):
        out = self.root / "graphify-out"
        out.mkdir(exist_ok=True)
        (out / "graph.json").write_text(json.dumps(self.graph()), encoding="utf-8")
        if manifest:
            files = {}
            for n in self.nodes:
                path = n.get("source_file")
                if path and (self.root / path).is_file():
                    digest = hashlib.md5((self.root / path).read_bytes()).hexdigest()
                    files[path] = {"ast_hash": digest, "semantic_hash": digest}
            (out / "manifest.json").write_text(json.dumps(files), encoding="utf-8")
        return out / "graph.json"

    def build(self, **kwargs):
        graph_path = self.root / "graphify-out" / "graph.json"
        if not graph_path.exists():
            self.save()
        kwargs.setdefault("review_path", self.root / "sys_path_review.json")
        return adapter().build(self.root, graph_path, self.root / "graphify-out" / "holojob", **kwargs)


def review(repo, entries):
    (repo.root / "sys_path_review.json").write_text(json.dumps({"reviewed": entries}), encoding="utf-8")
