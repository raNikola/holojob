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
