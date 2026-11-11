"""AI batch grouping (M5): code rules on recorded model answers, a fake `complete`, temp dirs only."""

import json
import stat

import competency_grouping as cg
import competency_mapping as cm

COMPS = [
    {"id": "acceptance-criteria", "definition": "Writing acceptance criteria.", "kind": "skill", "aliases": []},
    {"id": "juggling-degree", "definition": "A degree in juggling.", "kind": "education", "aliases": []},
]
PRICE = {"in": 1.0, "out": 1.0}


def mapper(tmp_path, learned=None):
    path = tmp_path / "aliases.json"
    if learned:
        path.write_text(json.dumps(learned))
    return cm.Mapper(COMPS, path, tmp_path / "remap.json")


def job(*texts, kind="skill", **extra):
    reqs = [{"text": t, "kind": kind, "id": "prov:" + str(abs(hash(t)))} for t in texts]
    return {"jobId": "x", "llmFacts": {"requirements": reqs}, **extra}


def fake(answers, calls=None):
    def complete(prompt):
        if calls is not None:
            calls.append(prompt)
        return {"answers": [{"n": n, "answer": a, "confidence": c} for n, (a, c) in enumerate(answers)]}
    return complete


def go(tmp_path, jobs, answers, m=None, **kw):
    m = m or mapper(tmp_path)
    r = cg.run(jobs, m, tmp_path / "cache" / "g.json", complete=fake(answers), price=PRICE, confirm=True, **kw)
    return r, m


def test_high_same_as_is_auto(tmp_path):
    r, m = go(tmp_path, [job("Defining acceptance criteria")], [("same_as: acceptance-criteria", "high")])
    assert r["auto"] == 1
    assert m.learned["defining acceptance criteria"] == {"competencyId": "acceptance-criteria", "status": "auto"}


def test_rejections_go_to_pending(tmp_path):
    jobs = [job("a one"), job("b two"), job("c three"), job("d four"), job("e five")]
    answers = [("same_as: juggling-degree", "high"), ("same_as: nope", "high"),
               ("same_as: acceptance-criteria", "uncertain"), ("none", "high"), ("group: lonely", "high")]
    r, m = go(tmp_path, jobs, answers)
    assert r["auto"] == 0 and r["pending"] == 5 and m.learned == {}


def test_groups_stable_id_and_spec_examples(tmp_path):
    jobs = [job("Writing acceptance criteria", "Defining acceptance criteria", "A/B testing", "Statistical experiment design")]
    answers = [("group: acceptance criteria", "high"), ("group: Acceptance criteria", "high"),
               ("none", "high"), ("none", "high")]
    r, m = go(tmp_path, jobs, answers)
    a, b = (m.learned[k] for k in ("writing acceptance criteria", "defining acceptance criteria"))
    assert a == b and a["status"] == "auto" and a["competencyId"] == cg.group_id("acceptance criteria")
    assert a["competencyId"].startswith("grp:") and r["groups"] == 1 and r["groupCandidates"] == [a["competencyId"]]
    assert "a/b testing" not in m.learned and "statistical experiment design" not in m.learned
    assert cm.Mapper(COMPS, tmp_path / "aliases.json").learned  # group links survive a reload


def test_link_confirm_and_coverage():
    group = ["Writing acceptance criteria", "Defining acceptance criteria", "Specifying acceptance criteria"]
    fact = {"coveredTexts": ["writing acceptance criteria.", "Defining acceptance criteria"]}
    assert cg.link_confirm_texts(fact["coveredTexts"], group) == ["Specifying acceptance criteria"]
    assert cg.link_confirm_texts(None, group) == group


def test_mapping_status_values(tmp_path):
    m = mapper(tmp_path, {"t1": {"competencyId": "acceptance-criteria", "status": "auto"},
                          "t2": {"competencyId": "acceptance-criteria", "status": "pending"},
                          "t3": {"competencyId": "acceptance-criteria", "status": "demoted"}})
    st = lambda t: m.mapping_status({"text": t, "id": "acceptance-criteria"})
    assert (st("t1"), st("t2"), st("t3"), st("t4")) == ("auto", "pending", "demoted", None)


def test_demoted_never_linked_again(tmp_path):
    m = mapper(tmp_path, {"t3": {"competencyId": "acceptance-criteria", "status": "demoted"}})
    assert m.alias_hit("t3") is None
    req = {"text": "t3", "kind": "skill", "importance": "must", "postingQuote": "t3"}
    out = m.resolve(req, "acceptance-criteria", "whole")
    assert out["provisional"] and m.learned["t3"]["status"] == "demoted"
    assert cg.pool_texts([job("t3")], m, {}) == []


def test_cached_not_resent_and_batch_size(tmp_path):
    texts = [f"requirement number {i}" for i in range(151)]
    calls = []
    m = mapper(tmp_path)
    cache = tmp_path / "c.json"
    cg.run([job(*texts)], m, cache, complete=fake([], calls), price=PRICE, confirm=True)
    assert len(calls) == 2 and "150. requirement number 150" not in calls[0] and "0. requirement number 150" in calls[1]
    calls.clear()
    r = cg.run([job(*texts)], m, cache, complete=fake([], calls), price=PRICE, confirm=True)
    assert calls == [] and r["texts"] == 0


def test_cap_stops_before_overspending(tmp_path):
    calls = []
    jobs = [job(*[f"requirement number {i}" for i in range(151)])]
    big = {"in": 1000.0, "out": 1000.0}
    r = cg.run(jobs, mapper(tmp_path), tmp_path / "c.json", complete=fake([], calls), price=big, confirm=True, max_usd=0.10)
    assert calls == [] and r["stopped"] and r["sent"] == 0
    guard = cg.SpendGuard(0.10, PRICE)
    p = "x" * 3000
    one = guard.worst(p, 10)
    guard.reserve(p, 10)
    assert guard.spent == one and not cg.SpendGuard(one * 1.5, PRICE).allows(p * 2, 10)


def test_dry_run_and_no_confirm_send_nothing(tmp_path):
    calls = []
    r = cg.run([job("alpha text")], mapper(tmp_path), tmp_path / "c.json", complete=fake([], calls), price=PRICE)
    assert calls == [] and r["texts"] == 1 and r["sent"] == 0 and not (tmp_path / "c.json").exists()


def test_closed_and_not_found_ads_excluded(tmp_path):
    jobs = [job("closed one", isClosed=True), job("missing one", notFoundThisRun=True), job("open one")]
    assert [i["text"] for i in cg.pool_texts(jobs, mapper(tmp_path), {})] == ["open one"]


def test_prompt_has_ad_text_and_list_only(tmp_path):
    p = cg.build_prompt(COMPS, ["Defining acceptance criteria"])
    assert "Defining acceptance criteria" in p and "acceptance-criteria" in p
    for word in ("candidate's", "resume", "CV", "email", "salary"):
        assert word.lower() not in p.lower().replace("nothing here is about any person", "")


def test_cache_file_mode_600(tmp_path):
    go(tmp_path, [job("alpha text")], [("same_as: acceptance-criteria", "high")])
    for name in ("cache/g.json", "aliases.json"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


def test_the_schema_is_in_the_providers_strict_form():
    assert cg.SCHEMA["strict"] is True and cg.SCHEMA["name"] and cg.SCHEMA["schema"]["additionalProperties"] is False
