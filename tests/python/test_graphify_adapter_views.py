"""S4: an architecture view and a test-dependency view, both loadable with graphify --graph."""

import json

from graphify_adapter_fixtures import Repo, adapter


def view_repo(tmp_path):
    repo = Repo(tmp_path)
    core = repo.write("python/llm/gate.py", "def check():\n    return 1\n")
    user = repo.write("python/job/client.py", "import gate\n")
    lonely = repo.write("src/lonely.js", "export const x = 1\n")
    test = repo.write("tests/python/test_gate.py", "import gate\n")
    subprocess_test = repo.write("tests/python/test_cli.py", "CMD = ['python', 'python/job/client.py']\n")
    preset = repo.write("docs/design-system/preset/button.tsx", "export const B = 1\n")
    tool = repo.write("tools/x/helper.py", "")
    deep = repo.write("python/llm/deep.py", "")
    preset_doc = repo.write("docs/design-system/preset/README.md", "# preset\n", file_type="document")
    fixture = repo.write("tests/python/fixtures/sample.py", "")
    repo.edge(core, deep, "imports", "python/llm/gate.py", 1)
    repo.edge(user, deep, "shares_data_with", "python/job/client.py", 1, _origin="semantic", confidence="INFERRED")
    repo.write("docs/A.md", "# A\n", node=False)
    concept = repo.add_node("docs_a_idea", "An idea", "docs/A.md", file_type="concept", _origin="semantic")
    repo.edge(user, core, "imports", "python/job/client.py", 1)
    repo.edge(test, core, "imports", "tests/python/test_gate.py", 1)
    repo.edge(preset, core, "references", "docs/design-system/preset/button.tsx", 1)
    repo.edge(concept, core, "references", "docs/A.md", 1, _origin="semantic")
    repo.edge(tool, core, "imports", "tools/x/helper.py", 1)
    repo.edge(user, repo.stub("json"), "imports", "python/job/client.py", 1)
    repo.hyperedges.append({"id": "h", "nodes": [concept, core], "relation": "form", "source_file": "docs/A.md"})
    return repo, dict(core=core, user=user, lonely=lonely, test=test, subprocess_test=subprocess_test,
                      preset=preset, tool=tool, concept=concept, deep=deep, preset_doc=preset_doc, fixture=fixture)


def load(tmp_path, name):
    return json.loads((tmp_path / "graphify-out" / "holojob" / name).read_text())


def test_architecture_view_keeps_production_and_docs_only(tmp_path):
    repo, ids = view_repo(tmp_path)
    repo.build()
    view = load(tmp_path, "architecture.json")
    kept = {n["id"] for n in view["nodes"]}
    assert {ids["core"], ids["user"], ids["lonely"], ids["concept"]} <= kept
    assert not kept & {ids["test"], ids["preset"], ids["tool"], ids["preset_doc"], ids["fixture"], "json"}
    assert {(e["source"], e["target"]) for e in view["links"]} == {
        (ids["user"], ids["core"]), (ids["concept"], ids["core"]), (ids["core"], ids["deep"]), (ids["user"], ids["deep"])}
    assert [h["id"] for h in view["hyperedges"]] == ["h"]
    assert set(view) == adapter().TOP_KEYS and view["graph"]["holojob_view"] == "architecture"


def test_test_dependency_view_keeps_code_edges_from_tests(tmp_path):
    repo, ids = view_repo(tmp_path)
    repo.build()
    view = load(tmp_path, "test-deps.json")
    kept = {n["id"] for n in view["nodes"]}
    assert {ids["core"], ids["user"], ids["test"]} <= kept
    assert not kept & {ids["concept"], ids["preset"], ids["tool"], ids["fixture"], "json"}
    assert all(e.get("_origin") in ("ast", "adapter") for e in view["links"])
    assert (ids["user"], ids["deep"]) not in {(e["source"], e["target"]) for e in view["links"]}  # semantic
    assert view["hyperedges"] == [] and view["graph"]["hyperedges"] == []
    node_ids = {n["id"] for n in view["nodes"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in view["links"])


def test_static_test_reference_summary(tmp_path):
    repo, _ = view_repo(tmp_path)
    repo.build()
    report = (tmp_path / "graphify-out" / "holojob" / "report.md").read_text()
    assert "- imported directly by a test: 1" in report  # gate.py
    assert "- reached through imports (direct or via other modules): 2" in report  # gate.py, deep.py
    assert "- referenced by a test only as a path string (e.g. a subprocess): 1" in report  # client.py
    assert "- no static test reference: 1" in report and "`src/lonely.js`" in report
    assert "not runtime coverage" in report
