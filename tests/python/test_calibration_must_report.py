"""The step 8 report on fictional samples and answers in a temp folder."""

import json

from calibration import must_report as mr


def item(n, kind="skill", mode="production_like", cls="neutral", status="MET", probe=False):
    return {"itemId": f"i{n:02d}", "jobId": f"ad{n}", "reqId": f"r{n}", "kind": kind, "mode": mode, "class": cls, "probe": probe,
            "importance": "nice" if probe else "must", "text": f"Requirement {n}", "verdict": {"status": status, "strength": 2, "evidenceQuote": "x"}}


def answer(is_must, meets, changed=False, final=None):
    first = {"isMust": is_must, "meets": meets, "savedAt": "t"}
    return {"first": first, "final": final or first, "changedAfterReveal": changed}


def folder(tmp_path, items, answers, strata=None):
    strata = strata if strata is not None else [
        {"kind": k, "mode": m, "class": c, "pool": pool, "sampled": sum(1 for i in items if (i["kind"], i["mode"], i["class"]) == (k, m, c) and not i["probe"])}
        for k, m, c, pool in {(i["kind"], i["mode"], i["class"], 10) for i in items if not i["probe"]}]
    (tmp_path / "must-sample.json").write_text(json.dumps({"version": 1, "items": items, "strata": strata}))
    (tmp_path / "ran-must-labels.json").write_text(json.dumps({"version": 1, "labels": {f"i{n:02d}": a for n, a in answers.items()}}))
    return tmp_path


def test_precision_is_counted_per_mode_and_never_pooled(tmp_path):
    items = [item(1), item(2), item(3, mode="diagnostic"), item(4, mode="diagnostic")]
    out = folder(tmp_path, items, {1: answer("yes", "yes"), 2: answer("nice", "yes"), 3: answer("no", "no"), 4: answer("no", "no")})
    report = mr.build(out)
    prod, diag = report["modes"]["production_like"], report["modes"]["diagnostic"]
    assert (prod["precision"]["really_must"], prod["precision"]["answered"], prod["precision"]["precision"]) == (1, 2, 0.5)
    assert (diag["precision"]["not_a_requirement"], diag["precision"]["precision"]) == (2, 0.0)
    assert "pooled" not in json.dumps(report).lower().replace("never pooled", "")


def test_the_blind_first_answer_is_used_and_a_change_after_the_reveal_is_only_counted(tmp_path):
    items = [item(1), item(2)]
    changed = answer("no", "no", changed=True, final={"isMust": "yes", "meets": "yes", "savedAt": "t2"})
    report = mr.build(folder(tmp_path, items, {1: changed, 2: answer("yes", "yes")}))
    assert report["changedAfterReveal"] == 1
    assert report["modes"]["production_like"]["precision"]["really_must"] == 1  # item 1 counts as the first answer, "no"


def test_weighting_gives_each_stratum_its_pool_not_its_sample_share(tmp_path):
    items = [item(1, cls="disagree"), item(2, cls="neutral"), item(3, cls="neutral")]
    strata = [{"kind": "skill", "mode": "production_like", "class": "disagree", "pool": 10, "sampled": 1},
              {"kind": "skill", "mode": "production_like", "class": "neutral", "pool": 90, "sampled": 2}]
    out = folder(tmp_path, items, {1: answer("no", "no"), 2: answer("yes", "yes"), 3: answer("yes", "yes")}, strata)
    p = mr.build(out)["modes"]["production_like"]["precision"]
    assert p["precision"] == 0.67  # raw: 2 of 3
    assert p["weighted"]["precision"] == 0.9 and p["weighted"]["coveredPoolShare"] == 1.0  # 0.1*0 + 0.9*1


def test_verdict_agreement_is_counted_on_real_musts_only_with_the_costly_misses_named(tmp_path):
    items = [item(1, status="MET"), item(2, status="MISSING"), item(3, status="MET"), item(4, status="PARTIAL"), item(5, status="MET")]
    answers = {1: answer("yes", "yes"), 2: answer("yes", "yes"), 3: answer("yes", "no"), 4: answer("yes", "partial"), 5: answer("nice", "no")}
    a = mr.build(folder(tmp_path, items, answers))["modes"]["production_like"]["verdictAgreement"]
    assert a["items"] == 4 and a["exact"] == 2  # items 1 and 4; item 5 is not a real must
    assert (a["engineMissingButOwnerMeetsIt"], a["engineMetButOwnerDoesNot"]) == (1, 1)


def test_the_bar_needs_both_the_precision_and_enough_answers(tmp_path):
    many = [item(n, kind="domain") for n in range(1, 9)] + [item(n, kind="education") for n in range(9, 12)]
    answers = {n: answer("yes", "yes") for n in range(1, 12)}
    m = mr.build(folder(tmp_path, many, answers))["modes"]["production_like"]
    assert m["trust"]["domain"] == "trusted at the bar"
    assert m["trust"]["education"].startswith("undecided")  # only 3 answered
    assert m["gateKinds"]["meetsBar"] is True


def test_probe_items_are_reported_apart_from_the_must_precision(tmp_path):
    items = [item(1), item(2, probe=True), item(3, probe=True)]
    m = mr.build(folder(tmp_path, items, {1: answer("yes", "yes"), 2: answer("yes", "no"), 3: answer("nice", "no")}))["modes"]["production_like"]
    assert m["probe"] == {"sampled": 2, "answered": 2, "calledRealMust": 1, "calledNice": 1, "calledNotRequirement": 0}
    assert m["precision"]["answered"] == 1


def test_unanswered_items_are_counted_not_guessed_and_nothing_is_written_or_printed(tmp_path, capsys):
    out = folder(tmp_path, [item(1), item(2)], {1: answer("yes", "yes")})
    before = sorted(p.name for p in tmp_path.iterdir())
    assert mr.main(["--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "1 of 2 sampled items answered" in printed and "Requirement" not in printed
    assert sorted(p.name for p in tmp_path.iterdir()) == before
