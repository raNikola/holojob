"""The rule-based cover letter states only what the candidate wrote.

Every sentence in it is either the candidate's own text, quoted whole, or one of
four fixed connectives that claim nothing about them. The property test below
checks that for the whole letter, so a new invented phrase fails it whatever
its wording.
"""

import re

from candidate_text import banned_phrases_in, narrative_answer, own_sentences
from cover_letter_generator import THANK_YOU, build_cover_letter_context, lint_cover_letter
from resume_tailor import build_resume_context
from template_engine import render_cover_letter_html, render_cover_letter_md

CV = (
    "JO DOE PRODUCT LEADER CONTACT Leeds, UK | jo@example.com "
    "PROFESSIONAL SUMMARY Product leader with a decade of platform work. Ships billing systems that hold up. "
    "PROFESSIONAL EXPERIENCE "
    "Product Lead, Acme | Remote May 2020 – Present | (Platform vendor) "
    "Owned the roadmap for the billing platform and launched it to the first fifty customers. "
    "• Cut invoice disputes by a third by redesigning the dunning flow with finance. "
    "• Hired and coached three product managers across two squads. "
    "• Ran discovery with twenty customers before every major billing release. "
    "Product Manager, Globex | Leeds, UK June 2016 – April 2020 | (Retail group) "
    "Moved the loyalty scheme from a vendor product to an in-house platform. "
    "• Grew active loyalty members from forty to ninety thousand in two years. "
    "• Set up the quarterly planning process the department still uses. "
    "EDUCATION Some University"
)
Q17 = (
    "I build products for finance teams. I care about evidence over opinion. "
    "One of my strengths is thinking outside the box. I like hard migrations."
)
JOB = {"title": "Senior Product Manager", "company": "Initech", "location": "Remote", "description": "billing roadmap discovery"}


def profile(raw=CV, q17=Q17, roles=None):
    p = {
        "basicProfile": {"fullName": "Jo Doe"},
        "resume": {
            "rawText": raw,
            "parsedData": {
                "skills": [],
                "workExperience": roles if roles is not None else [
                    "Product Lead — Acme | May 2020–Present | Billing",
                    "Product Manager — Globex | Jun 2016–Apr 2020 | Loyalty",
                ],
                "education": [],
                "links": [],
            },
        },
    }
    if q17 is not None:
        p["questionnaire"] = {"answers": [{"id": 17, "question": "career summary", "answer": q17}]}
    return p


def letter(p=None, job=JOB):
    p = p or profile()
    resume_ctx = build_resume_context(p, {}, job)
    return build_cover_letter_context(p, {}, job, resume_ctx), p


MECHANICS = [
    re.compile(r"I am applying for (?:the .+ role|this role)(?: at .+)?\."),
    re.compile(r"At .+, where I (?:work|worked) as .+:"),
    re.compile(r"(?:At .+|As .+):"),
    re.compile(r"Before that(?:, as .+ at .+|, at .+|, as .+)?:"),
    re.compile(re.escape(THANK_YOU)),
]


def pieces(ctx):
    """Every sentence and bullet of the letter body."""
    out = []
    for block in ctx["paragraphs"]:
        out += [s for s in re.split(r"(?<=[.!?:])\s+(?=[A-Z])", block["text"]) if s]
        out += block["bullets"]
    return out


def test_every_sentence_is_the_candidates_own_or_a_fixed_connective():
    ctx, p = letter()
    own = re.sub(r"\s+", " ", CV) + " " + narrative_answer(p)
    for piece in pieces(ctx):
        assert any(m.fullmatch(piece) for m in MECHANICS) or piece in own, piece


def test_the_old_invented_frame_is_gone():
    body = " ".join(" ".join([b["text"], *b["bullets"]]) for b in letter()[0]["paragraphs"])
    for invented in ("production systems", "reliability was not optional", "engineering discipline",
                     "design for failure", "maps directly onto", "across the stack", "years I have"):
        assert invented not in body


def test_the_structure_is_opening_current_role_earlier_role_thanks():
    blocks = letter()[0]["paragraphs"]
    assert blocks[0]["text"] == (
        "I am applying for the Senior Product Manager role at Initech. "
        "I build products for finance teams. I care about evidence over opinion."
    )
    assert blocks[1]["text"] == "At Acme, where I work as Product Lead:" and len(blocks[1]["bullets"]) == 3
    assert blocks[2]["text"] == "Before that, as Product Manager at Globex:" and len(blocks[2]["bullets"]) == 2
    assert blocks[3] == {"text": THANK_YOU, "bullets": []}


def test_a_sentence_with_a_banned_phrase_is_skipped_not_edited():
    assert own_sentences(Q17, 3) == [
        "I build products for finance teams.", "I care about evidence over opinion.", "I like hard migrations.",
    ]
    assert banned_phrases_in("thinking outside the box") == ["think outside the box"]
    assert banned_phrases_in("two team players") == ["team player"]


def test_without_q17_the_opening_is_the_cv_summary():
    blocks = letter(profile(q17=None))[0]["paragraphs"]
    assert blocks[0]["text"].endswith("Product leader with a decade of platform work. Ships billing systems that hold up.")


def test_with_no_summary_anywhere_the_opening_is_one_sentence_and_warned_about():
    raw = CV.replace("PROFESSIONAL SUMMARY Product leader with a decade of platform work. Ships billing systems that hold up. ", "")
    ctx, _ = letter(profile(raw=raw, q17=None))
    assert ctx["paragraphs"][0]["text"] == "I am applying for the Senior Product Manager role at Initech."
    assert any("opening is one sentence" in w for w in ctx["warnings"])


def test_with_no_experience_the_letter_is_opening_and_thanks_only():
    ctx, _ = letter(profile(raw="JO DOE nothing else", q17=None, roles=[]))
    assert [b["text"] for b in ctx["paragraphs"]] == [
        "I am applying for the Senior Product Manager role at Initech.", THANK_YOU,
    ]
    assert any("no experience bullets" in w for w in ctx["warnings"])


def test_a_short_honest_letter_is_reported_by_the_lint_not_padded():
    ctx, _ = letter(profile(raw="JO DOE nothing else", q17=None, roles=[]))
    assert any("Word count" in issue for issue in ctx["lint_issues"])
    assert sum(len(" ".join([b["text"], *b["bullets"]]).split()) for b in ctx["paragraphs"]) < 20


def test_a_single_role_gives_no_earlier_role_paragraph():
    raw = CV.split("Product Manager, Globex")[0] + "EDUCATION Some University"
    blocks = letter(profile(raw=raw, roles=["Product Lead — Acme | May 2020–Present | Billing"]))[0]["paragraphs"]
    assert not any(b["text"].startswith("Before that") for b in blocks)


def test_a_past_first_role_uses_the_past_tense():
    raw = CV.replace("May 2020 – Present", "May 2020 – June 2024")
    roles = ["Product Lead — Acme | May 2020–Jun 2024 | Billing", "Product Manager — Globex | Jun 2016–Apr 2020 | Loyalty"]
    assert letter(profile(raw=raw, roles=roles))[0]["paragraphs"][1]["text"] == "At Acme, where I worked as Product Lead:"


def test_no_bullet_is_quoted_twice_and_banned_bullets_are_skipped():
    raw = CV.replace("• Hired and coached", "• A passionate leader who hired and coached")
    blocks = letter(profile(raw=raw))[0]["paragraphs"]
    bullets = [b for block in blocks for b in block["bullets"]]
    assert len(bullets) == len(set(bullets))
    assert not any(banned_phrases_in(b) for b in bullets)


def test_a_job_without_title_or_company_still_reads_correctly():
    assert letter(job={"description": ""})[0]["paragraphs"][0]["text"].startswith("I am applying for this role. ")
    assert letter(job={"title": "PM"})[0]["paragraphs"][0]["text"].startswith("I am applying for the PM role. ")


def test_both_templates_render_the_bullets_as_a_list():
    ctx, _ = letter()
    html = render_cover_letter_html(ctx)
    md = render_cover_letter_md(ctx)
    assert html.count("<li>") == 5 and '<ul class="para-bullets">' in html
    assert "<p class=\"para\">At Acme, where I work as Product Lead:</p>" in html
    assert "- Cut invoice disputes by a third" in md and "At Acme, where I work as Product Lead:" in md


def test_an_llm_draft_renders_as_plain_paragraphs():
    p = profile()
    ctx = build_cover_letter_context(p, {}, JOB, build_resume_context(p, {}, JOB), paragraphs_override=["One.", "Two."])
    assert ctx["paragraphs"] == [{"text": "One.", "bullets": []}, {"text": "Two.", "bullets": []}]
    assert "<li>" not in render_cover_letter_html(ctx)
    assert ctx["warnings"] == []


def test_lint_catches_inflected_cliches_in_an_llm_draft():
    assert any("think outside the box" in i for i in lint_cover_letter(["I keep thinking outside the box."]))
