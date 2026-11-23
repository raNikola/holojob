"""Scoring 1.7: an ad whose Fit 3 role class is "target" is on-track (gate, off-track cap, unrelated-title cap).

Synthetic ads only: no test reads the owner's data. The three real ads that were misread are checked in the live run, by id.
"""

from __future__ import annotations

import inspect
import re

import pytest

import role_class
import scorer
from match_engine import gates
from scorer import OFF_TRACK_CAP, UNRELATED_TITLE_CAP, role_on_track, score_job
from test_scoring_16 import BANK, intel, job

TRACKS = {"product_management", "product_ownership", "program_management"}
MISREAD = {"roleTrack": "project_delivery", "roleTrackEvidence": "coordinate delivery of the programme"}


def ad_row(cls, title="Product Delivery Manager", facts=None, **kw):
    row = job(title=title, **kw)
    row["llmFacts"] = {**(row.get("llmFacts") or {}), **(MISREAD if facts is None else facts)}
    if cls is not None:
        row["roleClass"] = cls
    return row


def test_a_target_class_is_on_track_whatever_the_track_says():
    assert role_on_track(ad_row("target"), TRACKS) is True
    assert role_on_track(ad_row("target", facts={}), None) is True  # even with no family or no track read


@pytest.mark.parametrize("cls", ["adjacent", "other", "not available", None])
def test_every_other_class_takes_the_track_test_as_before(cls):
    assert role_on_track(ad_row(cls), TRACKS) is False
    assert role_on_track(ad_row(cls, facts={"roleTrack": "product_management", "roleTrackEvidence": "owns the roadmap"}), TRACKS) is True


@pytest.mark.parametrize("cls", ["adjacent", "other", "not available", None])
def test_unknown_stays_unknown_and_never_lowers(cls):
    assert role_on_track(ad_row(cls), None) is None  # no family
    assert role_on_track(ad_row(cls, facts={"roleTrack": "other", "roleTrackEvidence": "x"}), TRACKS) is None
    assert role_on_track(ad_row(cls, facts={"roleTrack": "engineering"}), TRACKS) is None  # no evidence quote


def test_the_gate_passes_a_target_class_and_otherwise_decides_as_before():
    assert gates.role_family_result(ad_row("target"), "product") == gates.PASS
    assert gates.role_family_result(ad_row("not available"), "product") == gates.FAIL
    assert gates.role_family_result(ad_row("adjacent"), "product") == gates.FAIL
    assert gates.role_family_result(ad_row("target"), None) == gates.UNKNOWN  # no family: nothing is assumed


def test_a_target_class_skips_both_caps_and_a_non_target_class_keeps_them():
    # The same misread ad, with a product title the extractor read as delivery work: the class is the only difference.
    base = score_job(ad_row(None), intel(**BANK))
    assert base["hardCapped"] is True and base["matchScore"] <= OFF_TRACK_CAP
    for cls in ("adjacent", "other", "not available"):
        assert score_job(ad_row(cls), intel(**BANK))["matchScore"] == base["matchScore"]
    row = score_job(ad_row("target"), intel(**BANK))
    assert not any(r.startswith("Capped: the ad describes") or r.startswith("Capped: the title") for r in row["reasons"])
    assert row["matchScore"] >= base["matchScore"]
    assert row["scoreBeforeCaps"] >= base["scoreBeforeCaps"]


def test_the_unrelated_title_cap_is_skipped_by_the_class_alone():
    title = "Account Executive"  # an unrelated title; the track says nothing against it
    capped = score_job(ad_row("other", title=title, facts={}), intel(**BANK))
    assert capped["matchScore"] <= UNRELATED_TITLE_CAP
    free = score_job(ad_row("target", title=title, facts={}), intel(**BANK))
    assert not any(r.startswith("Capped: the title") for r in free["reasons"])
    assert free["matchScore"] > UNRELATED_TITLE_CAP


@pytest.mark.parametrize("title", ["Product Delivery Manager", "Delivery Manager, Product Platform", "Technical Product Delivery Lead"])
def test_product_titled_ads_misread_as_delivery_pass_without_a_title_exception(title):
    # The three misread ads of the live run (FanDuel, Intermedia, Nebius) have this shape: a product title, a delivery track, a target class.
    row = score_job(ad_row("target", title=title), intel(**BANK))
    assert gates.role_family_result(ad_row("target", title=title), "product") == gates.PASS
    assert not any(r.startswith("Capped: the ad describes") or r.startswith("Capped: the title") for r in row["reasons"])
    # The same title with a non-target class is decided exactly as before 1.7.
    assert score_job(ad_row("adjacent", title=title), intel(**BANK))["matchScore"] <= OFF_TRACK_CAP


def test_scoring_version_is_1_7():
    assert scorer.SCORING_VERSION == "1.7"


# --- invariants -----------------------------------------------------------------------------------------------------------

def test_the_gate_and_both_caps_read_the_one_predicate():
    gate_src = inspect.getsource(gates.role_family_result)
    score_src = inspect.getsource(scorer.score_job)
    assert "role_on_track(" in gate_src and "role_on_track(" in score_src  # gate and off-track cap
    assert "role_class_is_target(job)" in score_src  # the title cap
    assert "role_class_is_target(job)" in inspect.getsource(scorer.role_on_track)  # one definition of "target"
    # No second place compares the class to "target" in the scorer's decisions.
    assert len(re.findall(r'"roleClass"\) == "target"', inspect.getsource(scorer))) == 1
    assert "roleClass" not in gate_src


def _calls(module):
    """(attribute name, line) of every real call `role_class.<name>(...)` / `score_jobs(...)` in a module, found in the syntax tree (not in a string)."""
    import ast
    found = []
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "role_class":
                found.append((f.attr, node.lineno))
            elif isinstance(f, ast.Name) and f.id == "score_jobs":
                found.append(("score_jobs", node.lineno))
    return found


def test_the_class_is_stamped_before_scoring_and_the_ceiling_runs_after():
    import run_scoring
    import import_job_url
    import rescore_kept
    for module in (run_scoring, import_job_url, rescore_kept):
        calls = _calls(module)
        names = [n for n, _ in calls]
        assert "stamp" not in names and "label" in names and "ceiling" in names and "score_jobs" in names, module.__name__
        assert min(l for n, l in calls if n == "label") < min(l for n, l in calls if n == "score_jobs")
        assert max(l for n, l in calls if n == "ceiling") > min(l for n, l in calls if n == "score_jobs")
    assert not hasattr(role_class, "stamp")
