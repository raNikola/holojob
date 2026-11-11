import json
import os
import stat

import pytest

import confirmed_facts as cf


def clock(stamp="2026-11-11T10:00:00Z"):
    return lambda: stamp


def write(path, facts, version=2):
    path.write_text(json.dumps({"version": version, "facts": facts}))


def test_v1_reads_as_v2_without_rewriting(tmp_path):
    p = tmp_path / "f.json"
    write(p, [{"competencyId": "a", "has": True, "note": "n"}, {"competencyId": "b", "has": False}], version=1)
    before = p.read_text()
    facts = cf.load(p)
    assert [(f["competencyId"], f["answer"]) for f in facts] == [("a", "yes"), ("b", "no")]
    assert facts[0]["qualifier"] is None and facts[0]["answeredAt"] is None
    assert facts[0]["overrules"] == [] and facts[0]["coveredTexts"] == [] and facts[0]["history"] == []
    assert facts[0]["note"] == "n"
    assert p.read_text() == before


def test_missing_file_is_empty(tmp_path):
    assert cf.load(tmp_path / "none.json") == []


def test_save_writes_version_2_and_mode_600(tmp_path):
    p = tmp_path / "sub" / "f.json"
    cf.save(cf.load(p) + [cf._valid({"competencyId": "a", "has": True})], p)
    assert json.loads(p.read_text())["version"] == 2
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700


def test_one_live_fact_per_id(tmp_path):
    p = tmp_path / "f.json"
    write(p, [{"competencyId": "a", "answer": "yes"}, {"competencyId": "a", "answer": "no"}])
    assert [f["answer"] for f in cf.load(p)] == ["no"]
    cf.save([{"competencyId": "a", "answer": "yes"}, {"competencyId": "a", "answer": "partly"}], p)
    assert len(json.loads(p.read_text())["facts"]) == 1


@pytest.mark.parametrize("bad", [
    {"answer": "maybe"},
    {"answer": "yes", "qualifier": {"kind": "years", "value": 41}},
    {"answer": "yes", "qualifier": {"kind": "years", "value": -1}},
    {"answer": "yes", "qualifier": {"kind": "months", "value": 3}},
    {"answer": "yes", "qualifier": {"kind": "years", "value": True}},
])
def test_invalid_entries_dropped(tmp_path, bad):
    p = tmp_path / "f.json"
    write(p, [{"competencyId": "a", **bad}, {"competencyId": "ok", "answer": "yes", "qualifier": {"kind": "years", "value": 40}}])
    assert [f["competencyId"] for f in cf.load(p)] == ["ok"]


def test_record_moves_old_answer_to_history(tmp_path):
    p = tmp_path / "f.json"
    cf.record_answer("a", "yes", via="queue", qualifier={"kind": "years", "value": 3}, path=p, now=clock("t1"))
    fact = cf.record_answer("a", "no", via="edit", path=p, now=clock("t2"))
    assert fact["answer"] == "no" and fact["answeredAt"] == "t2"
    assert fact["history"] == [{"answer": "yes", "qualifier": {"kind": "years", "value": 3}, "at": "t1", "via": "edit"}]
    assert cf.load(p) == [fact]


def test_history_capped_at_20_newest_kept(tmp_path):
    p = tmp_path / "f.json"
    for i in range(25):
        cf.record_answer("a", "yes" if i % 2 else "partly", via="edit", path=p, now=clock(f"t{i}"))
    history = cf.load(p)[0]["history"]
    assert len(history) == 20
    assert history[-1]["at"] == "t23" and history[0]["at"] == "t4"


def test_revoke_keeps_history_and_sets_unknown(tmp_path):
    p = tmp_path / "f.json"
    cf.record_answer("a", "yes", via="queue", note="mine", path=p, now=clock("t1"))
    fact = cf.revoke("a", path=p, now=clock("t2"))
    assert fact["answer"] == "unknown" and fact["note"] == "mine"
    assert fact["history"] == [{"answer": "yes", "qualifier": None, "at": "t1", "via": "revoke"}]
    assert cf.revoke("missing", path=p) is None


def test_covered_texts_and_overrules_round_trip(tmp_path):
    p = tmp_path / "f.json"
    cf.record_answer("a", "yes", via="conflict", covered_texts=["x y", "z"], overrules=["ev1"], path=p, now=clock())
    fact = cf.load(p)[0]
    assert fact["coveredTexts"] == ["x y", "z"] and fact["overrules"] == ["ev1"]
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_record_rejects_bad_input(tmp_path):
    with pytest.raises(ValueError):
        cf.record_answer("a", "yes", via="nope", path=tmp_path / "f.json")
    with pytest.raises(ValueError):
        cf.record_answer("a", "bad", via="edit", path=tmp_path / "f.json")
