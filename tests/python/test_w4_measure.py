"""W4 owner-run tools: extract-7 holdout read (estimate-first), role-mix report, matcher over responsibilities, the d: stability class. Temp dirs only, no provider."""

import json
import stat
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure_holdout_extract7 as e7  # noqa: E402
import measure_holdout_matcher as hm  # noqa: E402
import measure_requirement_stability as ms  # noqa: E402
import measure_role_mix as rmx  # noqa: E402
from test_holdout_measure import PRICED, data_dir, ids_file, snapshot  # noqa: E402,F401


# --- extract-7 ------------------------------------------------------------------------------------------------------

def test_extract7_without_confirm_writes_nothing_and_calls_nothing(data_dir, ids_file, tmp_path, monkeypatch, capsys):
    scratch = tmp_path / "scratch"
    seen = {}
    monkeypatch.setattr(e7.mv, "estimate", lambda *a, **k: seen.update(resp=a[-1]) or PRICED)
    monkeypatch.setattr(e7.mv, "run_extractions", lambda *a, **k: pytest.fail("a provider call was made"))
    before = snapshot(data_dir)
    assert e7.main(["--ids", str(ids_file), "--scratch", str(scratch), "--data-dir", str(data_dir), "--max-usd", "0.15"]) == 0
    assert seen["resp"] is True  # priced as prompt 7
    assert not scratch.exists() and snapshot(data_dir) == before
    assert "Nothing was called" in capsys.readouterr().out


def test_extract7_refuses_an_unknown_price_and_a_worst_case_above_the_cap(data_dir, ids_file, tmp_path, monkeypatch):
    monkeypatch.setattr(e7.mv, "run_extractions", lambda *a, **k: pytest.fail("called"))
    for est in ({"priceKnown": False}, {**PRICED, "worstCaseUsd": 0.5}):
        monkeypatch.setattr(e7.mv, "estimate", lambda *a, _e=est, **k: _e)
        assert e7.main(["--ids", str(ids_file), "--scratch", str(tmp_path / "s"), "--data-dir", str(data_dir), "--max-usd", "0.15", "--confirm"]) == 1
    assert not (tmp_path / "s").exists()


def test_extract7_scratch_guard():
    with pytest.raises(SystemExit):
        e7.check_scratch(Path("/x/data/sub"), Path("/x/data"))


def test_extract7_record_keeps_text_only_in_the_record_and_skips_failed_ads():
    rec = e7.facts_record({"a": [{"responsibilities": [{"text": "Own it", "postingQuote": "own it", "extra": 1}], "responsibilitiesDropped": 1,
                                  "requirements": [{}, {}]}], "b": []})
    assert rec == {"a": {"responsibilities": [{"text": "Own it", "postingQuote": "own it"}], "responsibilitiesDropped": 1, "requirements": 2}}


def test_extract7_source_never_writes_the_ledger_or_view():
    src = (SCRIPTS / "measure_holdout_extract7.py").read_text(encoding="utf-8")
    assert "store_facts" not in src and "job_history" not in src and "discovered_jobs" not in src


# --- role mix report ------------------------------------------------------------------------------------------------

def mix(fit, available=True, insufficient=False):
    return {"roleFit": fit, "available": available, "insufficient": insufficient}


def test_bar_pass_fail_tie_and_not_evaluable():
    nebius = rmx.BAR_SKIP_IDS[0]
    apply_ids = ["a", "b", "c", "monzo"]
    ok = {"a": mix(80), "b": mix(70), "c": mix(60), "monzo": None, nebius: mix(40)}
    assert rmx.evaluate_bar(ok, apply_ids)["verdict"] == "pass"
    assert rmx.evaluate_bar(ok, apply_ids)["unreadable"] == ["monzo"]
    tie = {**ok, "c": mix(40)}
    assert rmx.evaluate_bar(tie, apply_ids)["verdict"] == "fail"
    assert rmx.evaluate_bar({**ok, nebius: None}, apply_ids)["verdict"] == "not evaluable"
    assert rmx.evaluate_bar({**ok, nebius: mix(None, available=False, insufficient=True)}, apply_ids)["verdict"] == "not evaluable"
    # an APPLY ad with an insufficient role part is unreadable, not a pass
    assert rmx.evaluate_bar({**ok, "a": mix(90, insufficient=True)}, apply_ids)["unreadable"] == ["a", "monzo"]


def test_role_mix_tool_needs_the_owner_read(tmp_path, capsys):
    assert rmx.main(["--scratch", str(tmp_path)]) == 2
    assert "measure_holdout_extract7" in capsys.readouterr().err


def test_role_mix_tool_prints_counts_and_verdicts_not_text(tmp_path, capsys):
    ratings = tmp_path / "r.md"
    ratings.write_text("""| rank | verdict | id | company / title | primary driver | reason |
|---|---|---|---|---|---|
| 1 | apply | aaaaaaaaaaaaaaaa | Acme, TPM | FIT | SECRET REASON |
| 2 | skip | 2fa17cc182518736 | Nebius, Backend | FIT | SECRET REASON TWO |

## Success criterion

APPROVED

1. At least 3 of the 4 APPLY.
2. No SKIP ad with primary driver FIT (Nebius) ranks above any APPLY ad.
3. x
4. y
""")
    (tmp_path / "s" / "extract7").mkdir(parents=True)
    (tmp_path / "s" / "extract7" / "facts.json").write_text(json.dumps({"facts": {
        "aaaaaaaaaaaaaaaa": {"responsibilities": [{"text": "Own the product roadmap SECRET TEXT", "postingQuote": "q"}]},
        "2fa17cc182518736": {"responsibilities": [{"text": "Write code for backend services", "postingQuote": "q"}]}}}))
    assert rmx.main(["--scratch", str(tmp_path / "s"), "--ratings", str(ratings)]) == 0
    out = capsys.readouterr().out
    assert "**PASS**" in out and "SECRET" not in out and "eng.code" in out


# --- matcher over responsibilities ----------------------------------------------------------------------------------

def test_responsibility_rows_for_the_matcher():
    from requirement_ids import provisional_id
    rows = hm.responsibility_requirements([{"text": "Own the roadmap", "postingQuote": "own the roadmap"}, {"text": "Own the roadmap", "postingQuote": "x"},
                                           {"text": "", "postingQuote": "q"}, {"text": "No quote", "postingQuote": None}])
    assert len(rows) == 1
    r = rows[0]
    assert (r["kind"], r["importance"], r["provisional"]) == ("experience", "nice", True) and r["id"] == provisional_id("Own the roadmap")
    # the row maps back to its r: unit key through its quote
    from match_engine.fit21 import quote_key
    assert quote_key(r["postingQuote"], "r").startswith("r:")


def test_responsibilities_mode_never_writes_the_step2_matcher_folder(tmp_path, monkeypatch, capsys):
    real = tmp_path / "data"
    scratch = tmp_path / "scratch"
    for need in ("profile/candidate-profile.json", "intelligence/candidate-intelligence.json", "config/ai-settings.json", "jobs/discovered_jobs.json"):
        (scratch / need).parent.mkdir(parents=True, exist_ok=True)
        (scratch / need).write_text("{}")
    (tmp_path / "ids.json").write_text(json.dumps({"ids": ["a"]}))
    code = hm.main(["--scratch", str(scratch), "--data-dir", str(real), "--ids", str(tmp_path / "ids.json"), "--max-usd", "0.1",
                    "--responsibilities", "--out", str(scratch / "matcher")])
    assert code == 2 and "step-2 input" in capsys.readouterr().err
    assert not (scratch / "matcher").exists()


# --- the d: class in the stability tool -----------------------------------------------------------------------------

def det(*units, unmapped_must=0):
    return {"units": [{"key": f"d:{k}", "importance": imp, "kind": "skill"} for k, imp in units], "unmapped": {"must": unmapped_must, "other": 0}}


def test_det_stability_reads_the_per_pass_dict_shape():
    doc = {"detUnitKeys": {
        "ad1": [det(("sql", "must"), ("python", "must"), unmapped_must=2), det(("sql", "must"), unmapped_must=1)],
        "ad2": [det(("communication", "must")), det(("communication", "must"))],
        "ad3": [det()]}}
    out = ms.det_stability(doc)
    must = out["classes"]["nonGenericMustUnits"]
    assert must["ads"] == 1 and must["median"] == 0.5          # ad1: {sql,python} vs {sql}
    assert must["adsUndefined"] == 2                            # ad2 only generic, ad3 one pass
    assert out["classes"]["allUnits"]["ads"] == 2               # ad2 identical (1.0) and ad1
    assert out["unmappedMustShare"]["ads"] == 1                 # ad1: 2/4 and 1/2 -> 0.5
    assert out["unmappedMustShare"]["median"] == 0.5


def test_det_stability_is_none_without_the_key_and_the_cli_prints_it(tmp_path, capsys):
    assert ms.det_stability({"unitKeys": {}}) is None
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"unitKeysVersion": 1, "unitKeys": {"a": [[{"key": "c:x", "canonical": True, "kind": "skill", "importance": "must"}]] * 2},
                             "detUnitKeys": {"a": [det(("sql", "must")), det(("sql", "must"))]}}))
    assert ms.main([str(p)]) == 0
    assert "d: keys" in capsys.readouterr().out
