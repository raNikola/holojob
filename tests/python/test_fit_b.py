"""Experiment B: the pre-registered evaluation rules and the privacy behaviour of its requests (synthetic data only; no model, no data/ access)."""

import math
import sys
from pathlib import Path

import pytest

from calibration import fit_b, fit_b_metrics as m

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import measure_fit_b  # noqa: E402


def test_ties_are_broken_by_ad_id_and_unlabelled_ads_are_not_counted_as_zero():
    scores = {"b": 50, "a": 50, "c": 10, "z": 99}
    assert m.order(scores) == ["z", "a", "b", "c"]
    gains = {"a": 3.0, "b": 0.0, "c": 1.0}  # z is unlabelled: excluded from the ranking, not a 0
    assert m.ndcg_of(scores, gains, 10) == pytest.approx(m.ndcg_at([3.0, 0.0, 1.0], 10))


def test_ndcg_known_values():
    assert m.ndcg_at([3, 2, 1], 3) == pytest.approx(1.0)
    assert m.ndcg_at([0, 0, 0], 3) is None
    worst = m.dcg([1, 2, 3], 3) / m.dcg([3, 2, 1], 3)
    assert m.ndcg_at([1, 2, 3], 3) == pytest.approx(worst) and worst < 1


def test_a_win_needs_the_margin_the_interval_and_the_apply_guard():
    ids = [f"ad{n:02d}" for n in range(20)]
    gains = {i: float(3 - n // 5) for n, i in enumerate(ids)}  # ideal order is the id order
    good = {i: 100 - n for n, i in enumerate(ids)}
    bad = {i: n for n, i in enumerate(ids)}
    win = m.verdict(good, bad, gains, delta=0.05)
    assert win["win"] and win["ciLow"] > 0
    assert not m.verdict(good, bad, gains, delta=0.99)["win"]  # margin not reached
    assert not m.verdict(bad, good, gains, delta=0.05)["win"]  # B worse
    assert not m.verdict(good, good, gains, delta=0.05)["win"]  # no difference


def test_the_apply_guard_fails_when_a_top_half_apply_ad_falls_out_of_the_top_half():
    ids = [f"ad{n:02d}" for n in range(10)]
    gains = {i: (3.0 if n < 2 else 0.0) for n, i in enumerate(ids)}
    base = {i: 100 - n for n, i in enumerate(ids)}
    demoted = {**base, "ad00": 0}
    guard = m.apply_guard(demoted, base, gains)
    assert guard["violators"] == ["ad00"] and not guard["pass"]
    assert m.apply_guard(base, base, gains)["pass"]


def test_the_bootstrap_is_deterministic_and_paired():
    ids = [f"ad{n:02d}" for n in range(12)]
    gains = {i: float(n % 4) for n, i in enumerate(ids)}
    a, b = {i: n * 7 % 11 for n, i in enumerate(ids)}, {i: n * 5 % 13 for n, i in enumerate(ids)}
    one, two = m.paired_bootstrap(a, b, gains, resamples=300), m.paired_bootstrap(a, b, gains, resamples=300)
    assert one["diffs"] == two["diffs"] and len(one["diffs"]) == 300


def test_delta_is_the_larger_of_the_floor_and_twice_the_noise():
    assert m.delta_for(0.01) == 0.05 and m.delta_for(0.04) == pytest.approx(0.08)
    assert m.run_to_run_sd(0.6, 0.5) == pytest.approx(0.1 / math.sqrt(2))


def test_an_applied_ad_takes_the_top_gain_and_never_lowers_a_higher_one():
    assert m.combined_gain(None, True) == 3.0 and m.combined_gain(1.5, True) == 3.0 and m.combined_gain(1.5, False) == 1.5 and m.combined_gain(None, False) is None


PROFILE = {"basicProfile": {"fullName": "Zed Quux", "email": "zed@example.com", "phone": "+381 11 555 0100", "currentRole": "Product Manager",
                            "experienceYears": "9 years", "location": "Nis", "targetRoles": ["Head of Product"], "languages": ["Serbian"]},
           "resume": {"parsedData": {"summary": "Product leader.", "skills": ["Roadmapping"], "certifications": ["CSPO"],
                                     "experienceDetail": [{"title": "Product Manager", "company": "Acme Ltd", "location": "Berlin", "start": "2020", "end": "2024",
                                                           "bullets": ["Launched a billing product"]}]}}}
INTEL = {"candidateSummary": {"seniorityLevel": "senior"}, "historyEntries": [{"role": "PM", "domains": ["fintech"], "capabilities": ["pricing"]}]}


def test_the_summary_never_carries_what_the_inventory_says_is_not_sent():
    s = fit_b.build_summary("public_cv", PROFILE, INTEL, ("Zed Quux", []))
    for banned in ("Zed", "Quux", "zed@example.com", "555", "Acme", "Berlin", "Head of Product", "Serbian", "Nis"):
        assert banned not in s["text"]
    assert "fintech" not in s["text"]  # P-pub does not hold the confirmed C entries
    assert "fintech" in fit_b.build_summary("public_cv_plus_confirmed_C", PROFILE, INTEL, ("Zed Quux", []))["text"]


def test_a_summary_that_still_holds_an_identifier_is_not_built():
    leaky = {**PROFILE, "resume": {"parsedData": {**PROFILE["resume"]["parsedData"], "summary": "Reach me at someone.else@example.org"}}}
    out = fit_b.build_summary("public_cv", leaky, INTEL, ("Zed Quux", []))
    assert "someone.else@example.org" not in out["text"]  # redacted; and a leak that survives redaction raises


def test_the_ad_text_is_public_text_only_and_redacted():
    job = {"title": "PM", "description": "<p>Write to jobs@corp.example or call +44 20 7946 0958.</p>", "company": "Corp", "location": "Paris"}
    prompt = fit_b.build_prompt({"text": "S"}, job, ("Zed Quux", []))
    assert "jobs@corp.example" not in prompt and "7946" not in prompt and "Corp" not in prompt and "Paris" not in prompt


def test_a_reply_outside_the_schema_is_not_a_rating():
    ok = {"score": 70, "must_haves": [{"requirement": "x", "status": "met"}], "domain_experience": "direct", "seniority": "match", "reason": "r"}
    assert fit_b.valid_rating(ok) and not fit_b.valid_rating({**ok, "score": 101}) and not fit_b.valid_rating({**ok, "seniority": "huge"}) and not fit_b.valid_rating("70")


def test_a_paid_run_needs_confirm_and_a_cap_and_never_writes_under_the_real_data_dir(tmp_path):
    base = ["run", "--scope", "public_cv", "--ids", str(tmp_path / "ids.json"), "--out", str(tmp_path), "--label", "x"]
    assert measure_fit_b.main(base) == 2
    assert measure_fit_b.main(base + ["--confirm"]) == 2
    with pytest.raises(SystemExit):
        measure_fit_b.refuse_real(Path("/srv/holojob/data/anything"))
