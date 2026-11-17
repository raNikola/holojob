"""holdout-v2 selection, the unit keys kept by the variance script, and the requirement-stability tool.

Synthetic data only: every file lives in tmp_path; nothing reads or writes /srv/holojob/data; no provider is called.
"""

import json
import stat
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure_extraction_variance as mv  # noqa: E402
import measure_requirement_stability as ms  # noqa: E402
import select_holdout_v2 as sel  # noqa: E402


# --- selection --------------------------------------------------------------------------------------------------------

def make_rows(n_product=30, n_delivery=20, n_other=10):
    rows = []
    titles = ([("Senior Product Manager", n_product), ("Technical Program Manager", n_delivery), ("Software Engineer", n_other)])
    n = 0
    for title, count in titles:
        for _ in range(count):
            n += 1
            rows.append({"jobId": f"{n:016x}", "title": title, "company": "Acme", "jobUrl": f"https://jobs.example/{n}",
                         "description": "Body. " * 20})
    return rows


def write_inputs(tmp_path, rows, labelled=(), v1=(), ex1=()):
    data = tmp_path / "data"
    (data / "jobs").mkdir(parents=True)
    (data / "calibration" / "stage-a").mkdir(parents=True)
    (data / "jobs" / "discovered_jobs.json").write_text(json.dumps({"jobs": rows}))
    (data / "calibration" / "stage-a" / "eval-set.json").write_text(json.dumps({"ads": {i: {} for i in labelled}}))
    (tmp_path / "v1.json").write_text(json.dumps({"ids": list(v1)}))
    (tmp_path / "ex1.json").write_text(json.dumps({"ids": list(ex1)}))
    return data


def run(tmp_path, data, seed=7):
    out, sheet = tmp_path / "sel.json", tmp_path / "sheet.md"
    code = sel.main(["--data-dir", str(data), "--seed", str(seed), "--selection", str(out), "--sheet", str(sheet),
                     "--holdout-v1", str(tmp_path / "v1.json"), "--extract-selection", str(tmp_path / "ex1.json")])
    return code, out, sheet


def test_title_classes_are_first_match_wins_on_the_public_title():
    assert sel.title_class("Senior Product Manager") == "product"
    assert sel.title_class("Product Program Manager") == "product"
    assert sel.title_class("Technical Project Manager") == "program_project_delivery"
    assert sel.title_class("Head of Delivery") == "program_project_delivery"
    assert sel.title_class("Software Engineer") == "other"
    assert sel.title_class(None) == "other"


def test_selection_has_the_quota_per_stratum_and_is_reproducible(tmp_path):
    rows = make_rows()
    data = write_inputs(tmp_path, rows)
    code, out, sheet = run(tmp_path, data)
    assert code == 0
    first = json.loads(out.read_text())
    assert first["countsPerStratum"] == {"product": 7, "program_project_delivery": 7, "other": 6}
    assert len(set(first["ids"])) == 20
    code, out2, _ = run(tmp_path, data)
    assert json.loads(out2.read_text())["ids"] == first["ids"]
    code, out3, _ = run(tmp_path, data, seed=8)
    assert json.loads(out3.read_text())["ids"] != first["ids"]
    for path in (out, sheet):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_exclusions_closed_manual_and_empty_description_are_never_drawn(tmp_path):
    rows = make_rows()
    labelled = [r["jobId"] for r in rows[:5]]
    v1 = [r["jobId"] for r in rows[5:10]]
    ex1 = [r["jobId"] for r in rows[10:15]]
    rows[15]["isClosed"] = True
    rows[16]["manualEntry"] = True
    rows[17]["description"] = "   "
    rows[18]["description"] = None
    barred = set(labelled) | set(v1) | set(ex1) | {rows[i]["jobId"] for i in (15, 16, 17, 18)}
    data = write_inputs(tmp_path, rows, labelled, v1, ex1)
    for seed in range(1, 15):
        code, out, _ = run(tmp_path, data, seed)
        assert code == 0
        assert not barred & set(json.loads(out.read_text())["ids"])
    why = json.loads(out.read_text())["pool"]["leftOut"]
    assert why == {"closed_or_manual": 2, "excluded_id": 15, "empty_description": 2}


def test_a_short_stratum_stops_and_writes_nothing(tmp_path, capsys):
    data = write_inputs(tmp_path, make_rows(n_other=5))
    code, out, sheet = run(tmp_path, data)
    assert code == 1
    assert not out.exists() and not sheet.exists()
    assert "other" in capsys.readouterr().err


def test_the_draw_does_not_depend_on_score_rank_cap_or_band(tmp_path):
    rows = make_rows()
    data = write_inputs(tmp_path, rows)
    _, out, _ = run(tmp_path, data)
    plain = json.loads(out.read_text())["ids"]
    for i, r in enumerate(rows):
        r.update({"matchScore": (i * 37) % 100, "matchLabel": "Strong", "scoreBeforeCaps": 99 - i, "llmFacts": {"roleTrack": "x"}})
    (data / "jobs" / "discovered_jobs.json").write_text(json.dumps({"jobs": rows}))
    _, out, _ = run(tmp_path, data)
    assert json.loads(out.read_text())["ids"] == plain


def test_the_sheet_is_blind_shuffled_and_has_the_empty_columns(tmp_path):
    rows = make_rows()
    for r in rows:
        r.update({"matchScore": 61, "matchLabel": "Strong", "scoreBeforeCaps": 70, "group": "g"})
    data = write_inputs(tmp_path, rows)
    _, out, sheet = run(tmp_path, data)
    ids = json.loads(out.read_text())["ids"]
    text = sheet.read_text()
    for word in ("matchScore", "Strong", "scoreBeforeCaps", "61", "group", "cap"):
        assert word not in text.replace("Success criterion", "")
    for i in ids:
        assert i in text
    for column in ("fit verdict", "rank 1-20", "eligibility", "cannot tell without reading", "one-line reason", "## Success criterion"):
        assert column in text
    order = [line.split("|")[2].strip() for line in text.splitlines() if line.startswith("| ") and line.split("|")[1].strip().isdigit()]
    assert sorted(order) == sorted(ids) and order != ids


def test_the_ids_hash_is_recorded(tmp_path):
    import hashlib
    data = write_inputs(tmp_path, make_rows())
    _, out, _ = run(tmp_path, data)
    doc = json.loads(out.read_text())
    assert doc["idsSha256"] == hashlib.sha256(json.dumps(doc["ids"]).encode()).hexdigest()
    assert doc["seed"] == 7 and "Pool:" in doc["rule"] and "sha256" in doc["rule"]


# --- unit keys ---------------------------------------------------------------------------------------------------------

def req(quote, importance="must", kind="skill", id_=None, provisional=True):
    return {"text": "paraphrase", "postingQuote": quote, "importance": importance, "kind": kind,
            "id": id_ or "prov-x", "provisional": provisional}


def test_unit_keys_are_text_free_and_stable_across_case_and_punctuation():
    a = mv.unit_keys({"requirements": [req("Own the Roadmap, end-to-end!")]})
    b = mv.unit_keys({"requirements": [req("own the roadmap end to end")]})
    assert a[0]["key"] == b[0]["key"] and a[0]["key"].startswith("q:") and len(a[0]["key"]) == 14
    assert "roadmap" not in json.dumps(a).lower()


def test_unit_keys_use_the_canonical_competency_id_and_merge_duplicates_at_the_highest_importance():
    facts = {"requirements": [req("quote one", "preferred", id_="agile", provisional=False),
                              req("quote two", "must", id_="agile", provisional=False),
                              req("", "must"), req("sql", "nice")]}
    units = mv.unit_keys(facts)
    by_key = {u["key"]: u for u in units}
    assert by_key["c:agile"]["importance"] == "must" and by_key["c:agile"]["canonical"] is True
    assert len(units) == 2  # the quote-less requirement is skipped


def test_variance_out_file_keeps_the_unit_keys():
    runs = {"a": [{"requirements": [req("x y")]}, {"requirements": [req("x y")]}], "b": []}
    keys = mv.unit_keys_by_ad(runs)
    assert list(keys) == ["a"] and len(keys["a"]) == 2


# --- stability -----------------------------------------------------------------------------------------------------------

def unit(key, importance="must", kind="skill", canonical=False):
    return {"key": key, "canonical": canonical, "kind": kind, "importance": importance}


def test_jaccard_basics():
    assert ms.jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert ms.jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert ms.jaccard({"a"}, {"b"}) == 0.0
    assert ms.jaccard(set(), set()) is None


def test_ad_overlap_means_over_pairs_and_needs_two_passes():
    passes = [[unit("a"), unit("b")], [unit("a"), unit("b")], [unit("a"), unit("c")]]
    res = ms.ad_overlap(passes)
    assert res["pairs"] == [1.0, pytest.approx(1 / 3), pytest.approx(1 / 3)]
    assert res["mean"] == pytest.approx((1 + 1 / 3 + 1 / 3) / 3)
    assert ms.ad_overlap([[unit("a")]]) is None


def test_specific_must_filter():
    assert ms.is_specific_must(unit("a", "must", "skill"))
    assert ms.is_specific_must(unit("a", "must", "other", canonical=True))
    assert not ms.is_specific_must(unit("a", "must", "experience"))
    assert not ms.is_specific_must(unit("a", "preferred", "skill"))
    assert not ms.is_specific_must(unit("a", "must", "other"))


def test_stability_report_on_synthetic_ads():
    data = {
        "same": [[unit("a"), unit("b")], [unit("a"), unit("b")]],
        "half": [[unit("a"), unit("b")], [unit("b"), unit("c")], [unit("b"), unit("c")]],
        # all units differ, but the only specific must unit (s) is stable: the two classes must disagree
        "generic-churn": [[unit("s"), unit("g1", "preferred")], [unit("s"), unit("g2", "preferred")]],
        "no-must": [[unit("p", "preferred")], [unit("q", "preferred")]],
        "once": [[unit("a")]],
    }
    rep = ms.stability(data)
    assert rep["adsWithTooFewPasses"] == ["once"]
    allc, spec = rep["classes"]["allUnits"], rep["classes"]["specificMustUnits"]
    assert allc["ads"] == 4 and allc["adsAtOne"] == 1
    assert allc["perAdMean"]["generic-churn"] == pytest.approx(0.333, abs=1e-3)
    assert allc["perAdMean"]["half"] == pytest.approx((1 / 3 + 1 / 3 + 1.0) / 3, abs=1e-3)
    assert sum(allc["buckets"].values()) == 4
    assert spec["ads"] == 3 and spec["adsUndefined"] == 1 and spec["undefinedIds"] == ["no-must"]
    assert spec["perAdMean"]["generic-churn"] == 1.0
    assert spec["adsAtOne"] == 2
    assert spec["lowestIds"][0] == "half"


def test_load_rejects_a_file_without_unit_keys_and_a_wrong_version(tmp_path):
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"meta": {}, "report": {}}))
    with pytest.raises(ValueError, match="no unitKeys"):
        ms.load(old)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"unitKeysVersion": 99, "unitKeys": {"a": [[], []]}}))
    with pytest.raises(ValueError, match="unitKeysVersion"):
        ms.load(bad)


def test_matcher_prepare_reads_facts_from_the_scratch_ledger(tmp_path):
    import measure_holdout_matcher as hm
    scratch = tmp_path / "scratch"
    (scratch / "jobs").mkdir(parents=True)
    (scratch / "jobs" / "discovered_jobs.json").write_text(json.dumps({"generation": 1, "jobs": []}))
    job = lambda i: {"jobId": i, "title": "Technical Program Manager", "company": "Acme", "description": "Run delivery. " * 10}  # noqa: E731
    reqs = [{"id": "agile", "text": "t", "kind": "skill", "importance": "must", "postingQuote": "q"}]
    ledger = {"generation": 1, "jobs": {
        "a": {"job": job("a"), "llmFacts": {"requirements": reqs}},
        "b": {"job": job("b"), "llmFacts": {"requirements": []}},
        "c": {"job": job("c")},
    }}
    (scratch / "jobs" / "job_history.json").write_text(json.dumps(ledger))
    items, facts, counts = hm.facts_from_scratch(scratch, ["a", "b", "c", "missing"])
    assert [i["jobId"] for i in items] == ["a"] and list(facts) == ["a"] and "llmFacts" not in items[0]
    assert counts == {"ids": 4, "found": 3, "noFacts": 1, "noRequirements": 1, "prepared": 1}


def test_matcher_wrapper_refuses_a_scratch_dir_inside_the_real_data_dir(tmp_path, capsys):
    import measure_holdout_matcher as hm
    real = tmp_path / "data"
    (real / "scratch").mkdir(parents=True)
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({"ids": []}))
    code = hm.main(["--ids", str(ids), "--scratch", str(real / "scratch"), "--data-dir", str(real), "--max-usd", "0.1"])
    assert code == 2 and "refused" in capsys.readouterr().err
    assert hm.main(["--ids", str(ids), "--scratch", str(tmp_path / "s"), "--data-dir", str(real), "--max-usd", "0"]) == 2


def test_main_prints_a_report_without_writing(tmp_path, capsys):
    f = tmp_path / "v.json"
    f.write_text(json.dumps({"unitKeysVersion": 1, "unitKeys": {"a": [[unit("x")], [unit("x")]], "b": [[unit("x")], [unit("y")]]}}))
    before = sorted(p.name for p in tmp_path.iterdir())
    assert ms.main([str(f)]) == 0
    out = capsys.readouterr().out
    assert "allUnits" in out and "specificMustUnits" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert ms.main([str(tmp_path / "missing.json")]) == 2
