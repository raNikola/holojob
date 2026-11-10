"""P1 Stage A tooling on fictional ads, in a temp directory. Nothing here reads or writes the real data/."""

import csv
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
    assert sa.cap_type(row("a", reasons=["Red flag: x"])) == "red_flag"
    assert sa.cap_type(row("a")) == "none"


def test_language_label_by_function_word_share():
    assert sa.language_of("we will work with the team and our experience") == "en"
    assert sa.language_of("rad na poslu i iskustvo u znanje za posla") == "sr"


def test_diff_separates_unchanged_changed_and_missing_jobs():
    before = [row("1"), row("2", score=40, label="Weak"), row("3")]
    after = [row("1"), row("2", score=45, label="Weak", raw={"skillMatch": 70}), row("4")]
    d = sa.diff_scores(before, after)
    assert (d["common"], d["unchanged"], len(d["changed"])) == (2, 1, 1)
    assert d["onlyBefore"] == ["3"] and d["onlyAfter"] == ["4"]
    assert d["changed"][0]["dimensions"] == {"skillMatch": [60, 70]}
    assert d["scoreDeltas"] == {5: 1} and d["labelChanges"] == 0


def test_cases_resolve_by_company_and_title_and_missing_ones_are_reported():
    rows = [row("c1", title="Account Executive", company="MPG Plus d.o.o."), row("x", company="Other")]
    found, missing = sa.resolve_cases(rows)
    assert found == {"mpg-account-executive": "c1"}
    assert "raiffeisen-product-manager" in missing and len(missing) == len(sa.CASES) - 1


def test_sample_is_seeded_keeps_cases_and_skips_closed_ads():
    rows = [row(f"j{i}", company=f"Firm{i}", label="Weak" if i % 3 else "Strong", provider="infostud" if i % 4 else "ashby",
                reasons=["Capped: the title matches no target role"] if i % 2 else [], isClosed=(i == 5)) for i in range(40)]
    rows.append(row("case", title="Account Executive", company="MPG Plus"))
    cases, _ = sa.resolve_cases(rows)
    a = sa.draw_sample(rows, 12, 7, cases)
    b = sa.draw_sample(rows, 12, 7, cases)
    assert [r["jobId"] for r in a] == [r["jobId"] for r in b]
    ids = [r["jobId"] for r in a]
    assert len(ids) == len(set(ids)) == 12 and "case" in ids and "j5" not in ids
    assert {r["matchLabel"] for r in a} == {"Weak", "Strong"} and {sa.cap_type(r) for r in a} == {"none", "title"}


def test_sheet_is_blind_private_and_prefilled_only_for_cases(tmp_path):
    rows = [row(f"j{i}", company=f"Firm{i}") for i in range(10)] + [row("case", title="Account Executive", company="MPG Plus")]
    (tmp_path / "rescored").mkdir()
    (tmp_path / "rescored" / "scored_jobs.json").write_text(json.dumps({"jobs": rows}))
    summary = sa.sample(tmp_path, size=6, seed=3)
    sheet = tmp_path / "labeling-sheet.csv"
    assert stat.S_IMODE(sheet.stat().st_mode) == 0o600 and stat.S_IMODE((tmp_path / "sample.json").stat().st_mode) == 0o600
    with open(sheet, newline="", encoding="utf-8") as handle:
        table = list(csv.DictReader(handle))
    assert list(table[0]) == sa.SHEET_COLUMNS and len(table) == summary["size"] == 6
    assert not {"matchScore", "matchLabel", "score"} & set(table[0])
    pre = [t for t in table if t["prefilled"]]
    assert [t["jobId"] for t in pre] == ["case"] and pre[0]["function"] == "no" and pre[0]["overall"] == "0"


def test_load_labels_validates_each_judgment(tmp_path):
    path = tmp_path / "labels.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=sa.SHEET_COLUMNS)
        w.writeheader()
        w.writerow({"jobId": "ok", "function": "yes", "hard_requirements": "unknown", "overall": "2", "main_reason": "skills"})
        w.writerow({"jobId": "bad", "function": "maybe", "hard_requirements": "no", "overall": "5", "main_reason": ""})
        w.writerow({"jobId": "empty", "function": "no", "hard_requirements": "", "overall": "0"})
    rows, problems = sa.load_labels(path)
    assert len(rows) == 3
    assert any("bad: function 'maybe'" in p for p in problems) and any("bad: overall '5'" in p for p in problems)
    assert any("empty: hard_requirements is empty" in p for p in problems)
    assert not any(p.startswith("ok:") for p in problems)


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


def test_diff_reading_says_when_the_rescore_reproduces_the_baseline(tmp_path):
    rows = {"jobs": [row("1"), row("2")]}
    for folder in ("baseline", "rescored"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "scored_jobs.json").write_text(json.dumps(rows))
    (tmp_path / "manifest.json").write_text(json.dumps({"git": {"scoringCodeChangedSinceBaseline": ["python/job_scoring/x.py"]}}))
    result = sa.diff(tmp_path)
    assert result["changed"] == [] and "reproduces the baseline" in result["attribution"]["reading"]
    assert stat.S_IMODE((tmp_path / "diff.json").stat().st_mode) == 0o600
