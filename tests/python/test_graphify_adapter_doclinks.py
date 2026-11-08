"""S5: a doc links to a code file only through an explicit backticked path to exactly that file."""

import json

from graphify_adapter_fixtures import VALIDATE_PATH, Repo, load_module

DOC = """# Notes

The gate is `python/llm/gate.py` and its test `tests/python/test_gate.py:12`.
Again: `python/llm/gate.py#L3`, `./python/llm/gate.py`.
Next to this doc: `local.py`.
Not links: `gate.py`, `llm/gate.py`, `python/llm/*.py`, `python/llm/`, `python/missing.py`,
`data/jobs/x.json`, `docs/Other.md`, `https://x/python/llm/gate.py`, `python/llm/gate.py()`.
Both readings: `python/llm/gate.py` vs doc-relative is the same file, fine.

```
`python/job/client.py` inside a fence is ignored
```

~~~text
`python/job/client.py` also ignored
~~~
"""


def doc_repo(tmp_path, doc=DOC, doc_path="docs/Notes.md"):
    repo = Repo(tmp_path)
    gate = repo.write("python/llm/gate.py", "")
    client = repo.write("python/job/client.py", "")
    test = repo.write("tests/python/test_gate.py", "")
    local = repo.write("docs/local.py", "")
    repo.write("docs/Other.md", "# other\n", file_type="document")
    repo.write(doc_path, doc, node=False)
    return repo, dict(gate=gate, client=client, test=test, local=local)


def doc_edges(result):
    return [e for e in result["index"]["links"] if e.get("provenance") == "doc-path"]


def test_only_exact_paths_outside_fences_are_linked(tmp_path):
    repo, ids = doc_repo(tmp_path)
    result = repo.build()
    edges = doc_edges(result)
    assert {e["target"] for e in edges} == {ids["gate"], ids["test"], ids["local"]}
    gate = [e for e in edges if e["target"] == ids["gate"]][0]
    assert gate["mentions"] == 4 and gate["source_location"] == "L3"
    assert gate["_origin"] == "adapter" and gate["relation"] == "references" and gate["confidence"] == "EXTRACTED"
    doc_node = [n for n in result["index"]["nodes"] if n["id"] == gate["source"]][0]
    assert doc_node["source_file"] == "docs/Notes.md" and doc_node["_origin"] == "adapter"
    assert all(m["target"] != "python/job/client.py" for m in result["details"]["doc_links"])


def test_repo_and_doc_relative_readings_that_differ_are_skipped(tmp_path):
    repo, ids = doc_repo(tmp_path, doc="See `python/llm/gate.py`.\n", doc_path="docs/Notes.md")
    repo.write("docs/python/llm/gate.py", "")  # a second file the same token could mean
    result = repo.build()
    assert doc_edges(result) == []
    assert result["counts"]["S5 skipped: repo- and doc-relative readings differ"] == 1


def test_links_are_rebuilt_from_the_working_tree(tmp_path):
    repo, ids = doc_repo(tmp_path, doc="Uses `python/llm/gate.py`.\n")
    assert len(doc_edges(repo.build())) == 1
    (tmp_path / "docs" / "Notes.md").write_text("Now uses `python/job/client.py`.\n")
    edges = doc_edges(repo.build())
    assert [e["target"] for e in edges] == [ids["client"]]
    report = (tmp_path / "graphify-out" / "holojob" / "report.md").read_text()
    assert "**Doc-to-code links: current" in report


def test_doc_links_are_in_the_architecture_view_only(tmp_path):
    repo, ids = doc_repo(tmp_path, doc="Uses `python/llm/gate.py`.\n")
    repo.build()
    out = tmp_path / "graphify-out" / "holojob"
    arch = json.loads((out / "architecture.json").read_text())
    tests = json.loads((out / "test-deps.json").read_text())
    assert any(e.get("provenance") == "doc-path" for e in arch["links"])
    assert not any(e.get("provenance") == "doc-path" for e in tests["links"])


def test_wilson_lower_bound():
    validate = load_module("holojob_graphify_validate", VALIDATE_PATH)
    assert validate.wilson_lower(200, 200) > 0.98
    assert validate.wilson_lower(199, 200) < 0.98
    assert validate.wilson_lower(0, 0) == 0.0


def test_data_paths_are_never_linked_even_when_indexed(tmp_path):
    repo, _ = doc_repo(tmp_path, doc="Example: `data/examples/profile.json`.\n")
    repo.write("data/examples/profile.json", "{}")
    assert doc_edges(repo.build()) == []
