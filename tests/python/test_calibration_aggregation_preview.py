"""The offline aggregation preview on fictional verdicts. No real data, no model."""

import pytest

from calibration import aggregation_preview as ap

SECTIONS = {"education": 1, "certification": 1, "language": 2}
GATES = [{"gate": g, "result": "pass"} for g in ("work_authorization", "location", "language", "salary_floor", "role_family")]


def req(status, kind="skill", importance="must", strength=3):
    return {"id": f"{kind}-{status}", "text": "t", "kind": kind, "importance": importance, "status": status, "strength": strength, "quoteVerified": True}


# --- vocabulary ---------------------------------------------------------------------------


def test_missing_is_contradicted_only_for_a_closed_world_kind_with_a_non_empty_profile_section():
    assert ap.typed_status(req("MISSING", "certification"), SECTIONS) == ap.CONTRADICTED
    assert ap.typed_status(req("MISSING", "education"), SECTIONS) == ap.CONTRADICTED
    assert ap.typed_status(req("MISSING", "language"), SECTIONS) == ap.CONTRADICTED
    assert ap.typed_status(req("MISSING", "certification"), {"certification": 0}) == ap.NOT_EVIDENCED  # nothing listed: silence
    for kind in ("skill", "experience", "domain", "other"):
        assert ap.typed_status(req("MISSING", kind), SECTIONS) == ap.NOT_EVIDENCED  # open prose: silence is not absence


def test_unknown_is_silence_and_positive_verdicts_are_kept():
    assert ap.typed_status(req("UNKNOWN", "education"), SECTIONS) == ap.NOT_EVIDENCED
    assert ap.typed_status(req("MET"), SECTIONS) == ap.MET and ap.typed_status(req("PARTIAL"), SECTIONS) == ap.PARTIAL


# --- the owner's rule: silence never moves fit ------------------------------------------------


@pytest.mark.parametrize("silent", [req("UNKNOWN"), req("MISSING", "skill"), req("MISSING", "experience", "preferred"),
                                    req("UNKNOWN", "education", "nice"), req("MISSING", "certification", "must")])
def test_adding_a_silent_requirement_never_changes_fit(silent):
    base = [req("MET"), req("PARTIAL", "experience"), req("MISSING", "language")]
    silent = {**silent, "id": "extra"}
    if ap.typed_status(silent, SECTIONS) != ap.NOT_EVIDENCED:
        silent = {**silent, "kind": "skill"}  # a closed-world MISSING is explicit evidence against, tested below
    assert ap.fit_of(base + [silent], SECTIONS) == ap.fit_of(base, SECTIONS)


def test_removing_every_silent_item_leaves_fit_unchanged_and_silence_never_raises_it():
    mixed = [req("MET"), req("UNKNOWN"), req("MISSING", "skill"), req("PARTIAL", strength=2), req("UNKNOWN", importance="nice")]
    settled = [r for r in mixed if r["status"] in ("MET", "PARTIAL")]
    assert ap.fit_of(mixed, SECTIONS) == ap.fit_of(settled, SECTIONS)
    low = [req("PARTIAL", strength=1)]
    assert ap.fit_of(low + [req("UNKNOWN")] * 5, SECTIONS) == ap.fit_of(low, SECTIONS)  # five unknowns do not lift a weak fit


def test_explicit_evidence_against_lowers_fit():
    base = [req("MET"), req("MET", "experience")]
    assert ap.fit_of(base + [req("MISSING", "certification")], SECTIONS) < ap.fit_of(base, SECTIONS)
    assert ap.fit_of(base + [req("MISSING", "certification")], {"certification": 0}) == ap.fit_of(base, SECTIONS)  # empty section: silence


def test_no_estimate_when_nothing_is_settled_and_never_a_fake_zero():
    assert ap.fit_of([req("UNKNOWN"), req("MISSING", "skill")], SECTIONS) is None
    pv = ap.preview([req("UNKNOWN")], GATES, SECTIONS)
    assert pv["fit"] is None and pv["label"] == "No estimate"


# --- confidence, range, flag ------------------------------------------------------------------


def test_silence_lowers_confidence_and_only_confidence():
    settled = [req("MET"), req("MET", "experience")]
    silent = settled + [req("UNKNOWN"), req("MISSING", "skill")]
    a, b = ap.preview(settled, GATES, SECTIONS), ap.preview(silent, GATES, SECTIONS)
    assert a["fit"] == b["fit"] and b["confidence"] < a["confidence"] == 1.0


def test_the_range_brackets_fit_and_a_contradiction_counts_as_verified_for_confidence():
    reqs = [req("MET"), req("UNKNOWN"), req("MISSING", "certification")]
    pv = ap.preview(reqs, GATES, SECTIONS)
    lo, hi = pv["fitRange"]
    assert lo <= pv["fit"] <= hi
    assert pv["contradicted"] == 1 and pv["notEvidenced"] == 1
    only_contradicted = ap.preview([req("MISSING", "certification")], GATES, SECTIONS)
    assert only_contradicted["confidence"] == 1.0 and only_contradicted["fit"] == 0


def test_the_flag_counts_unconfirmed_musts_and_there_is_no_incomplete_label():
    reqs = [req("MET")] + [req("UNKNOWN")] * 4  # far past the engine's old one-third unknown-must limit
    pv = ap.preview(reqs, GATES, SECTIONS)
    assert pv["flag"] == "unconfirmed: 4 must requirements" and pv["label"] != "Incomplete" and pv["fit"] == 90
    assert ap.preview([req("MET")], GATES, SECTIONS)["flag"] is None
    nice_only = ap.preview([req("MET"), req("UNKNOWN", importance="nice")], GATES, SECTIONS)
    assert nice_only["flag"] is None and nice_only["notEvidenced"] == 1


# --- critical unconfirmed must ----------------------------------------------------------------


def test_a_critical_unconfirmed_must_holds_the_bucket_lowers_confidence_harder_and_never_moves_fit():
    no_sections = {"education": 0, "certification": 0, "language": 0}
    plain = [req("MET")]
    critical = plain + [req("MISSING", "certification")]  # empty section: silence on a binary prerequisite
    ordinary = plain + [req("MISSING", "skill")]
    pc, po = ap.preview(critical, GATES, no_sections), ap.preview(ordinary, GATES, no_sections)
    assert pc["criticalUnconfirmed"] == 1 and po["criticalUnconfirmed"] == 0
    assert pc["fit"] == po["fit"] == ap.preview(plain, GATES, no_sections)["fit"]
    assert pc["confidence"] < po["confidence"]
    assert pc["bucket"] == "check_first" and po["bucket"] == "apply"
    assert ap.preview(critical, GATES, no_sections, bucket="blocked")["bucket"] == "blocked"  # a worse bucket is kept


def test_a_nice_to_have_or_an_open_prose_kind_is_never_critical():
    no_sections = {"education": 0, "certification": 0, "language": 0}
    assert ap.preview([req("MET"), req("MISSING", "certification", "nice")], GATES, no_sections)["criticalUnconfirmed"] == 0
    assert ap.preview([req("MET"), req("MISSING", "experience")], GATES, no_sections)["criticalUnconfirmed"] == 0


# --- labels ----------------------------------------------------------------------------------


@pytest.mark.parametrize("fit, label", [(75, "Strong"), (74, "Good"), (45, "Good"), (44, "Partial"), (30, "Partial"), (29, "Weak")])
def test_labels_use_the_engines_thresholds(fit, label):
    assert ap.label_for(fit) == label


def test_the_module_names_no_profession():
    source = open(ap.__file__, encoding="utf-8").read().lower()
    for word in ("product manager", "engineer", "nurse", "teacher", "developer", "driver"):
        assert word not in source
