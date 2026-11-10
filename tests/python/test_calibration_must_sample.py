"""The must-have precision sampler on fictional engine results. No real data."""

import json
import stat
from collections import Counter

from calibration import must_sample as ms

KINDS = ("certification", "education", "domain", "language", "other", "experience", "skill")


def req(n, kind, importance="must", status="PARTIAL"):
    return {"id": f"r{n}", "text": f"Requirement {n}", "kind": kind, "importance": importance, "postingQuote": f"quote {n}",
            "status": status, "strength": 2, "evidenceQuote": "evidence"}


def fixture(ads=24):
    """24 ads: half production_like, half diagnostic; owner labels cycle yes/no/partial; each ad holds one must per kind."""
    engine, labels, titles, n = {}, {}, {}, 0
    for a in range(ads):
        reqs = []
        for kind in KINDS:
            n += 1
            reqs.append(req(n, kind, status=("MISSING", "MET", "PARTIAL")[n % 3]))
        n += 1
        reqs.append(req(n, "skill", importance="nice"))
        engine[f"ad{a}"] = {"mode": ms.MODES[a % 2], "output": {"requirements": reqs}}
        labels[f"ad{a}"] = {"hardRequirements": ("yes", "no", "partial")[a % 3]}
        titles[f"ad{a}"] = {"title": f"Title {a}", "company": f"Firm {a}"}
    return engine, labels, titles


def test_quotas_modes_probes_and_the_per_ad_cap_hold():
    sample = ms.draw(*fixture())
    counts = ms.counts(sample)
    assert counts["mustItems"] == 60 and counts["probeItems"] == 10
    assert counts["mustByKind"] == ms.QUOTAS
    assert counts["mustByMode"] == {"production_like": 30, "diagnostic": 30}
    assert counts["probeByMode"] == {"production_like": 5, "diagnostic": 5}
    assert counts["maxItemsFromOneAd"] <= ms.MAX_PER_AD


def test_the_same_seed_draws_the_same_items_and_another_seed_draws_others():
    a, b, c = ms.draw(*fixture(), seed=1), ms.draw(*fixture(), seed=1), ms.draw(*fixture(), seed=2)
    ids = lambda s: [(i["jobId"], i["reqId"]) for i in s["items"]]
    assert ids(a) == ids(b) and ids(a) != ids(c)


def test_disagreements_come_before_controls_before_the_rest_inside_a_kind():
    sample = ms.draw(*fixture())
    musts = [i for i in sample["items"] if not i["probe"] and i["kind"] == "skill"]
    # every disagreeing skill item in the pool is taken before any neutral one, as far as the quota reaches
    pool_disagree = sum(s["pool"] for s in sample["strata"] if s["kind"] == "skill" and s["class"] == "disagree")
    took_disagree = sum(1 for i in musts if i["class"] == "disagree")
    assert took_disagree == min(pool_disagree, len(musts))


def test_classification_uses_only_yes_and_no_ads():
    assert ms.classify("yes", "MISSING") == "disagree" and ms.classify("yes", "PARTIAL") == "disagree"
    assert ms.classify("no", "MET") == "disagree"
    assert ms.classify("yes", "MET") == "control" and ms.classify("no", "MISSING") == "control"
    assert ms.classify("partial", "MET") == "neutral" and ms.classify("no", "UNKNOWN") == "neutral"


def test_a_probe_looks_like_any_other_item_and_the_display_order_is_mixed():
    sample = ms.draw(*fixture())
    assert all({"itemId", "kind", "text", "postingQuote", "title", "company"} <= set(i) for i in sample["items"])
    assert [i["itemId"] for i in sample["items"]] == [f"i{n:02d}" for n in range(1, 71)]
    flags = [i["probe"] for i in sample["items"]]
    assert flags != sorted(flags)  # probes are not bunched at the end
    assert all(i["importance"] != "must" for i in sample["items"] if i["probe"])


def test_every_stratum_records_its_pool_and_sample_size_for_weighting():
    sample = ms.draw(*fixture())
    assert sum(s["sampled"] for s in sample["strata"]) == 60
    assert all(s["sampled"] <= s["pool"] for s in sample["strata"])
    assert sum(s["pool"] for s in sample["strata"]) == sample["mustPool"]


def test_a_kind_with_too_few_items_is_made_up_from_the_big_kinds_not_left_short():
    engine, labels, titles = fixture()
    for entry in engine.values():
        entry["output"]["requirements"] = [r for r in entry["output"]["requirements"] if r["kind"] != "education"]
    counts = ms.counts(ms.draw(engine, labels, titles))
    assert counts["mustItems"] == 60 and "education" not in counts["mustByKind"]


def test_main_writes_the_sample_with_mode_600_and_prints_counts_only(tmp_path, capsys):
    engine, labels, titles = fixture()
    (tmp_path / "engine-shadow.json").write_text(json.dumps({"ads": engine}))
    (tmp_path / "ran-labels.json").write_text(json.dumps({"labels": labels}))
    (tmp_path / "review-items.json").write_text(json.dumps({"items": [{"jobId": j, **t} for j, t in titles.items()]}))
    assert ms.main(["--out", str(tmp_path)]) == 0
    assert stat.S_IMODE((tmp_path / ms.SAMPLE_NAME).stat().st_mode) == 0o600
    printed = capsys.readouterr().out
    assert "Requirement" not in printed and "Title" not in printed
    assert json.loads(printed)["mustItems"] == 60
