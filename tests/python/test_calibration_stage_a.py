"""P1 Stage A tooling on fictional ads, in a temp directory. Nothing here reads or writes the real data/."""

import json
import stat

import pytest

from calibration import stage_a as sa


def row(job_id, title="Product Manager", company="Acme", score=70, label="Strong", reasons=None, raw=None, **extra):
    dims = {d: {"raw": (raw or {}).get(d, 60), "weight": 10, "weighted": 6} for d in sa.DIMENSIONS}
    return {"jobId": job_id, "title": title, "company": company, "matchScore": score, "matchLabel": label,
            "priority": "P2", "reasons": reasons or [], "scoreBreakdown": dims, "description": "the work and the team",
            "provider": "greenhouse", "location": "Remote", "site": "greenhouse", "jobUrl": "https://example.test/1", **extra}


def test_cap_type_reads_the_scorer_reason_lines():
    assert sa.cap_type(row("a", reasons=["Capped: the title matches no target role"])) == "title"
    assert sa.cap_type(row("a", reasons=["Capped: the ad describes delivery work, not a product role"])) == "track"
    assert sa.cap_type(row("a", reasons=["Capped: visa"])) == "authorization"
    assert sa.cap_type(row("a", reasons=["Capped: the ad requires Russian, which your profile does not list"])) == "language"
    assert sa.cap_type(row("a", reasons=["Red flag: x"])) == "red_flag"
    assert sa.cap_type(row("a")) == "none"












def test_review_items_show_no_score_field_and_the_holdout_excludes_the_sample(tmp_path):
    rows = [row(f"j{i}", company=f"Firm{i}", reasons=["Capped: the title matches no target role"],
                score=40, label="Weak") for i in range(10)] + [row("case", title="Account Executive", company="MPG Plus")]
    (tmp_path / "rescored").mkdir()
    (tmp_path / "rescored" / "scored_jobs.json").write_text(json.dumps({"jobs": rows}))
    summary = sa.sample(tmp_path, size=6, seed=3)
    for name in ("review-items.json", "sample.json"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600
    items = json.loads((tmp_path / "review-items.json").read_text())["items"]
    assert len(items) == summary["size"] == 6 and {tuple(i) for i in items} == {sa.REVIEW_FIELDS}
    text = (tmp_path / "review-items.json").read_text()
    assert "matchScore" not in text and "Capped" not in text and "scoreBreakdown" not in text
    sample = json.loads((tmp_path / "sample.json").read_text())
    assert sorted(sample["jobIds"]) == sorted(sample["drawOrder"]) == sample["holdoutExclusions"]["jobIds"]
    assert len(sample["holdoutExclusions"]["matchKeys"]) == 6


def test_freeze_copies_inputs_once_and_never_touches_the_source(tmp_path):
    data = tmp_path / "data"
    (data / "jobs").mkdir(parents=True)
    (data / "intelligence").mkdir()
    for name in ("discovered_jobs.json", "job_history.json", "manual_jobs.json"):
        (data / "jobs" / name).write_text(json.dumps({"jobs": []}))
    (data / "jobs" / "scored_jobs.json").write_text(json.dumps({"meta": {"generatedAt": "2026-01-01T00:00:00+00:00",
                                                                        "jobCount": 0}, "jobs": []}))
    (data / "intelligence" / sa.INTELLIGENCE).write_text(json.dumps({"meta": {"generatedAt": "2025-12-31"}}))
    before = {p.name: p.read_bytes() for p in (data / "jobs").iterdir()}
    out = tmp_path / "out"
    m = sa.freeze(out, data, lock=tmp_path / "lock")
    assert all(f["sha256"] == f["copySha256"] for f in m["files"].values())
    assert m["missingOptionalInputs"] == ["rescored_kept.json"]
    assert stat.S_IMODE((out / "baseline" / "scored_jobs.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((out / "baseline").stat().st_mode) == 0o700
    assert {p.name: p.read_bytes() for p in (data / "jobs").iterdir()} == before
    with pytest.raises(SystemExit):
        sa.freeze(out, data, lock=tmp_path / "lock")


