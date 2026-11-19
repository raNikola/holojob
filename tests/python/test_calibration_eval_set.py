"""The frozen test set on fictional labels in a temp folder. No real data."""

import json
import stat

import pytest

from calibration import eval_set as es


def labels(n=12):
    return {f"ad{i}": {"jobId": f"ad{i}", "overall": i % 4, "functionFit": "yes", "hardRequirements": "partial"} for i in range(n)}


def sample(ad_ids):
    items, k = [], 0
    for ad in ad_ids:
        for _ in range(2):
            k += 1
            items.append({"itemId": f"i{k:02d}", "jobId": ad, "kind": "skill", "mode": "production_like", "probe": k % 5 == 0,
                          "importance": "must", "text": "SECRET REQUIREMENT TEXT"})
    return items


def line_labels(items):
    return {i["itemId"]: {"first": {"isMust": "yes", "meets": "partial"}, "final": {"isMust": "yes", "meets": "partial"}} for i in items}


def folder(tmp_path, n=12):
    ad_labels = labels(n)
    items = sample(list(ad_labels))
    (tmp_path / "ran-labels.json").write_text(json.dumps({"labels": ad_labels}))
    (tmp_path / "ran-must-labels.json").write_text(json.dumps({"labels": line_labels(items)}))
    (tmp_path / "must-sample.json").write_text(json.dumps({"items": items}))
    return tmp_path








def test_the_freeze_holds_ids_kinds_and_answers_but_no_text_and_has_mode_600(tmp_path):
    out = folder(tmp_path)
    es.freeze(out)
    raw = (out / es.EVAL_NAME).read_text()
    assert "SECRET REQUIREMENT TEXT" not in raw and "caveat" in raw
    assert stat.S_IMODE((out / es.EVAL_NAME).stat().st_mode) == 0o600
    assert set(es.load(out)["lines"]["i01"]) == {"jobId", "kind", "mode", "probe", "modelImportance", "first", "split"}


def test_a_frozen_set_is_not_overwritten_without_force(tmp_path):
    out = folder(tmp_path)
    es.freeze(out)
    with pytest.raises(SystemExit, match="frozen"):
        es.freeze(out)
    es.freeze(out, seed=99, force=True)
    assert es.load(out)["seed"] == 99






def test_main_prints_counts_only(tmp_path, capsys):
    out = folder(tmp_path)
    assert es.main(["freeze", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "SECRET" not in printed and json.loads(printed)["ads"] == 12
