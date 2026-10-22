"""The CV parser reads structure, not one person's CV.

Every CV here is invented. They differ on purpose: flat PDF text against real
line breaks, different heading words, three entry layouts, accented names. A
parser tuned to a single CV would pass one of them at most.
"""

import pytest

from resume_parser import (
    DATE_RANGE_RE,
    normalize_link,
    parse_header,
    parse_resume_from_profile,
    parse_role_entry,
    parse_skill_rows,
    split_sections,
)

# PDF text as it really arrives: one line, headings in capitals, bullets as "•".
FLAT = (
    "ANA KOVAC SENIOR DATA ENGINEER FOR FINTECH TEAMS CONTACT Zagreb, Croatia +385 91 234 5678 | "
    "ana@example.com linkedin.com/in/anakovac | anakovac.dev "
    "CAREER PROFILE Data engineer with eight years building pipelines for payment platforms. "
    "WORK HISTORY "
    "Data Engineer, Northwind Payments | Remote March 2022 – Present | (European payments processor) "
    "Rebuilt the settlement pipeline and cut the nightly run from six hours to ninety minutes . "
    "Key Outcomes & Leadership "
    "• Introduced data contracts between the ledger and analytics teams to stop schema drift. "
    "• Mentored four engineers through their first production on-call rotations and reviews. "
    "Analyst, Contoso Retail | Zagreb, Croatia June 2018 – February 2022 | (Retail chain) "
    "Built weekly sales dashboards used by regional managers across forty stores. "
    "• Automated the stock reconciliation that took two analysts a full day each week. "
    "Junior Developer 2015 – 2018 | Fabrikam Labs Wrote internal tooling for the support team "
    "and maintained the release scripts for the whole department. "
    "TECHNICAL SKILLS Languages: Python, SQL, R (base) Data Tools: Airflow, dbt, Kafka (Confluent, Connect) "
    "ACADEMIC BACKGROUND University of Zagreb M.Sc. Computer Science | 2015"
)

ROLES = [
    "Data Engineer — Northwind Payments | Mar 2022–Present | Pipelines",
    "Analyst — Contoso Retail | Jun 2018–Feb 2022 | Dashboards",
    "Junior Developer — Fabrikam Labs | 2015–2018 | Tooling",
]

MULTILINE = """Ana Kovač
Senior Data Engineer
Zagreb, Croatia | ana@example.com | +385 91 234 5678

Summary
Data engineer with eight years building pipelines for payment platforms.

Work Experience
Data Engineer, Northwind Payments
March 2022 – Present
• Rebuilt the settlement pipeline and cut the nightly run from six hours to ninety minutes.
• Mentored four engineers through their first production on-call rotations.

Skills & Tools
Languages: Python, SQL
Tools: Airflow, dbt

Education
University of Zagreb, M.Sc. Computer Science, 2015
"""


def profile(raw, roles=None, **basic):
    return {
        "basicProfile": {"fullName": "Ana Kovač", **basic},
        "resume": {"rawText": raw, "parsedData": {"workExperience": roles or [], "education": [], "links": []}},
    }


# --- sections -----------------------------------------------------------------------------------


def test_headings_are_found_by_the_words_they_contain():
    header, sections = split_sections(FLAT)
    assert set(sections) == {"summary", "experience", "skills", "education"}
    assert header.startswith("ANA KOVAC")
    assert sections["summary"].strip().startswith("Data engineer with eight years")
    assert "Contoso Retail" in sections["experience"]
    assert sections["skills"].strip().startswith("Languages: Python")


@pytest.mark.parametrize(
    "heading,kind",
    [
        ("PROFESSIONAL SUMMARY", "summary"), ("ABOUT ME", "summary"), ("CAREER PROFILE", "summary"),
        ("PROFESSIONAL EXPERIENCE", "experience"), ("WORK HISTORY", "experience"), ("EMPLOYMENT", "experience"),
        ("SKILLS AND OTHERS", "skills"), ("CORE COMPETENCIES", "skills"), ("TOOLS", "skills"),
        ("EDUCATION & CERTIFICATIONS", "education"), ("ACADEMIC BACKGROUND", "education"),
    ],
)
def test_each_synonym_opens_the_right_section(heading, kind):
    _, sections = split_sections(f"JANE ROE contact details {heading} the body text of the section ")
    assert kind in sections and "body text" in sections[kind]


def test_unused_headings_still_end_the_section_before_them():
    _, sections = split_sections("NAME X WORK HISTORY job text here. CERTIFICATIONS some certificate EDUCATION a school")
    assert "certificate" not in sections["experience"]
    assert sections["education"].strip() == "a school"


def test_line_based_title_case_headings():
    header, sections = split_sections(MULTILINE)
    assert set(sections) == {"summary", "experience", "skills", "education"}
    assert "Zagreb, Croatia" in header and "Data Engineer, Northwind" in sections["experience"]


def test_text_without_headings_is_all_header():
    header, sections = split_sections("just some words with no heading at all")
    assert sections == {} and header.startswith("just")


# --- header -------------------------------------------------------------------------------------


def test_flat_header_is_read_by_pattern():
    header, _ = split_sections(FLAT)
    info = parse_header(header, "Ana Kovač")
    assert info["name"] == "ANA KOVAC"
    assert info["headline"] == "Senior Data Engineer for Fintech Teams"
    assert info["location"] == "Zagreb, Croatia"
    assert info["phone"] == "+385 91 234 5678"
    assert info["email"] == "ana@example.com"
    assert info["links"] == ["linkedin.com/in/anakovac", "anakovac.dev"]


def test_multiline_header_without_a_profile_name_uses_the_first_line():
    header, _ = split_sections(MULTILINE)
    info = parse_header(header)
    assert info["name"] == "Ana Kovač"
    assert info["location"] == "Zagreb, Croatia" and info["email"] == "ana@example.com"


def test_a_name_with_a_diacritic_matches_its_plain_spelling():
    assert parse_header("ANA KOVAC engineer", "Ana Kovač")["name"] == "ANA KOVAC"


def test_a_place_needs_two_title_case_names_around_a_comma():
    assert parse_header("PLATFORMS DETAILS Kraków, Poland +48 22 000 0000")["location"] == "Kraków, Poland"
    assert parse_header("Jo Doe New York, United States x")["location"] == "New York, United States"
    assert parse_header("Jo Doe Product Lead, ACME | Remote")["location"] == ""


def test_links_lose_their_scheme_and_trailing_slash():
    assert normalize_link("https://www.linkedin.com/in/jane/") == "linkedin.com/in/jane"
    assert normalize_link("jane.dev") == "jane.dev"


def test_a_header_without_contact_details_gives_empty_parts_not_defaults():
    info = parse_header("", "")
    assert info == {"name": "", "headline": "", "location": "", "phone": "", "email": "", "links": []}


# --- experience ---------------------------------------------------------------------------------


def test_every_entry_is_found_in_three_different_layouts():
    entries = parse_resume_from_profile(profile(FLAT, ROLES))["experience"]
    assert [(e["title"], e["company"], e["dates"]) for e in entries] == [
        ("Data Engineer", "Northwind Payments", "March 2022 – Present"),
        ("Analyst", "Contoso Retail", "June 2018 – February 2022"),
        ("Junior Developer", "Fabrikam Labs", "2015 – 2018"),
    ]
    assert [e["location"] for e in entries] == ["Remote", "Zagreb, Croatia", ""]


def test_bullets_are_the_entrys_own_text_without_headers_or_subheadings():
    entries = parse_resume_from_profile(profile(FLAT, ROLES))["experience"]
    first = entries[0]["bullets"]
    assert first[0].startswith("Rebuilt the settlement pipeline")
    assert any(b.startswith("Mentored four engineers") for b in first)
    assert not any("Key Outcomes" in b or "European payments" in b for b in first)
    # The company, which this layout puts after the dates, does not open the bullets.
    assert entries[2]["bullets"][0].startswith("Wrote internal tooling")


def test_titles_and_companies_are_read_without_a_profile_list():
    entries = parse_resume_from_profile(profile(FLAT))["experience"]
    assert (entries[0]["title"], entries[0]["company"]) == ("Data Engineer", "Northwind Payments")
    assert (entries[1]["title"], entries[1]["company"]) == ("Analyst", "Contoso Retail")


def test_a_title_company_header_with_no_pipe_splits_at_the_comma():
    entries = parse_resume_from_profile(profile(MULTILINE))["experience"]
    assert [(e["title"], e["company"], e["dates"]) for e in entries] == [
        ("Data Engineer", "Northwind Payments", "March 2022 – Present")
    ]
    assert len(entries[0]["bullets"]) == 2


def test_the_profile_list_labels_an_entry_by_its_start_date():
    roles = ["Principal Engineer — Different Name | 2022 | x"]
    entries = parse_resume_from_profile(profile(FLAT, roles))["experience"]
    assert (entries[0]["title"], entries[0]["company"]) == ("Principal Engineer", "Different Name")


def test_a_year_range_inside_a_sentence_is_not_an_entry():
    text = (
        "WORK HISTORY Engineer, Acme | Remote 2020 – 2022 | Reduced costs in 2019 – 2020 across the whole "
        "estate and led the 2021 – 2022 migration for every customer segment."
    )
    entries = parse_resume_from_profile(profile(text))["experience"]
    assert len(entries) == 1 and entries[0]["dates"] == "2020 – 2022"


def test_no_readable_entry_falls_back_to_the_profile_list_and_nothing_else():
    entries = parse_resume_from_profile(profile("nothing useful here", ROLES))["experience"]
    assert [e["company"] for e in entries] == ["Northwind Payments", "Contoso Retail", "Fabrikam Labs"]
    assert entries[0]["bullets"] == ["Pipelines"]
    assert parse_resume_from_profile(profile("nothing useful here"))["experience"] == []


@pytest.mark.parametrize(
    "text",
    ["April 2024 – Present", "Apr 2024 – Current", "Apr. 2024–Now", "06/2019 – 08/2021", "2014 – 2021", "Sept 2020 — Dec 2021"],
)
def test_date_ranges_in_common_formats(text):
    assert DATE_RANGE_RE.fullmatch(text)


def test_profile_role_entries():
    role = parse_role_entry("Scrum Master — Acme Corp | Jun 2021–Jul 2023 | Led two teams")
    assert (role["title"], role["company"], role["start"]) == ("Scrum Master", "Acme Corp", (2021, 6))
    assert parse_role_entry("Engineer — Acme | 2014–2021")["start"] == (2014, None)
    assert parse_role_entry("no dates here")["start"] is None


# --- skills -------------------------------------------------------------------------------------


def test_labelled_rows_with_any_labels_and_parentheses_in_items():
    rows = parse_skill_rows("Languages: Python, SQL. Data Tools: Airflow, dbt, Kafka (Confluent, Connect). Soft: Writing")
    assert rows == [
        {"label": "Programming languages", "skills": ["Python", "SQL"]},
        {"label": "Data Tools", "skills": ["Airflow", "dbt", "Kafka (Confluent, Connect)"]},
        {"label": "Soft", "skills": ["Writing"]},
    ]


def test_a_label_after_an_item_with_a_dot_starts_a_new_row():
    rows = parse_skill_rows("Delivery : Jira, Monday.com AI Tooling: ChatGPT, Claude")
    assert [(r["label"], r["skills"][-1]) for r in rows] == [("Delivery", "Monday.com"), ("AI Tooling", "Claude")]


def test_text_with_no_labels_gives_no_rows():
    assert parse_skill_rows("Product Strategy, Roadmapping, Discovery") == []


# --- the whole CV -------------------------------------------------------------------------------


def test_the_flat_cv_end_to_end():
    parsed = parse_resume_from_profile(profile(FLAT, ROLES))
    assert parsed["name"] == "ANA KOVAČ"
    assert parsed["headline"] == "Senior Data Engineer for Fintech Teams"
    assert parsed["contact_items"] == [
        "Zagreb, Croatia", "+385 91 234 5678", "ana@example.com", "linkedin.com/in/anakovac", "anakovac.dev",
    ]
    assert parsed["about_me"].startswith("Data engineer with eight years")
    assert [r["label"] for r in parsed["skill_categories"]] == ["Programming languages", "Data Tools"]


def test_the_profile_wins_over_the_cv_header_and_links_mirror_the_cv():
    p = profile(FLAT, ROLES, location="Split, Croatia", phone="+385 1 000 0000")
    p["resume"]["parsedData"]["links"] = ["https://github.com/ana"]
    items = parse_resume_from_profile(p)["contact_items"]
    assert items[:3] == ["Split, Croatia", "+385 1 000 0000", "ana@example.com"]
    assert "github.com/ana" not in items and "anakovac.dev" in items


def test_profile_links_are_used_when_the_cv_header_lists_none():
    p = profile("ANA KOVAC engineer WORK HISTORY nothing", [])
    p["resume"]["parsedData"]["links"] = ["https://github.com/ana", "https://www.linkedin.com/in/ana/"]
    assert parse_resume_from_profile(p)["contact_items"] == ["github.com/ana", "linkedin.com/in/ana"]


def test_an_empty_cv_and_profile_give_empty_parts_and_no_defaults():
    parsed = parse_resume_from_profile({})
    assert parsed["experience"] == [] and parsed["skill_categories"] == []
    assert parsed["about_me"] == "" and parsed["contact_items"] == [] and parsed["headline"] == ""
    assert parsed["education"] == {}


def test_a_flat_row_label_cannot_be_told_from_a_last_item_that_looks_like_one():
    """Known limit of flat text: with no line break, "Scala Data Tools:" reads as one label.

    A row separator (a period, a bracket, a dotted name like "Monday.com") makes it
    unambiguous, and so does any line break. The CV text that prompted this
    parser has them; the limit is recorded here so it is not rediscovered.
    """
    rows = parse_skill_rows("Languages: Python, Scala Data Tools: Airflow")
    assert rows[1]["label"] == "Scala Data Tools"


def test_a_country_code_is_a_place():
    assert parse_header("Jo Doe CONTACT Leeds, UK | jo@example.com")["location"] == "Leeds, UK"
    assert parse_header("Jo Doe | Austin, TX | 555 123 4567")["location"] == "Austin, TX"
