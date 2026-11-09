"""LLM tailoring: what goes to the provider, and what is done with what comes back.

Offline. Only subprocess.run behind claude_code is replaced, so the budget gate, the prompt builder, the
structural checks and the fact gate below it are the real ones. Every path is under tmp_path.

A test marked xfail (strict) states a rule of DECISIONS.md or CLAUDE.md that the code does not meet yet. It
turns into a failure as soon as the code meets it, which is the moment to remove the mark.
"""

import json
import subprocess
from types import SimpleNamespace

import pytest

import ai_gate
import claude_code
import llm_tailor
import run_tailor
from conftest import permissive_ai_budget
from provenance_checker import build_canonical_facts, check_provenance
from resume_parser import parse_resume_from_profile

NAME = "Jovana Testić"
EMAIL = "jovana.canary@example.com"
PHONE = "+381 64 555 0199"
LINKEDIN = "linkedin.com/in/jovana-canary"
GITHUB = "github.com/jovana-canary"
SITE = "jovana-canary.example.org"
IDENTIFIERS = (NAME, EMAIL, PHONE, LINKEDIN, GITHUB, SITE)
# Fields tailoring has no reason to send. CLAUDE.md: "Do not widen what it sends".
SALARY = "9137 EUR canary"
QUESTIONNAIRE = "questionnaire-answer-canary"

COMPANY = "Acme Platforms"
OLD_COMPANY = "Borealis Systems"
BULLET = "Led the billing platform migration and reached 40% faster releases across the group."
OLD_BULLET = "Owned the partner onboarding flow from discovery to launch."
SUMMARY_TEXT = "Product leader with a long record of shipping billing platforms and partner tools."
RAW_CV = f"""{NAME}
Senior Product Manager
Niš, Serbia | {PHONE} | {EMAIL} | {LINKEDIN} | {GITHUB} | {SITE}

PROFESSIONAL SUMMARY
{SUMMARY_TEXT}

PROFESSIONAL EXPERIENCE
Senior Product Manager, {COMPANY} | Remote
May 2020 – Present
• {BULLET}
Product Manager, {OLD_COMPANY} | Niš
Jan 2016 – Apr 2020
• {OLD_BULLET}

SKILLS
Delivery: Jira, Roadmapping, SQL

EDUCATION
B.A. Economics, University of Niš, 2012
"""

JOB = {
    "jobId": "job-under-test",
    "title": "Lead Product Manager",
    "company": "Hiring Co",
    "location": "Remote",
    "description": "<p>Own the &amp; roadmap for {billing} products.</p>",
}

# Enough words for lint_cover_letter (250-500), no digit, no banned phrase.
FILLER = " ".join(["The work joined product discovery with careful delivery for the customers it served."] * 8)


def profile():
    return {
        "basicProfile": {
            "fullName": NAME, "email": EMAIL, "phone": PHONE, "location": "Niš, Serbia",
            "currentRole": "Senior Product Manager", "experienceYears": "12",
            "salaryExpectation": SALARY, "targetRoles": ["Lead Product Manager"],
        },
        "resume": {
            "rawText": RAW_CV,
            "parsedData": {
                "skills": ["Jira", "Roadmapping", "SQL"],
                "workExperience": [f"Senior Product Manager — {COMPANY} | May 2020–Present | Billing"],
                "education": ["B.A. Economics — University of Niš | 2012"],
                "links": [LINKEDIN, GITHUB, SITE],
            },
        },
        "repositories": {"githubLinks": [GITHUB], "localRepoPaths": []},
        "questionnaire": {"answers": [{"id": 1, "question": "q", "answer": QUESTIONNAIRE}]},
    }


def intelligence():
    return {
        "candidateSummary": {"candidateType": "product", "oneLinePitch": "Ships billing platforms."},
        "skillsMap": {"technicalSkills": ["SQL"], "productBusiness": ["Roadmapping"]},
        "experienceMap": {"projectHighlights": ["Billing platform migration"]},
        "atsKeywordBank": {"highPriority": ["roadmap"]},
        "jobFitPreferences": {"salaryExpectation": SALARY},
    }


def good_output(**overrides):
    """What a well-behaved model returns for profile(): reworded, with no fact the profile lacks."""
    return {
        "subtitle": "Lead Product Manager | Billing Platforms",
        "summary": "Product leader with a long record of shipping billing platforms and partner tools for customers.",
        "experience": [{"company": COMPANY, "bullets": [BULLET]}],
        "skills": [{"label": "Delivery", "skills": ["SQL", "Jira"]}],
        "projects": [],
        "cover_letter_paragraphs": [f"Opening. {FILLER}", f"Depth. {FILLER}", f"Breadth. {FILLER}", "Thank you."],
        **overrides,
    }


class Cli:
    """Stands in for `claude -p`: records every prompt, answers with `reply`."""

    def __init__(self):
        self.prompts = []
        self.reply = json.dumps(good_output())
        self.stdout = None  # the raw envelope, when a test wants a broken one
        self.raises = None

    def __call__(self, args, *rest, **kwargs):
        assert args[0] == "claude", args
        self.prompts.append(kwargs["input"])
        if self.raises:
            raise self.raises
        stdout = self.stdout if self.stdout is not None else json.dumps({"result": self.reply})
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    @property
    def prompt(self):
        assert len(self.prompts) == 1, f"expected one call, got {len(self.prompts)}"
        return self.prompts[0]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Everything tailoring reads or writes by default, moved to tmp_path. The PDF step needs a browser, so it is out."""
    monkeypatch.setattr(llm_tailor, "PROJECT_INTEL_PATH", tmp_path / "data" / "intelligence" / "project-intelligence.json")
    monkeypatch.setattr(run_tailor, "ROOT", tmp_path)
    monkeypatch.setattr(run_tailor, "RESUMES_ROOT", tmp_path / "data" / "resumes")
    monkeypatch.setattr(run_tailor, "render_single_page_pdf", lambda *a, **k: (False, -1))
    monkeypatch.setattr(claude_code, "_availability", {"available": True, "reason": ""})


@pytest.fixture
def cli(monkeypatch):
    fake = Cli()
    monkeypatch.setattr(claude_code.subprocess, "run", fake)
    return fake


@pytest.fixture
def allowed(cli, tmp_path, monkeypatch):
    """The gate lets the call through, and the CLI answers."""
    permissive_ai_budget(tmp_path, monkeypatch)
    return cli


def write_project_intel(tmp_path, data):
    path = llm_tailor.PROJECT_INTEL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def generate(parsed=None, intel=None, job=None, confirmed=True):
    """The owner has confirmed unless a test says otherwise."""
    return llm_tailor.generate_llm_content(
        parse_resume_from_profile(profile()) if parsed is None else parsed,
        intelligence() if intel is None else intel,
        JOB if job is None else job,
        confirmed=confirmed,
    )


def tailor(tmp_path, *, prof=None, intel=None):
    job = run_tailor.tailor_job(dict(JOB), prof or profile(), intel or intelligence(), use_llm=True, confirmed=True)
    assets = job["tailoredAssets"]
    folder = tmp_path / "data" / "resumes" / JOB["jobId"]
    written = {p.name: p.read_text(encoding="utf-8") for p in folder.iterdir() if p.suffix in (".md", ".html", ".json")}
    return assets, written


def ledger_calls(decision=None):
    rows = [r for r in ai_gate.read_ledger() if r["type"] == "call"]
    return [r for r in rows if decision is None or r["decision"] == decision]


# --- what the prompt contains --------------------------------------------------------------------


def test_the_prompt_carries_the_job_and_the_candidates_work(allowed):
    generate()
    prompt = allowed.prompt
    for text in (JOB["title"], JOB["company"], BULLET, OLD_BULLET, SUMMARY_TEXT, COMPANY, "Ships billing platforms."):
        assert text in prompt


def test_the_ad_is_stripped_of_html_cut_to_length_and_its_braces_are_harmless(allowed):
    long_ad = "<p>Own the &amp; roadmap for {billing} products.</p>" + "x" * 6000 + "END-OF-AD"
    data, err = generate(job={**JOB, "description": long_ad})
    assert err == "" and data
    assert "Own the & roadmap" in allowed.prompt
    assert "<p>" not in allowed.prompt
    assert "{billing}" in allowed.prompt
    assert "END-OF-AD" not in allowed.prompt


@pytest.mark.parametrize("identifier", IDENTIFIERS)
def test_contact_details_in_the_profile_and_the_cv_header_stay_out_of_the_prompt(allowed, identifier):
    generate()
    assert identifier.lower() not in allowed.prompt.lower()
    assert identifier.split()[-1].lower() not in allowed.prompt.lower()


def test_the_prompt_is_not_widened_to_salary_questionnaire_or_raw_cv(allowed):
    generate()
    assert SALARY not in allowed.prompt
    assert QUESTIONNAIRE not in allowed.prompt
    assert "Niš, Serbia |" not in allowed.prompt  # the CV header line


def _in_about_me(parsed, intel, project, text):
    parsed["about_me"] = f"{parsed['about_me']} {text}"


def _in_a_bullet(parsed, intel, project, text):
    parsed["experience"][0]["bullets"].append(text)


def _in_a_skill(parsed, intel, project, text):
    parsed["skill_categories"].append({"label": "Links", "skills": [text]})


def _in_education(parsed, intel, project, text):
    parsed["education"] = {**parsed["education"], "school": text}


def _in_the_pitch(parsed, intel, project, text):
    intel["candidateSummary"]["oneLinePitch"] = text


def _in_a_highlight(parsed, intel, project, text):
    intel["experienceMap"]["projectHighlights"].append(text)


def _in_project_intel(parsed, intel, project, text):
    project["projects"][0]["highlights"] = [text]


@pytest.mark.parametrize("identifier", IDENTIFIERS)
@pytest.mark.parametrize("place", [_in_about_me, _in_a_bullet, _in_a_skill, _in_education, _in_the_pitch,
                                   _in_a_highlight, _in_project_intel], ids=lambda f: f.__name__)
def test_an_identifier_inside_a_sent_section_is_redacted(allowed, tmp_path, place, identifier):
    parsed, intel, project = parse_resume_from_profile(profile()), intelligence(), {"projects": [{"name": "P"}]}
    place(parsed, intel, project, f"Contact {identifier} for details.")
    write_project_intel(tmp_path, project)
    generate(parsed, intel)
    assert identifier not in allowed.prompt


def test_a_cv_summary_that_names_its_owner_is_redacted_end_to_end(allowed):
    prof = profile()
    prof["resume"]["rawText"] = RAW_CV.replace(SUMMARY_TEXT, f"{NAME} is a product leader. Write to {EMAIL}.")
    generate(parse_resume_from_profile(prof))
    assert NAME not in allowed.prompt and EMAIL not in allowed.prompt


def test_a_draft_that_copies_a_redaction_placeholder_is_rejected(allowed):
    allowed.reply = json.dumps(good_output(summary="Product leader, reach [NAME] at [EMAIL] for billing platforms and partner tools."))
    data, err = generate()
    assert data is None and "placeholder" in err


def test_nothing_is_sent_when_redaction_leaves_something_of_the_candidate(allowed, monkeypatch):
    monkeypatch.setattr(llm_tailor.redact, "redact_cv_text", lambda text, *a, **k: (text, {}))
    parsed = parse_resume_from_profile(profile())
    _in_about_me(parsed, None, None, f"Write to {EMAIL}.")
    data, err = generate(parsed)
    assert data is None and "nothing was sent" in err
    assert allowed.prompts == []


def test_a_provider_error_that_echoes_a_contact_detail_is_masked_everywhere(allowed):
    allowed.stdout = json.dumps({"is_error": True, "result": f"Cannot process {EMAIL} or {PHONE} at {LINKEDIN}"})
    data, err = generate()
    assert data is None and "Cannot process" in err
    for identifier in (EMAIL, PHONE, LINKEDIN):
        assert identifier not in err
    assert all(identifier not in json.dumps(row) for row in ai_gate.read_ledger() for identifier in (EMAIL, PHONE, LINKEDIN))


def test_an_unparseable_provider_output_is_masked_and_cut(allowed):
    allowed.stdout = f"not json {EMAIL} " + "x" * 500
    data, err = generate()
    assert data is None and EMAIL not in err and len(err) < 260


def test_the_project_scan_tools_cannot_read_commit_authors():
    joined = " ".join(claude_code.READONLY_TOOLS)
    assert "git log" not in joined and "git shortlog" not in joined


def test_nothing_is_sent_without_an_explicit_confirm(allowed):
    data, err = generate(confirmed=False)
    assert data is None and "not confirmed" in err
    assert allowed.prompts == []
    assert ledger_calls() == []


def test_a_run_without_confirm_sends_nothing_and_says_so(allowed, tmp_path, monkeypatch, capsys):
    code, doc, out = _run_main(tmp_path, monkeypatch, capsys, extra=())
    assert code == 0 and allowed.prompts == []
    assets = doc["jobs"][0]["tailoredAssets"]
    assert assets["contentEngine"] == "rule-based" and "not confirmed" in assets["llmIssues"][0]
    assert "Not confirmed" in out


def test_the_preview_shows_the_exact_redacted_prompt_and_calls_no_model(allowed, tmp_path, monkeypatch, capsys):
    code, _, out = _run_main(tmp_path, monkeypatch, capsys, extra=("--preview",))
    assert code == 0 and allowed.prompts == []
    shown = json.loads(out.strip().splitlines()[-1])
    [item] = shown["jobs"]
    assert item["jobId"] == JOB["jobId"] and item["gate"]["allowed"] is True
    assert BULLET in item["prompt"] and item["characters"] == len(item["prompt"])
    for identifier in IDENTIFIERS:
        assert identifier not in item["prompt"]
    assert ledger_calls() == []


def test_the_preview_reports_a_refusal_by_the_gate_and_by_redaction(cli, tmp_path, monkeypatch, capsys):
    _, _, out = _run_main(tmp_path, monkeypatch, capsys, extra=("--preview",))
    [item] = json.loads(out.strip().splitlines()[-1])["jobs"]
    assert item["gate"]["allowed"] is False and "budget" in item["gate"]["reason"].lower()
    assert cli.prompts == []


# --- the fact gate: what it does reject today ----------------------------------------------------


def _invent_in_summary(metric):
    return good_output(summary=f"Product leader with a long record of shipping billing platforms, reaching {metric} overall.")


def _invent_in_bullet(metric):
    return good_output(experience=[{"company": COMPANY, "bullets": [f"Reached {metric} on the billing platform."]}])


def _invent_in_letter(metric):
    paragraphs = good_output()["cover_letter_paragraphs"]
    paragraphs[0] = f"I reached {metric} at my last company. {FILLER}"
    return good_output(cover_letter_paragraphs=paragraphs)


@pytest.mark.parametrize("build", [_invent_in_summary, _invent_in_bullet, _invent_in_letter], ids=lambda f: f.__name__)
@pytest.mark.parametrize("metric", ["73% growth", "9000 users", "870 customers"])
def test_an_invented_metric_is_rejected_and_never_written(allowed, tmp_path, build, metric):
    allowed.reply = json.dumps(build(metric))
    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any("rejected" in issue and metric.split()[0] in issue for issue in assets["llmIssues"])
    for name, text in written.items():
        assert metric not in text, name


def test_a_metric_the_cv_states_is_accepted_and_the_draft_is_used(allowed, tmp_path):
    allowed.reply = json.dumps(good_output())
    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "claude-code", assets["llmIssues"]
    assert assets["llmIssues"] == []
    assert "Lead Product Manager | Billing Platforms" in written["tailored_resume.md"]
    assert "40% faster releases" in written["tailored_resume.md"]


def test_an_employer_the_cv_does_not_list_is_rejected_by_structure(allowed):
    allowed.reply = json.dumps(good_output(experience=[{"company": "Google", "bullets": ["Ran search."]}]))
    data, err = generate()
    assert data is None and "unknown company in experience: Google" in err


def test_a_skill_the_candidate_does_not_have_is_dropped(allowed, tmp_path):
    allowed.reply = json.dumps(good_output(skills=[{"label": "Delivery", "skills": ["SQL", "Kubernetes"]}]))
    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "claude-code"
    assert "SQL" in written["tailored_resume.md"]
    assert "Kubernetes" not in written["tailored_resume.md"]


def test_a_project_not_in_project_intelligence_is_dropped(allowed, tmp_path):
    write_project_intel(tmp_path, {"projects": [{"name": "Real Project"}]})
    allowed.reply = json.dumps(good_output(projects=[{"name": "Real Project", "line": "Real line."},
                                                     {"name": "Invented Project", "line": "Invented line."}]))
    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "claude-code"
    assert "Real Project" in written["tailored_resume.md"]
    assert "Invented Project" not in written["tailored_resume.md"]


def test_a_banned_phrase_rejects_the_draft(allowed, tmp_path):
    allowed.reply = json.dumps(good_output(summary="A passionate product leader with a long record of shipping billing platforms and partner tools."))
    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any("passionate" in issue for issue in assets["llmIssues"])
    assert "passionate" not in written["tailored_resume.md"].lower()


def test_dynamic_is_a_banned_phrase_the_code_enforces(allowed, tmp_path):
    allowed.reply = json.dumps(good_output(summary="A dynamic product leader with a long record of shipping billing platforms and partner tools."))
    assets, _ = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any("dynamic" in issue for issue in assets["llmIssues"])


def test_a_letter_of_the_wrong_length_rejects_the_draft(allowed, tmp_path):
    allowed.reply = json.dumps(good_output(cover_letter_paragraphs=["Short.", "Short.", "Short.", "Short."]))
    assets, _ = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any("Word count" in issue for issue in assets["llmIssues"])


# --- the fact gate: what principle 8 asks and it does not reject ---------------------------------

@pytest.mark.parametrize("claim", [
    "Managed a team of 47 engineers.",
    "Grew revenue to $8 billion in one year.",
    "Raised €5 million from investors.",
    "Holds a PhD from Stanford University.",
    "Worked with the leadership of Google and Netflix.",
    "Built the platform on Kubernetes and Terraform.",
], ids=["headcount", "dollars", "euro-million", "degree", "employer-in-prose", "technology-in-prose"])
def test_an_invented_claim_of_any_shape_is_rejected(allowed, tmp_path, claim):
    allowed.reply = json.dumps(good_output(experience=[{"company": COMPANY, "bullets": [claim]}]))
    assets, written = tailor(tmp_path)
    assert claim not in written["tailored_resume.md"]
    assert assets["contentEngine"] == "rule-based"


# --- the fact gate: a metric is matched as a whole token -------------------------------------------


@pytest.mark.parametrize(("change", "metric"), [
    (lambda p, i: p["basicProfile"].update(experienceYears="5"), "500%"),
    (lambda p, i: p["basicProfile"].update(experienceYears="12"), "12000 users"),
    (lambda p, i: p["basicProfile"].update(experienceYears="12"), "12%"),
    (lambda p, i: p["basicProfile"].update(experienceYears="12"), "12 users"),
    (lambda p, i: p["resume"]["parsedData"]["skills"].append("R"), "870 users"),
    (lambda p, i: p["resume"]["parsedData"]["skills"].append("C"), "870 customers"),
    (lambda p, i: i["experienceMap"]["projectHighlights"].append(""), "99%"),
], ids=["years-5", "years-12", "years-same-number-percent", "years-same-number-users", "skill-R", "skill-C", "empty-highlight"])
def test_a_short_fact_does_not_vouch_for_an_invented_metric(change, metric):
    prof, intel = profile(), intelligence()
    change(prof, intel)
    passed, issues = check_provenance(f"Reached {metric} on the platform.", build_canonical_facts(prof, intel))
    assert passed is False, issues


def test_a_metric_is_not_accepted_because_a_longer_number_contains_it():
    facts = build_canonical_facts({"resume": {"rawText": "Grew revenue by 150% in two years", "parsedData": {}}}, {})
    passed, _ = check_provenance("Grew revenue by 50%.", facts)
    assert passed is False


def _facts_from_cv(line):
    return build_canonical_facts({"resume": {"rawText": line, "parsedData": {}}}, {})


@pytest.mark.parametrize(("source", "claim"), [
    ("Cut churn by 1.5% in a year", "1.50%"),
    ("Cut churn by 1.5% in a year", "5%"),
    ("Served 1,500 users", "500 users"),
    ("Served 1,000 users", "2,000 users"),
    ("Served 112 users", "12 users"),
    ("Answered in 10ms flat", "10m"),
    ("Saved 12k a year", "2k"),
], ids=["longer-decimal", "tail-of-decimal", "tail-of-thousands", "other-thousands", "tail-of-integer", "ms-is-not-m", "tail-of-k"])
def test_an_invented_metric_inside_a_real_number_is_rejected(source, claim):
    passed, issues = check_provenance(f"Reached {claim} overall.", _facts_from_cv(source))
    assert passed is False, issues
    assert claim in issues[0]


@pytest.mark.parametrize(("source", "claim"), [
    ("Led a migration: 40% faster releases.", "Reached 40% faster."),
    ("Cut churn by 1.5% in a year", "Cut churn by 1.5%."),
    ("Cut churn by 5,5% in a year", "Cut churn by 5,5%."),
    ("Served 1,000 users daily", "Served 1,000 users."),
    ("Served 10k daily users", "Served 10k people."),
    ("Budget of $2.5m per year", "Ran $2.5m."),
    ("Revenue of EUR40k a month", "Brought 40k."),
    ("Grew 30-50% each year", "Grew 50%."),
    ("(40%) and more", "Reached 40%."),
    ("Grew by 40%of the base", "Grew 40%."),
    ("Bought 5 Xbox consoles", "Bought 5 Xbox."),
    ("Served 120 USERS", "Served 120 users."),
], ids=["percent", "decimal", "decimal-comma", "thousands", "k", "money-m", "currency-glued", "range-end", "in-brackets",
        "percent-glued-word", "unit-whole-word", "case"])
def test_a_metric_the_source_states_still_passes(source, claim):
    passed, issues = check_provenance(claim, _facts_from_cv(source))
    assert passed is True, issues


def test_blank_facts_are_not_kept():
    facts = build_canonical_facts(
        {"resume": {"parsedData": {}}},
        {"experienceMap": {"projectHighlights": ["", "  "]}, "skillsMap": {"technicalSkills": [" ", 0, "SQL"]}},
    )
    assert facts == {"sql"}


# --- empty and invalid provider output -----------------------------------------------------------


@pytest.mark.parametrize(("reply", "expected"), [
    ("", "No JSON object"),
    ("I cannot help with that.", "No JSON object"),
    ('{"subtitle": "broken', "No JSON object"),
    ("{}", "missing subtitle"),
    (json.dumps(good_output(subtitle="  ")), "missing subtitle"),
    (json.dumps(good_output(subtitle=7)), "missing subtitle"),
    (json.dumps(good_output(summary="Too short.")), "missing/short summary"),
    (json.dumps(good_output(summary=None)), "missing/short summary"),
    (json.dumps(good_output(cover_letter_paragraphs=["One", "Two", "Three"])), "exactly 4"),
    (json.dumps(good_output(cover_letter_paragraphs=["One", "Two", "Three", " "])), "exactly 4"),
    (json.dumps(good_output(cover_letter_paragraphs="Four paragraphs")), "exactly 4"),
    (json.dumps(good_output(experience=[{"company": COMPANY, "bullets": []}])), "empty bullets"),
], ids=["empty", "prose", "cut-json", "empty-object", "blank-subtitle", "number-subtitle", "short-summary", "null-summary",
        "three-paragraphs", "blank-paragraph", "letter-as-string", "no-bullets"])
def test_invalid_output_returns_its_reason_and_tailoring_falls_back(allowed, tmp_path, reply, expected):
    allowed.reply = reply
    data, err = generate()
    assert data is None and expected in err

    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any(expected in issue for issue in assets["llmIssues"])
    assert SUMMARY_TEXT in written["tailored_resume.md"]  # the candidate's own text, unchanged


def test_json_in_a_code_fence_is_read(allowed):
    allowed.reply = f"Here it is:\n```json\n{json.dumps(good_output())}\n```"
    data, err = generate()
    assert err == "" and data["subtitle"] == good_output()["subtitle"]


@pytest.mark.parametrize(("stdout", "expected"), [
    ("not json at all", "Unparseable Claude Code output"),
    (json.dumps({"is_error": True, "result": "Credit balance is too low"}), "Credit balance is too low"),
    (json.dumps({"is_error": True}), "Claude Code error"),
    ("", "No JSON object"),
], ids=["garbage", "cli-error", "cli-error-no-text", "no-stdout"])
def test_a_failed_cli_run_returns_its_reason(allowed, tmp_path, stdout, expected):
    allowed.stdout = stdout
    data, err = generate()
    assert data is None and expected in err


@pytest.mark.parametrize(("error", "expected"), [
    (subprocess.TimeoutExpired("claude", 300), "timed out after 300s"),
    (OSError("no such file"), "no such file"),
], ids=["timeout", "os-error"])
def test_a_cli_that_cannot_run_falls_back(allowed, tmp_path, error, expected):
    allowed.raises = error
    assets, _ = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any(expected in issue for issue in assets["llmIssues"])


def test_a_missing_cli_sends_nothing_and_says_why(cli, tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch)
    monkeypatch.setattr(claude_code, "_availability", {"available": False, "reason": "claude CLI not installed"})
    data, err = generate()
    assert data is None and err == "claude CLI not installed"
    assert cli.prompts == []
    assert ledger_calls() == []


BAD_SHAPES = {
    "experience-string": {"experience": "none"},
    "experience-number": {"experience": 3},
    "experience-of-strings": {"experience": ["Acme"]},
    "skills-string": {"skills": "SQL"},
    "skills-of-strings": {"skills": ["SQL"]},
    "skill-items-numbers": {"skills": [{"label": "Delivery", "skills": [1]}]},
    "skill-label-number": {"skills": [{"label": 5, "skills": ["SQL"]}]},
    "projects-string": {"projects": "none"},
    "projects-of-strings": {"projects": ["P"]},
    "project-name-number": {"projects": [{"name": 5, "line": "x"}]},
}


@pytest.mark.parametrize("case", list(BAD_SHAPES))
def test_a_draft_with_the_wrong_inner_shape_falls_back_instead_of_crashing(allowed, tmp_path, case):
    allowed.reply = json.dumps(good_output(**BAD_SHAPES[case]))
    assets, _ = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert assets["llmIssues"]


@pytest.mark.parametrize(("change", "expected"), [
    ({"experience": [{"company": 5, "bullets": ["x"]}]}, "unknown company in experience: 5"),
    ({"experience": [{"company": COMPANY, "bullets": [1, 2]}]}, "must be text"),
    ({"skills": [{"label": "Delivery", "skills": "SQL"}]}, "skills items must be a list"),
    ({"projects": [{"name": "P", "line": 7}]}, "project name and line must be text"),
], ids=["company-number", "bullet-numbers", "skill-items-string", "project-line-number"])
def test_more_wrong_shapes_fall_back_with_their_reason(allowed, tmp_path, change, expected):
    allowed.reply = json.dumps(good_output(**change))
    assets, _ = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any(expected in issue for issue in assets["llmIssues"])


def test_a_shape_the_checks_did_not_foresee_still_costs_only_the_draft(allowed, tmp_path, monkeypatch):
    def unforeseen(*_):
        raise TypeError("unforeseen shape")
    monkeypatch.setattr(run_tailor, "_apply_llm_content", unforeseen)
    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    assert any("malformed draft" in issue and "unforeseen shape" in issue for issue in assets["llmIssues"])
    assert SUMMARY_TEXT in written["tailored_resume.md"]


def test_null_or_absent_optional_sections_are_still_a_valid_draft(allowed, tmp_path):
    draft = good_output(skills=None, projects=None)
    del draft["experience"]
    allowed.reply = json.dumps(draft)
    assets, _ = tailor(tmp_path)
    assert assets["contentEngine"] == "claude-code", assets["llmIssues"]


def test_a_malformed_draft_does_not_stop_a_bulk_run_or_lose_other_jobs(allowed, tmp_path, monkeypatch, capsys):
    prof, intel, scored = tmp_path / "p.json", tmp_path / "i.json", tmp_path / "s.json"
    prof.write_text(json.dumps(profile()), encoding="utf-8")
    intel.write_text(json.dumps(intelligence()), encoding="utf-8")
    jobs = [{**JOB, "jobId": f"job-{n}"} for n in (1, 2, 3)]
    scored.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    replies = iter([json.dumps(good_output()), json.dumps(good_output(skills="SQL")), json.dumps(good_output())])
    real_call = allowed.__call__

    def answer(args, *rest, **kwargs):
        allowed.reply = next(replies)
        return real_call(args, *rest, **kwargs)

    monkeypatch.setattr(claude_code.subprocess, "run", answer)
    monkeypatch.setattr("sys.argv", ["run_tailor.py", "--job-ids", "job-1,job-2,job-3", "--profile", str(prof),
                                     "--intelligence", str(intel), "--scored", str(scored), "--confirm"])
    assert run_tailor.main() == 0
    saved = {j["jobId"]: j["tailoredAssets"] for j in json.loads(scored.read_text(encoding="utf-8"))["jobs"]}
    assert {k: v["contentEngine"] for k, v in saved.items()} == {
        "job-1": "claude-code", "job-2": "rule-based", "job-3": "claude-code"}
    assert any("skills must be a list" in issue for issue in saved["job-2"]["llmIssues"])


def test_bullets_given_as_a_string_are_not_written_one_letter_per_line(allowed, tmp_path):
    allowed.reply = json.dumps(good_output(experience=[{"company": COMPANY, "bullets": "One long line"}]))
    assets, written = tailor(tmp_path)
    assert "- O\n" not in written["tailored_resume.md"]
    assert assets["contentEngine"] == "rule-based"
    assert any("must be a list" in issue for issue in assets["llmIssues"])


@pytest.mark.parametrize("bullets", [5, {"a": "b"}, True], ids=["number", "object", "boolean"])
def test_bullets_of_any_other_non_list_shape_are_rejected_with_the_reason(allowed, bullets):
    allowed.reply = json.dumps(good_output(experience=[{"company": COMPANY, "bullets": bullets}]))
    data, err = generate()
    assert data is None and "must be a list" in err


# --- the budget gate -----------------------------------------------------------------------------


def test_a_refusal_at_budget_0_returns_the_gates_reason_and_nothing_is_sent(cli):
    data, err = generate()
    assert data is None and "AI budget is 0" in err
    assert cli.prompts == []


def test_a_refusal_is_in_the_ledger_with_feature_and_job(cli):
    generate()
    [row] = ledger_calls("refused")
    assert row["feature"] == "tailoring" and row["jobId"] == JOB["jobId"] and row["provider"] == "claude-code"


def test_a_refusal_is_recorded_on_the_job_and_rule_based_documents_are_still_made(cli, tmp_path):
    assets, written = tailor(tmp_path)
    assert assets["contentEngine"] == "rule-based"
    [issue] = assets["llmIssues"]
    assert issue.startswith("llm skipped:") and "AI budget is 0" in issue
    assert cli.prompts == []
    assert SUMMARY_TEXT in written["tailored_resume.md"]


def test_the_subscription_switch_does_not_open_tailoring(cli, tmp_path):
    ai = tmp_path / "ai"
    ai.mkdir(parents=True, exist_ok=True)
    (ai / "settings.json").write_text(json.dumps(
        {"claudeCodeSubscription": {"enabled": True, "maxCallsDaily": 5, "features": ["jobAnalysis"]}}))
    data, err = generate()
    assert data is None and err
    assert cli.prompts == []


def test_an_allowed_call_is_in_the_ledger_with_feature_and_job(allowed):
    generate()
    [row] = ledger_calls("allowed")
    assert row["feature"] == "tailoring" and row["jobId"] == JOB["jobId"]


def _run_main(tmp_path, monkeypatch, capsys, extra=("--confirm",)):
    prof, intel, scored = tmp_path / "p.json", tmp_path / "i.json", tmp_path / "s.json"
    prof.write_text(json.dumps(profile()), encoding="utf-8")
    intel.write_text(json.dumps(intelligence()), encoding="utf-8")
    scored.write_text(json.dumps({"jobs": [JOB]}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["run_tailor.py", "--job-id", JOB["jobId"], "--profile", str(prof),
                                     "--intelligence", str(intel), "--scored", str(scored), *extra])
    code = run_tailor.main()
    return code, json.loads(scored.read_text(encoding="utf-8")), capsys.readouterr().out


def test_a_full_run_refused_by_the_gate_keeps_the_reason_in_the_scored_file(cli, tmp_path, monkeypatch, capsys):
    code, doc, _ = _run_main(tmp_path, monkeypatch, capsys)
    assert code == 0
    assets = doc["jobs"][0]["tailoredAssets"]
    assert assets["contentEngine"] == "rule-based"
    assert "AI budget is 0" in assets["llmIssues"][0]


def test_a_refusal_reason_reaches_the_output_of_the_run(cli, tmp_path, monkeypatch, capsys):
    _, _, out = _run_main(tmp_path, monkeypatch, capsys)
    assert "AI budget is 0" in out


def test_a_rejection_reason_reaches_the_output_of_the_run(allowed, tmp_path, monkeypatch, capsys):
    allowed.reply = json.dumps(_invent_in_summary("73% growth"))
    _, _, out = _run_main(tmp_path, monkeypatch, capsys)
    assert "73%" in out


# --- project intelligence, and where things are written ------------------------------------------


def test_no_project_intelligence_file_sends_none_available(allowed):
    generate()
    assert "none available" in allowed.prompt


def test_a_corrupt_project_intelligence_file_sends_none_available(allowed):
    path = llm_tailor.PROJECT_INTEL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    generate()
    assert "none available" in allowed.prompt


def test_only_the_named_project_fields_are_sent(allowed, tmp_path):
    write_project_intel(tmp_path, {"aggregate": {"techStack": ["SQL"]},
                                   "projects": [{"name": "P1", "summary": "S1", "localPath": "/home/canary/repo",
                                                 "remoteUrl": "https://github.com/canary/repo"}]})
    generate()
    assert "P1" in allowed.prompt and "S1" in allowed.prompt
    assert "canary" not in allowed.prompt


def test_every_file_goes_under_the_given_root(allowed, tmp_path):
    from pathlib import Path

    real_resumes = Path(__file__).resolve().parents[2] / "data" / "resumes" / JOB["jobId"]
    job = run_tailor.tailor_job(dict(JOB), profile(), intelligence(), use_llm=True, confirmed=True)
    assert not real_resumes.exists()
    for key in ("resumeMd", "resumeHtml", "resumeJson", "coverLetterMd"):
        assert (tmp_path / job["tailoredAssets"][key]).is_file(), key


# --- the verdict the application store reads, and the records tailoring must never touch ---------------


def _verdict_status(tmp_path, name):
    import verdicts

    return verdicts.status(tmp_path / "data" / "resumes" / JOB["jobId"], name)


DOCUMENTS = ("tailored_resume.md", "tailored_resume.html", "cover_letter.md")


def test_every_document_of_a_run_gets_a_passing_verdict_bound_to_its_hash(allowed, tmp_path):
    assets, _ = tailor(tmp_path)
    assert assets["provenancePassed"] is True
    for name in DOCUMENTS:
        assert _verdict_status(tmp_path, name) == "verified", name
    folder = tmp_path / "data" / "resumes" / JOB["jobId"]
    sidecar = folder / ".tailored_resume.md.verdict.json"
    assert sidecar.stat().st_mode & 0o777 == 0o600
    body = json.loads(sidecar.read_text(encoding="utf-8"))
    assert body["passed"] is True and body["issues"] == [] and len(body["sha256"]) == 64


def test_a_document_that_fails_the_final_check_gets_a_failing_verdict_and_the_reasons(allowed, tmp_path, monkeypatch):
    monkeypatch.setattr(run_tailor, "check_document", lambda text, facts: ["Unverified number: 9"])
    assets, _ = tailor(tmp_path)
    assert assets["provenancePassed"] is False and assets["provenanceIssues"] == ["Unverified number: 9"]
    for name in DOCUMENTS:
        assert _verdict_status(tmp_path, name) == "failed", name
    body = json.loads((tmp_path / "data" / "resumes" / JOB["jobId"] / ".cover_letter.md.verdict.json").read_text(encoding="utf-8"))
    assert body["issues"] == ["Unverified number: 9"]


def test_a_document_changed_after_the_run_no_longer_matches_its_verdict(allowed, tmp_path):
    tailor(tmp_path)
    (tmp_path / "data" / "resumes" / JOB["jobId"] / "cover_letter.md").write_text("edited afterwards", encoding="utf-8")
    assert _verdict_status(tmp_path, "cover_letter.md") == "changed"
    assert _verdict_status(tmp_path, "tailored_resume.md") == "verified"


def test_a_rerun_replaces_the_verdicts_with_the_new_documents_hashes(allowed, tmp_path):
    tailor(tmp_path)
    allowed.reply = json.dumps(good_output(subtitle="Lead Product Manager | Billing"))
    tailor(tmp_path)
    for name in DOCUMENTS:
        assert _verdict_status(tmp_path, name) == "verified", name


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _make_application_records(tmp_path):
    base = tmp_path / "data" / "applications"
    (base / "files" / "app-1").mkdir(parents=True)
    (base / "applications.json").write_text(json.dumps({"applications": {"app-1": {"events": [{"type": "application_voided"}]}}}))
    (base / "files" / "app-1" / "Resume.pdf").write_bytes(b"%PDF frozen copy")
    (base / "settings.json").write_text("{}")
    return base


@pytest.mark.parametrize("reply", ["good", "invented", "garbage"])
def test_tailoring_never_touches_the_application_records(allowed, tmp_path, reply):
    base = _make_application_records(tmp_path)
    before = _snapshot(base)
    allowed.reply = {"good": json.dumps(good_output()), "invented": json.dumps(_invent_in_summary("73% growth")), "garbage": "not json"}[reply]
    tailor(tmp_path)
    tailor(tmp_path)
    assert _snapshot(base) == before


def test_a_run_without_confirm_and_a_preview_never_touch_the_application_records(allowed, tmp_path, monkeypatch, capsys):
    base = _make_application_records(tmp_path)
    before = _snapshot(base)
    _run_main(tmp_path, monkeypatch, capsys, extra=())
    _run_main(tmp_path, monkeypatch, capsys, extra=("--preview",))
    assert _snapshot(base) == before


def test_no_phase_4_module_writes_under_the_application_store():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    guarded = [
        "python/resume_generator/verdicts.py", "python/resume_generator/accept_cover_letter.py", "python/resume_generator/llm_tailor.py",
        "python/resume_generator/provenance_checker.py", "python/resume_generator/run_tailor.py", "python/llm/claude_code.py",
        "scripts/ai-draft-accept.js", "scripts/document-verdicts.js", "scripts/run-tailor.js", "scripts/inspect-document-verdicts.py",
    ]
    for rel in guarded:
        assert "applications" not in (root / rel).read_text(encoding="utf-8").lower().replace("application store", "").replace("an application", "").replace("applications.", ""), rel
