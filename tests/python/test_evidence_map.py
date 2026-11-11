"""The competency evidence map in check mode, on fictional verdicts. No real data, no model."""

import json
import stat
from datetime import datetime, timezone

import pytest

from calibration import matcher_v3 as v3
from match_engine.evidence_map import EvidenceMap, text_hash

ITEM = {"id": "ev-abc", "text": "Led the roadmap for three teams", "strength": 3}
JOB = {"id": "job-1"}


class FakeMapper:
    def __init__(self, status="reviewed"):
        self.status = status

    def mapping_status(self, _req):
        return self.status


def candidate(**extra):
    return {"evidenceVersion": "ev1", "evidence": [ITEM], "confirmedFacts": [], **extra}


def req(status="MET", strength=3, rid="roadmap", **extra):
    return {"id": rid, "text": "Owning a roadmap", "kind": "skill", "status": status, "strength": strength, "quoteVerified": True, "evidenceId": ITEM["id"], "evidenceQuote": "Led the roadmap", **extra}


def memory(tmp_path, mapper=None, cand=None, **kw):
    return EvidenceMap(cand or candidate(), FakeMapper() if mapper is None else mapper, tmp_path / "cache" / "map.json", now=lambda: datetime(2026, 11, 11, tzinfo=timezone.utc), **kw)


def see(m, *reqs, key="k1"):
    m.observe(JOB, {"cacheKey": key, "requirements": list(reqs)})
    return m


def test_a_stable_verified_met_is_learned_in_the_spec_shape_with_no_candidate_text(tmp_path):
    m = see(memory(tmp_path), req())
    m.save()
    stored = json.loads(m.path.read_text())
    assert (stored["version"], stored["evidenceVersion"]) == (1, "ev1")
    assert stored["entries"]["roadmap"] == {"status": "MET", "evidenceId": "ev-abc", "evidenceTextHash": text_hash(ITEM["text"]), "strength": 3, "stability": "one_reading",
                                            "learnedFrom": {"jobId": "job-1", "requirementId": "roadmap", "via": "reviewed"}, "learnedAt": "2026-11-11T00:00:00Z", "checks": {"agree": 0, "disagree": 0}}
    assert "Led the roadmap" not in m.path.read_text() and "Owning" not in m.path.read_text()
    assert stat.S_IMODE(m.path.stat().st_mode) == 0o600


@pytest.mark.parametrize("line", [
    req("CONTRADICTED"), req("NOT_EVIDENCED", 0), req("MISSING", 0), req("UNKNOWN", 0), req("PARTIAL", 4),
    req(qualifier={"kind": "years", "value": 5}), req(requirementLevel="expert"),
    req(quoteVerified=False), req(evidenceQuote=None), req(evidenceId="ev-gone"),
    req(strength=2),  # one reading needs strength 3-4
    req(flagged=True, flagReason="MET against PARTIAL"), req(kind="language"),
], ids=lambda r: f"{r['status']}-{r['strength']}-{sorted(set(r) - set(req()))}")
def test_the_map_never_learns_this_line(tmp_path, line):
    assert see(memory(tmp_path), line).entries == {}


def test_a_line_a_fact_settled_is_not_a_matcher_verdict(tmp_path):
    assert see(memory(tmp_path, cand=candidate(confirmedFacts=[{"competencyId": "roadmap", "coveredTexts": []}])), req()).entries == {}


@pytest.mark.parametrize("status,expected", [("pending", False), ("demoted", False), ("auto", False), ("reviewed", True)])
def test_only_a_reviewed_link_carries_by_itself(tmp_path, status, expected):
    assert bool(see(memory(tmp_path, FakeMapper(status)), req()).entries) is expected


def test_an_auto_link_carries_only_a_text_the_owner_covered_and_a_pending_link_never(tmp_path):
    covered = candidate(confirmedFacts=[{"competencyId": "other", "coveredTexts": ["Owning a roadmap"]}])
    assert see(memory(tmp_path, FakeMapper("auto"), covered), req()).entries["roadmap"]["learnedFrom"]["via"] == "covered"
    assert see(memory(tmp_path, FakeMapper("pending"), covered), req()).entries == {}


def test_a_provisional_id_is_not_learned_and_a_dictionary_term_is(tmp_path):
    assert see(memory(tmp_path, FakeMapper(None)), req(rid="prov:aaaa")).entries == {}
    assert see(memory(tmp_path, FakeMapper(None)), req()).entries["roadmap"]["learnedFrom"]["via"] == "seed"


def test_two_agreeing_readings_may_teach_a_lower_strength_and_a_flagged_line_may_not(tmp_path):
    a = {"roadmap": req(strength=2, requirementLevel=None, candidateLevel=None)}
    m = see(memory(tmp_path), v3.aggregate_two(a, a)["roadmap"])
    assert m.entries["roadmap"]["stability"] == "two_readings"
    b = {"roadmap": req("PARTIAL", 2, requirementLevel=None, candidateLevel=None)}
    assert see(memory(tmp_path), v3.aggregate_two(a, b)["roadmap"]).entries == {}


def test_check_mode_counts_agreement_and_changes_no_verdict(tmp_path):
    m = see(memory(tmp_path), req())
    second = req("PARTIAL", 2)
    output = {"cacheKey": "k2", "requirements": [second]}
    m.observe(JOB, output)
    see(m, req(), key="k3")
    assert m.entries["roadmap"]["checks"] == {"agree": 1, "disagree": 1} and output["requirements"] == [second] and m.summary() == {"entries": 1, "agree": 1, "disagree": 1}


def test_a_requirement_with_a_level_is_never_checked_against_the_map(tmp_path):
    m = see(memory(tmp_path), req())
    see(m, req(qualifier={"kind": "years", "value": 5}), key="k2")
    assert m.entries["roadmap"]["checks"] == {"agree": 0, "disagree": 0}


def test_a_cached_verdict_seen_again_is_not_a_new_check(tmp_path):
    m = see(memory(tmp_path, already_matched={"k9"}), req())
    see(m, req(), key="k9")
    assert m.entries["roadmap"]["checks"] == {"agree": 0, "disagree": 0}


def test_an_entry_is_dropped_when_the_cv_text_hash_changes(tmp_path):
    m = see(memory(tmp_path), req())
    m.save()
    changed = {**ITEM, "text": "Led something else"}
    reloaded = memory(tmp_path, cand=candidate(evidence=[changed]))
    assert reloaded.entries == {} and reloaded.dirty
    reloaded.save()
    assert json.loads(m.path.read_text())["entries"] == {}


def test_a_new_evidence_version_empties_the_map(tmp_path):
    m = see(memory(tmp_path), req())
    m.save()
    assert memory(tmp_path, cand=candidate(evidenceVersion="ev2")).entries == {}
    assert memory(tmp_path).entries.keys() == {"roadmap"}


def test_nothing_is_written_when_nothing_changed(tmp_path):
    m = memory(tmp_path)
    m.save()
    assert not m.path.exists()
