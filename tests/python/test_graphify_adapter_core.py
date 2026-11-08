"""S1: the adapter reads graph.json without changing it, is deterministic and fails closed."""

import ast
import hashlib
import json

import pytest

from graphify_adapter_fixtures import ADAPTER_PATH, Repo, adapter


def small_repo(tmp_path):
    repo = Repo(tmp_path)
    a = repo.write("pkg/a.py", "import os\n")
    b = repo.write("pkg/b.py", "def f():\n    return 1\n")
    repo.edge(a, b, "calls", "pkg/a.py", 1)
    repo.edge(a, repo.stub("os"), "imports", "pkg/a.py", 1)
    return repo


def test_identity_pass_keeps_every_edge_and_node(tmp_path):
    repo = small_repo(tmp_path)
    graph_path = repo.save()
    before = graph_path.read_bytes()
    result = repo.build()
    index = json.loads((tmp_path / "graphify-out" / "holojob" / "index.json").read_text())
    original = json.loads(before)
    assert index["links"] == original["links"]
    assert index["nodes"] == original["nodes"]
    assert graph_path.read_bytes() == before
    assert result["summary"]["input_sha256"] == hashlib.sha256(before).hexdigest()


def test_two_runs_write_identical_files(tmp_path):
    repo = small_repo(tmp_path)
    repo.save()
    out = tmp_path / "graphify-out" / "holojob"
    repo.build()
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    repo.build()
    second = {p.name: p.read_bytes() for p in out.iterdir()}
    assert first == second


def test_schema_or_version_mismatch_is_refused(tmp_path):
    repo = small_repo(tmp_path)
    graph = repo.graph()
    graph["graph"]["graphify_version"] = "0.10.0"
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    with pytest.raises(adapter().AdapterError, match="pinned"):
        repo.build()
    assert not (tmp_path / "graphify-out" / "holojob").exists()
    graph = repo.graph()
    del graph["hyperedges"]
    (tmp_path / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    with pytest.raises(adapter().AdapterError, match="top-level keys"):
        repo.build()


def test_cli_refusal_exits_non_zero(tmp_path, capsys):
    repo = small_repo(tmp_path)
    graph = repo.graph()
    graph["graph"]["schema_version"] = 2
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    assert adapter().main(["build", "--root", str(tmp_path)]) == 3
    assert "refused" in capsys.readouterr().err


def test_undeclared_change_fails_the_invariant(tmp_path):
    mod = adapter()
    repo = small_repo(tmp_path)
    raw = json.dumps(repo.graph()).encode()
    work = mod.Work(json.loads(raw))
    work.edges[0]["e"] = {**work.edges[0]["e"], "relation": "uses"}
    with pytest.raises(mod.AdapterError, match="changed without being declared"):
        mod.verify_invariant(raw, work)
    work = mod.Work(json.loads(raw))
    work.edges.pop()
    with pytest.raises(mod.AdapterError, match="exactly once"):
        mod.verify_invariant(raw, work)
    work = mod.Work(json.loads(raw))
    work.replace(work.edges[0], {**work.edges[0]["e"], "target": "pkg_a_py", "_origin": "adapter",
                                 "provenance": "reconstructed", "relation": "uses"}, "reconstructed")
    with pytest.raises(mod.AdapterError, match="more than its target"):
        mod.verify_invariant(raw, work)


def test_adapter_imports_only_allowed_standard_modules():
    tree = ast.parse(ADAPTER_PATH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module.split(".")[0])
    allowed = {"__future__", "argparse", "ast", "builtins", "hashlib", "json", "os", "re", "sys",
               "collections", "pathlib", "importlib"}
    assert imported <= allowed, imported - allowed
    assert not imported & {"socket", "urllib", "http", "subprocess", "requests", "ssl"}
    src = ADAPTER_PATH.read_text()
    assert "import_module" not in src and "exec_module" not in src and "__import__" not in src


def freshness_of(repo):
    return repo.build()["summary"]["freshness"]


def test_freshness_current_only_when_contents_match(tmp_path):
    repo = small_repo(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / ".git" / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    repo.save()
    fresh = freshness_of(repo)
    assert fresh["code"]["status"] == "current"
    assert fresh["code"]["head"] == "a" * 40
    assert "earlier commit" in fresh["code"]["note"]


def test_freshness_possibly_stale_on_uncommitted_edit_or_new_file(tmp_path):
    repo = small_repo(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("b" * 40 + "\n")
    repo.save()
    (tmp_path / "pkg" / "b.py").write_text("def f():\n    return 2\n")
    fresh = freshness_of(repo)
    assert fresh["code"]["status"] == "possibly stale"
    assert fresh["code"]["changed"] == ["pkg/b.py"]
    (tmp_path / "pkg" / "b.py").write_text("def f():\n    return 1\n")
    (tmp_path / "pkg" / "c.py").write_text("")
    fresh = freshness_of(repo)
    assert fresh["code"]["status"] == "possibly stale"
    assert fresh["code"]["new"] == ["pkg/c.py"]


def test_freshness_unknown_without_manifest_or_head(tmp_path):
    repo = small_repo(tmp_path)
    repo.save(manifest=False)
    fresh = freshness_of(repo)
    assert fresh["code"]["status"] == "unknown"
    assert fresh["semantic"]["status"] == "unknown"
    repo.save()
    assert freshness_of(repo)["code"]["status"] == "unknown"  # no .git: HEAD cannot be read


def test_semantic_freshness_flags_changed_docs(tmp_path):
    repo = small_repo(tmp_path)
    repo.write("docs/A.md", "# A\n", node=False)
    repo.add_node("docs_a_concept", "A concept", "docs/A.md", file_type="concept", _origin="semantic")
    repo.save()
    assert freshness_of(repo)["semantic"]["status"] == "current"
    (tmp_path / "docs" / "A.md").write_text("# A changed\n")
    fresh = freshness_of(repo)
    assert fresh["semantic"]["status"] == "possibly stale"
    assert fresh["semantic"]["changed"] == ["docs/A.md"]
    report = (tmp_path / "graphify-out" / "holojob" / "report.md").read_text()
    assert "**Code graph: " in report and "**Doc-to-code links: " in report and "**Semantic documentation: possibly stale" in report
