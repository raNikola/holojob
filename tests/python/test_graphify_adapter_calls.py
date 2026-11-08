"""S3: an inferred edge is removed only when the call site provably names something else."""

import pytest

from graphify_adapter_fixtures import Repo


def call_repo(tmp_path, source_text, line, name="handler", target_text=None, relation="calls", extra=None):
    """source.py refers to `name` at `line`; Graphify inferred it is target.py's function."""
    repo = Repo(tmp_path)
    source = repo.write("python/app/source.py", source_text)
    repo.write("python/lib/target.py", target_text or f"def {name}():\n    return 1\n")
    fn = repo.add_node("target_fn", f"{name}()", "python/lib/target.py", location="L1")
    for path, text in (extra or {}).items():
        repo.write(path, text)
    repo.edge(source, fn, relation, "python/app/source.py", line, confidence="INFERRED")
    return repo


def removed(repo, **kwargs):
    result = repo.build(**kwargs)
    return result["details"]["removals"]["removed"], result


@pytest.mark.parametrize("text,line,reason", [
    ("def run(handler):\n    return handler()\n", 2, "a parameter"),
    ("def run():\n    handler = open('x')\n    return handler()\n", 3, "a local variable"),
    ("def run():\n    with open('x') as handler:\n        return len(handler)\n", 3, "a local variable"),
    ("def run():\n    return list(map(lambda handler: handler, []))\n", 2, "a parameter"),
    ("def handler():\n    return 2\n\nhandler()\n", 4, "a def of that name in this file"),
    ("from dataclasses import replace as handler\nhandler()\n", 2, "standard library"),
    ("handler = open\nhandler('x')\n", 2, "a module variable"),
])
def test_names_bound_to_something_else_are_removed(tmp_path, text, line, reason):
    found, result = removed(call_repo(tmp_path, text, line))
    assert len(found) == 1 and reason in found[0]["reason"]
    assert not [e for e in result["index"]["links"] if e["target"] == "target_fn"]


def test_builtin_name_is_removed(tmp_path):
    found, _ = removed(call_repo(tmp_path, "print('x')\n", 1, name="print"))
    assert found[0]["reason"] == "the name is a Python builtin here"


def test_imported_from_a_file_that_defines_it_is_removed(tmp_path):
    repo = call_repo(tmp_path, "from fitmod import handler\nhandler()\n", 2,
                     extra={"python/engine/fitmod.py": "def handler():\n    return 3\n"})
    found, _ = removed(repo)
    assert "python/engine/fitmod.py, which defines it" in found[0]["reason"]


@pytest.mark.parametrize("text,line,why", [
    # dependency injection: the file imports the target (graph edge), so a parameter may be the target
    ("import libalias\n\ndef run(handler=None):\n    return handler()\n", 4, "imports"),
    # load by path: the target's file name appears in the source
    ("SPEC = 'lib/target.py'\n\ndef run(handler):\n    return handler()\n", 4, "named"),
    # getattr / dict dispatch: no bare name at the line
    ("import importlib\nfn = getattr(importlib, 'handler')\nfn()\n", 3, "no bare name"),
    ("TABLE = {}\nTABLE['handler']()\n", 2, "no bare name"),
    # re-export: imported from a module that only re-exports it
    ("from facade import handler\nhandler()\n", 2, "not proven"),
    # alias: the value names it
    ("def run(obj):\n    handler = obj.handler\n    return handler()\n", 3, "not proven"),
    # a class attribute is not visible inside the class's methods
    ("class C:\n    handler = 1\n\n    def m(self):\n        return handler()\n", 5, "not proven"),
    # global and star import
    ("def run():\n    global handler\n    return handler()\n", 3, "not proven"),
    ("from facade import *\nhandler()\n", 2, "not proven"),
    # module.attribute of the same name
    ("import json as handler\nhandler.handler()\n", 2, "not proven"),
])
def test_unproven_cases_are_kept(tmp_path, text, line, why):
    extra = {"python/engine/facade.py": "from target import handler\n"}
    repo = call_repo(tmp_path, text, line, extra=extra)
    if why == "imports":
        repo.edge("python_app_source_py", "python_lib_target_py", "imports", "python/app/source.py", 1)
    found, result = removed(repo)
    assert found == []
    assert [e for e in result["index"]["links"] if e["target"] == "target_fn"]


def test_extracted_edges_and_javascript_are_never_touched(tmp_path):
    repo = call_repo(tmp_path, "def run(handler):\n    return handler()\n", 2)
    repo.links[0]["confidence"] = "EXTRACTED"
    assert removed(repo)[0] == []
    repo = Repo(tmp_path / "js")
    src = repo.write("src/a.js", "handler = 1\nhandler\n")  # also valid Python: only the .py check keeps it
    repo.write("src/b.js", "export function handler() {}\n")
    repo.add_node("b_handler", "handler()", "src/b.js")
    repo.edge(src, "b_handler", "calls", "src/a.js", 2, confidence="INFERRED")
    assert removed(repo)[0] == []


def test_no_remove_reports_but_keeps(tmp_path):
    repo = call_repo(tmp_path, "def run(handler):\n    return handler()\n", 2)
    found, result = removed(repo, remove=False)
    assert len(found) == 1
    assert [e for e in result["index"]["links"] if e["target"] == "target_fn"]
    assert result["counts"]["S3 would be removed (--no-remove)"] == 1


def test_the_targets_own_module_object_is_not_proven_wrong(tmp_path):
    from graphify_adapter_fixtures import adapter

    repo = call_repo(tmp_path, "import target\nlist([target])\n", 2, name="target")
    resolver = repo.build()["resolver"]
    wrong, why = adapter().binding_verdict(resolver, "python/app/source.py", 2, "target", "python/lib/target.py")
    assert wrong is False and "own module" in why
    wrong, _ = adapter().binding_verdict(resolver, "python/app/source.py", 2, "target", "python/other.py")
    assert wrong is True


def test_global_declaration_reaches_the_module_binding(tmp_path):
    text = "def handler():\n    return 2\n\ndef run():\n    global handler\n    return handler()\n"
    found, _ = removed(call_repo(tmp_path, text, 6))
    assert found and "a def of that name in this file" in found[0]["reason"]
