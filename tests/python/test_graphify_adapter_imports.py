"""S2: only imports that resolve to one file in every run context are re-pointed."""

import json
import sys

import pytest

from graphify_adapter_fixtures import VALIDATE_PATH, Repo, adapter, load_module, review


def index_of(repo):
    repo.build()
    return json.loads((repo.root / "graphify-out" / "holojob" / "index.json").read_text())


def edges_from(index, source):
    return [e for e in index["links"] if e["source"] == source]


def two_folder_repo(tmp_path):
    """llm/gate.py imported from scoring/client.py: another folder, as ai_gate is from job_scoring."""
    repo = Repo(tmp_path)
    client = repo.write("python/scoring/client.py", "import gate\nimport json\n")
    repo.write("python/llm/gate.py", "def check():\n    return True\n")
    repo.write("scripts/gate.js", "export const x = 1\n")
    repo.edge(client, repo.stub("gate"), "imports", "python/scoring/client.py", 1)
    repo.edge(client, repo.stub("json"), "imports", "python/scoring/client.py", 2)
    return repo, client


def test_unique_module_in_another_folder_is_reconstructed(tmp_path):
    repo, client = two_folder_repo(tmp_path)
    index = index_of(repo)
    by_target = {e["target"]: e for e in edges_from(index, client)}
    edge = by_target["python_llm_gate_py"]
    assert edge["provenance"] == "reconstructed" and edge["_origin"] == "adapter"
    assert edge["original_target"] == "gate" and edge["resolved_module"] == "gate"
    assert by_target["json"] == repo.graph()["links"][1]  # standard library: untouched
    assert "gate" not in {n["id"] for n in index["nodes"]}  # the emptied stub is dropped
    assert "json" in {n["id"] for n in index["nodes"]}


def test_two_candidate_files_stay_unresolved(tmp_path):
    repo = Repo(tmp_path)
    a = repo.write("python/a/user.py", "from text_utils import norm\n")
    repo.write("python/a/text_utils.py", "def norm(): ...\n")
    repo.write("python/b/text_utils.py", "def norm(): ...\n")
    repo.edge(a, repo.add_node("ambiguous_python_import_0123456789ab", "x", "", file_type="concept", external=True),
              "imports_from", "python/a/user.py", 1)
    result = repo.build()
    index = json.loads((tmp_path / "graphify-out" / "holojob" / "index.json").read_text())
    assert index["links"] == repo.graph()["links"]
    unresolved = result["details"]["imports"]["unresolved"]
    assert unresolved == [("python/a/user.py:1", "text_utils",
                           "2 candidate files for 'text_utils': python/a/text_utils.py, python/b/text_utils.py")]


@pytest.mark.parametrize("make,reason", [
    (lambda root: (root / ".venv/lib/python3.12/site-packages/gate").mkdir(parents=True)
     or (root / ".venv/lib/python3.12/site-packages/gate/__init__.py").write_text(""), "installed package"),
    (lambda root: (root / ".venv/lib/python3.12/site-packages/x.pth").write_text("import os\n"), "runs code"),
    (lambda root: (root / ".venv/pyvenv.cfg").write_text("include-system-site-packages = true\n"), "system site"),
])
def test_installed_packages_shadow_or_unknown_leave_it_unresolved(tmp_path, make, reason):
    repo, client = two_folder_repo(tmp_path)
    make(tmp_path)
    result = repo.build()
    [(_, _, why)] = result["details"]["imports"]["unresolved"]
    assert reason in why
    assert all(e.get("_origin") != "adapter" for e in result["index"]["links"])


def test_stdlib_name_in_repo_stays_unresolved(tmp_path):
    repo = Repo(tmp_path)
    user = repo.write("python/a/user.py", "import secrets\n")
    repo.write("python/llm/secrets.py", "")
    repo.edge(user, repo.stub("secrets"), "imports", "python/a/user.py", 1)
    [(_, _, why)] = repo.build()["details"]["imports"]["unresolved"]
    assert "standard-library" in why


def test_sys_modules_injection_blocks_the_name(tmp_path):
    repo, _ = two_folder_repo(tmp_path)
    repo.write("tests/test_x.py", "import sys\nsys.modules['gate'] = object()\n", node=False)
    [(_, _, why)] = repo.build()["details"]["imports"]["unresolved"]
    assert "sys.modules['gate']" in why


def test_unreviewed_sys_path_change_refuses_the_build(tmp_path):
    repo, _ = two_folder_repo(tmp_path)
    repo.write("python/run.py", "import sys\nsys.path.insert(0, '/elsewhere')\n", node=False)
    with pytest.raises(adapter().AdapterError, match="unreviewed import-state"):
        repo.build()
    assert not (tmp_path / "graphify-out" / "holojob").exists()
    review(repo, [{"file": "python/run.py", "code": "sys.path.insert(0, '/elsewhere')"}])
    assert repo.build()["details"]["imports"]["resolved"]


def package_repo(tmp_path, init_text):
    repo = Repo(tmp_path)
    user = repo.write("tests/test_engine.py", "from engine import shadow, helper\n")
    repo.write("python/engine/__init__.py", init_text)
    repo.write("python/engine/shadow.py", "")
    repo.write("python/engine/helper.py", "")
    repo.edge(user, repo.stub("engine"), "imports_from", "tests/test_engine.py", 1)
    return repo, user


def test_package_import_points_to_init_and_adds_submodule_edges(tmp_path):
    repo, user = package_repo(tmp_path, "from engine.helper import thing as helper\n")
    index = index_of(repo)
    targets = sorted(e["target"] for e in edges_from(index, user))
    # helper is bound by __init__ itself, so it is the attribute, not a submodule edge
    assert targets == ["python_engine___init___py", "python_engine_shadow_py"]
    added = [e for e in edges_from(index, user) if e["target"] == "python_engine_shadow_py"][0]
    assert added["provenance"] == "reconstructed" and added["resolved_module"] == "engine.shadow"


def test_package_that_rewrites_path_stays_unresolved(tmp_path):
    repo, _ = package_repo(tmp_path, "__path__ = __import__('pkgutil').extend_path(__path__, __name__)\n")
    [(_, _, why)] = repo.build()["details"]["imports"]["unresolved"]
    assert "__path__" in why


def test_resolved_duplicate_is_dropped_not_doubled(tmp_path):
    repo, client = two_folder_repo(tmp_path)
    repo.edge(client, "python_llm_gate_py", "imports", "python/scoring/client.py", 1)
    result = repo.build()
    links = [e for e in result["index"]["links"] if e["source"] == client and e["target"] == "python_llm_gate_py"]
    assert len(links) == 1 and links[0].get("_origin") == "ast"
    assert result["counts"]["S2 resolved, already present (stub edge dropped)"] == 1


def test_isolated_lookup_runs_no_project_code(tmp_path):
    validate = load_module("holojob_graphify_validate", VALIDATE_PATH)
    marker = tmp_path / "executed"
    pkg = tmp_path / "sentinel_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    (pkg / "sub.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    answers = validate.find_specs(sys.executable, [
        {"name": "sentinel_pkg", "path": [str(tmp_path)]},
        {"name": "sentinel_pkg.sub", "path": [str(pkg)]},
    ])
    assert answers[0]["origin"] == str(pkg / "__init__.py")
    assert answers[1]["origin"] == str(pkg / "sub.py")
    assert not marker.exists()
