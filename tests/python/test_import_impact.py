"""The cache impact a profile import would have (Wave 7): which draft sections change profileVersion, and what the counts say."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from profile_import import impact
from evidence_index import build_candidate

ROOT = Path(__file__).resolve().parents[2]


def _profile(**parsed):
    base = {"skills": ["SQL"], "projects": ["Payments revamp"], "education": ["BSc"], "certifications": ["CSPO"], "workExperience": [],
            "experienceDetail": [{"title": "PM", "company": "Acme", "start": "2019-01", "end": "2022-01", "description": "", "bullets": ["Led the roadmap."]}]}
    base.update(parsed)
    return {"basicProfile": {"fullName": "Test Person", "currentRole": "PM", "experienceYears": "8", "targetRoles": ["PM"], "languages": [{"language": "English"}], "location": "X", "email": "a@b.invalid"},
            "resume": {"parsedData": base}, "repositories": {"githubLinks": []}}


def _version(profile, intelligence=None):
    return build_candidate(profile, intelligence or {}, [])["evidenceVersion"]


def test_an_identical_profile_keeps_the_version_so_no_cached_answer_is_lost():
    a = _profile()
    assert _version(a) == _version(copy.deepcopy(a))
    out = impact.profile_impact(a, copy.deepcopy(a), {}, [], cache_keys=[f"ad1:{_version(a)}:p:rq1-x", f"ad2:{_version(a)}:p:rq1-x"])
    assert out["profileVersion"]["changed"] is False
    assert out["matcher"] == {"entriesTotal": 2, "matchingNow": 2, "stopMatching": 0, "alreadyMatchingAfter": 0}
    assert out["evidence"] == {"before": out["evidence"]["before"], "after": out["evidence"]["after"], "added": 0, "removed": 0}


def test_sections_that_feed_the_evidence_change_the_version():
    base = _profile()
    changed = {
        "a bullet": _profile(experienceDetail=[{"title": "PM", "company": "Acme", "start": "2019-01", "end": "2022-01", "description": "", "bullets": ["Led the roadmap.", "Cut churn."]}]),
        "skills": _profile(skills=["SQL", "Python"]),
        "projects": _profile(projects=["Payments revamp", "New app"]),
        "education": _profile(education=["BSc", "MSc"]),
        "certifications": _profile(certifications=["CSPO", "PSM"]),
    }
    for name, other in changed.items():
        assert _version(other) != _version(base), name


def test_fields_that_are_not_evidence_do_not_change_the_version():
    base = _profile()
    other = copy.deepcopy(base)
    other["basicProfile"].update({"email": "other@b.invalid", "phone": "+1 555 0100", "location": "Elsewhere", "currentRole": "Head of Product"})
    other["basicProfile"]["languages"] = [{"language": "German"}]
    other["resume"]["parsedData"]["links"] = ["https://example.invalid/x"]
    other["resume"]["parsedData"]["summary"] = "A new summary."
    other["repositories"]["githubLinks"] = ["https://github.com/x"]
    assert _version(other) == _version(base)
    out = impact.profile_impact(base, other, {}, [], findings_count=4)
    assert out["profileVersion"]["changed"] is False
    assert out["findings"] == {"stored": 4, "mayMiss": True}  # the current role is part of the browser AI profile summary


def test_a_change_reports_how_many_cached_entries_stop_matching_and_nothing_else():
    a, b = _profile(), _profile(skills=["SQL", "Python"])
    va, vb = _version(a), _version(b)
    out = impact.profile_impact(a, b, {}, [], cache_keys=[f"x:{va}:p", f"y:{va}:p", f"z:{vb}:p", "odd"])
    assert out["profileVersion"] == {"before": build_candidate(a, {}, [])["profileVersion"],
                                     "after": build_candidate(b, {}, [])["profileVersion"], "changed": True}
    assert out["matcher"] == {"entriesTotal": 3, "matchingNow": 2, "stopMatching": 2, "alreadyMatchingAfter": 1}
    assert out["evidence"]["added"] == 1 and out["evidence"]["removed"] == 0
    assert out["judge"] == {"changes": False}


def test_the_answer_carries_counts_and_hashes_only():
    a, b = _profile(), _profile(skills=["SQL", "SECRET-SKILL-CANARY"])
    text = json.dumps(impact.profile_impact(a, b, {}, []))
    assert "CANARY" not in text and "Test Person" not in text and "a@b.invalid" not in text


def test_the_runner_answers_fixed_codes_and_reads_only():
    ok = subprocess.run([sys.executable, "-I", str(ROOT / "python/profile_import/run_impact.py")], input=json.dumps({"before": _profile(), "after": _profile(skills=["Go"])}), capture_output=True, text=True)
    out = json.loads(ok.stdout)
    assert out["ok"] is True and out["impact"]["profileVersion"]["changed"] is True and ok.stderr == ""
    for bad in ("", "{}", json.dumps({"before": 1, "after": {}}), "not json CANARY-5"):
        done = subprocess.run([sys.executable, "-I", str(ROOT / "python/profile_import/run_impact.py")], input=bad, capture_output=True, text=True)
        answer = json.loads(done.stdout)
        assert answer["ok"] is False and answer["code"] in ("invalid_request", "impact_failed")
        assert "CANARY" not in done.stdout + done.stderr and done.stderr == ""
