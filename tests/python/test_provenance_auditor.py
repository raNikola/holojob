"""The quality audit's provenance check: a fact backs a claim only as whole tokens, and only if it states the claim."""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "python" / "quality_audit"))

from provenance_auditor import audit_provenance  # noqa: E402


def profile(raw="", skills=(), education=(), certifications=(), years=None):
    return {
        "basicProfile": {"experienceYears": years} if years else {},
        "resume": {
            "rawText": raw,
            "parsedData": {"skills": list(skills), "education": list(education), "certifications": list(certifications)},
        },
    }


def degree_issues(result):
    return [i for i in result["provenanceIssues"] if i.startswith("Unverified degree")]


def cert_issues(result):
    return [i for i in result["provenanceIssues"] if i.startswith("Unverified certification")]


def metric_issues(result):
    return [i for i in result["provenanceIssues"] if i.startswith("Unsupported metric")]


# --- what used to pass and must not ------------------------------------------------------------------


@pytest.mark.parametrize(("source", "claim"), [
    (profile(skills=["SQL"]), "PhD in SQL from Stanford"),
    (profile(skills=["R"]), "PhD in R from Stanford"),
    (profile(skills=["C"]), "Master of Science, Caltech"),
    (profile(education=["University of Niš"]), "PhD from University of Niš"),
    (profile(education=["MBA"]), "MBA from Harvard"),
    (profile(raw="Listed items in the catalogue"), "MS in"),
    (profile(), "Doctorate in Physics"),
], ids=["skill-sql", "skill-r", "skill-c", "school-without-degree", "bare-keyword", "inside-a-word", "no-fact"])
def test_an_invented_degree_is_severe(source, claim):
    result = audit_provenance(f"{claim}\n", source, {})
    assert degree_issues(result), result
    assert result["severeCount"] == 1
    assert result["provenanceSafe"] is False
    assert result["provenanceStatus"] == "needs_review"


@pytest.mark.parametrize(("source", "claim"), [
    (profile(skills=["Python"]), "Certified in Python"),
    (profile(skills=["R"]), "Certification in R programming"),
    (profile(skills=["AWS"]), "Certificate from AWS"),
    (profile(raw="Attended a certification course"), "Certified Cloud Architect"),
], ids=["skill-python", "skill-r", "skill-aws", "unrelated-line"])
def test_an_invented_certification_is_flagged(source, claim):
    assert cert_issues(audit_provenance(f"{claim}\n", source, {}))


@pytest.mark.parametrize(("source", "claim"), [
    (profile(raw="Grew revenue by 150% in two years"), "50%"),
    (profile(raw="Grew revenue by 1.5% in two years"), "5%"),
    (profile(raw="Served 1,500 users"), "500 users"),
    (profile(raw="Served 1,000 users"), "2,000 users"),
    (profile(raw="Worked for 15 years"), "5 years"),
    (profile(skills=["C"]), "870 customers"),
    (profile(skills=["R"]), "870 users"),
    (profile(years="5"), "500 users"),
    (profile(years="12"), "12 users"),
    (profile(years="12"), "12%"),
    (profile(years="12"), "2 years"),
    (profile(years="12"), "120 years"),
], ids=["tail-of-percent", "tail-of-decimal", "tail-of-thousands", "other-thousands", "tail-of-years", "skill-c", "skill-r",
        "years-inside-number", "years-as-users", "years-as-percent", "years-tail", "years-head"])
def test_an_invented_metric_is_flagged(source, claim):
    assert metric_issues(audit_provenance(f"Reached {claim} overall.", source, {}))


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_fact_backs_nothing(blank):
    intelligence = {"experienceMap": {"projectHighlights": [blank]}, "skillsMap": {"technicalSkills": [blank]}}
    result = audit_provenance("PhD in Physics. Certified Architect. Reached 99%.", profile(), intelligence)
    assert degree_issues(result) and cert_issues(result) and metric_issues(result)


# --- what is legitimate and must keep passing --------------------------------------------------------


@pytest.mark.parametrize(("source", "claim"), [
    (profile(raw="Bachelor of Economics, University of Niš"), "Bachelor of Economics"),
    (profile(raw="Bachelor of Economics, University of Niš"), "Bachelor of Economics, University of Niš"),
    (profile(education=["Bachelor of Economics"]), "Bachelor of Economics, University of Niš, 2012"),
    (profile(education=["MBA"]), "MBA"),
    (profile(education=["M.S. in Computer Science"]), "M.S. in Computer Science"),
    (profile(education=["BSc Economics"]), "BSc Economics"),
    (profile(raw="Ph.D. in Physics, ETH"), "Ph.D. in Physics"),
    (profile(education=["Master of Science"]), "Master of Science in Physics, ETH"),
    (profile(raw="Bachelor of Economics"), "bachelor of economics"),
], ids=["part-of-line", "whole-line", "fact-inside-claim", "bare-keyword-same", "dotted", "bsc", "phd-dotted", "fact-names-degree", "case"])
def test_a_stated_degree_passes(source, claim):
    result = audit_provenance(f"{claim}\n", source, {})
    assert not degree_issues(result), result
    assert result["severeCount"] == 0
    assert result["provenanceSafe"] is True


def test_a_long_degree_cut_inside_a_word_by_the_length_limit_passes():
    line = "Bachelor of " + "Interdisciplinary Economics and Quantitative Management Sciences and Administration"
    result = audit_provenance(f"{line}\n", profile(raw=line), {})
    assert not degree_issues(result), result


@pytest.mark.parametrize(("source", "claim"), [
    (profile(raw="Certified Scrum Master, 2019"), "Certified Scrum Master"),
    (profile(certifications=["Certified Scrum Master"]), "Certified Scrum Master, 2019"),
    (profile(raw="AWS Certified Solutions Architect"), "AWS Certified Solutions Architect"),
    (profile(certifications=["PMP"]), "Certification: PMP"),
    (profile(certifications=["AWS Solutions Architect"]), "Certified AWS Solutions Architect"),
], ids=["part-of-line", "fact-inside-claim", "keyword-mid-line", "listed-name", "listed-long-name"])
def test_a_stated_certification_passes(source, claim):
    assert not cert_issues(audit_provenance(f"{claim}\n", source, {}))


@pytest.mark.parametrize(("source", "claim"), [
    (profile(raw="Led it: 40% faster releases"), "40%"),
    (profile(raw="Cut churn by 1.5% in a year"), "1.5%"),
    (profile(raw="Served 1,000 users daily"), "1,000 users"),
    (profile(raw="Served 120 USERS"), "120 users"),
    (profile(raw="5+ years of experience"), "5+ years"),
    (profile(raw="Grew 30-50% each year"), "50%"),
    (profile(years="12"), "12 years"),
    (profile(years="12"), "12+ years"),
    (profile(years="12+"), "12+ years"),
    (profile(raw="Worked for 1 year abroad"), "1 year"),
], ids=["percent", "decimal", "thousands", "case", "plus", "range-end", "years-field", "years-field-plus", "years-field-both", "year"])
def test_a_stated_metric_passes(source, claim):
    assert not metric_issues(audit_provenance(f"Reached {claim} overall.", source, {}))
