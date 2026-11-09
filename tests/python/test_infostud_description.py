"""Infostud detail-page description (Wave 5): real-content check, source choice, status. Synthetic HTML, offline."""

import json

from providers import infostud_client, infostud_description as d

AD = (
    "<div><h3>About the role</h3><p>You will own the product roadmap for our payments platform and work with engineering, design "
    "and sales to deliver features customers value.</p><h3>Requirements</h3><ul><li>Five years of experience in product management "
    "for B2B software</li><li>Strong analytical skills and a habit of measuring outcomes</li><li>Excellent written and spoken "
    "English and Serbian</li></ul><p>We offer a hybrid working model, a competitive salary and a team that trusts you.</p></div>"
)
TEASER = "Own the product roadmap for our payments platform and work with engineering, design and sales to deliver..."
BOILER = "".join(
    f"<div>{t}</div>" for t in (
        "We use cookies to improve your experience. Accept all", "Privacy policy", "Log in", "Sign in", "Similar jobs",
        "Related jobs", "Follow us", "Newsletter", "All rights reserved", "Skip to content",
    ) * 6
)


def page(text_ad=None, ld=None, body=""):
    data = {"props": {"pageProps": {"job": {"textAd": text_ad} if text_ad is not None else {}}}}
    out = f'<html><head><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    if ld is not None:
        out += f'<script type="application/ld+json">{json.dumps({"@type": "JobPosting", "description": ld, "employmentType": "FULL_TIME"})}</script>'
    return out + f"</head><body>{body}</body></html>"


def test_html_to_text_blocks_lists_entities():
    text = d.html_to_text("<p>Tom &amp; Jerry</p><ul><li>one</li><li>two</li></ul><script>x=1</script>")
    assert text.splitlines() == ["Tom & Jerry", "- one", "- two"]


def test_real_ad_passes_and_blobs_boilerplate_repeats_fail():
    assert d.real_content_reasons(d.html_to_text(AD)) == []
    assert "looks like a JSON blob" in d.real_content_reasons(json.dumps({"k": ["v " * 30] * 20, "a": {"b": 1}}))
    assert d.real_content_reasons(d.html_to_text(BOILER))
    assert "mostly repeated lines" in d.real_content_reasons("\n".join(["Product manager wanted for a payments team now"] * 8))
    assert d.real_content_reasons("short")


def test_full_text_ad_replaces_teaser_and_is_complete():
    read = d.read_detail(page(text_ad=AD, ld="Short seo blurb."), TEASER)
    assert read["status"] == d.COMPLETE and read["source"] == "next_data"
    assert "Five years of experience" in read["description"] and len(read["description"]) > len(TEASER)


def test_long_boilerplate_body_loses_to_shorter_real_description():
    body = BOILER * 3
    assert len(d.html_to_text(body)) > len(d.html_to_text(AD))
    read = d.read_detail(page(text_ad=AD, body=body), TEASER)
    assert read["source"] == "next_data" and "cookies" not in read["description"]


def test_boilerplate_only_page_is_not_accepted_and_is_source_truncated():
    read = d.read_detail(page(body=BOILER * 3), TEASER)
    assert read == {"description": TEASER, "status": d.SOURCE_TRUNCATED, "source": "teaser"}


def test_json_ld_blurb_alone_does_not_make_an_ad_complete():
    read = d.read_detail(page(ld="A short seo blurb about the job."), TEASER)
    assert read["status"] == d.SOURCE_TRUNCATED and read["description"] == TEASER


def test_text_ad_itself_cut_off_is_source_truncated_but_kept():
    cut = AD.replace("a team that trusts you.", "a team that tr...")
    read = d.read_detail(page(text_ad=cut), TEASER)
    assert read["status"] == d.SOURCE_TRUNCATED and read["source"] == "next_data" and read["description"].endswith("...")


def test_tie_between_passing_candidates_takes_priority_then_length():
    options = [
        {"source": "json_ld", "text": "x" * 900, "reasons": []},
        {"source": "next_data", "text": "y" * 300, "reasons": []},
        {"source": "next_data", "text": "z" * 400, "reasons": []},
        {"source": "body", "text": "w" * 5000, "reasons": ["mostly navigation or cookie text"]},
    ]
    assert d.choose(options)["text"] == "z" * 400
    assert d.choose([options[3]]) is None


def test_enrich_records_status_and_survives_fetch_failure(monkeypatch):
    job = {"jobUrl": "https://x/y", "description": TEASER}
    monkeypatch.setattr(infostud_client, "_get", lambda url: page(text_ad=AD, ld="blurb"))
    out = infostud_client.enrich(dict(job), delay=0)
    assert out["descriptionStatus"] == "complete" and out["employmentType"] == "FULL_TIME"

    def boom(url):
        raise RuntimeError("down")

    monkeypatch.setattr(infostud_client, "_get", boom)
    out = infostud_client.enrich(dict(job), delay=0)
    assert out["descriptionStatus"] == "failed" and out["description"] == TEASER


def test_normalize_marks_teaser():
    assert infostud_client.normalize({"id": 1, "url": "u", "title": "t"})["descriptionStatus"] == "teaser"


def test_provider_canonical_job_carries_status_and_source():
    from providers.infostud_provider import InfostudProvider

    raw = {**infostud_client.normalize({"id": 1, "url": "u", "title": "t"}), "descriptionStatus": "complete", "descriptionSource": "next_data"}
    job = InfostudProvider._to_canonical(raw)
    assert job["descriptionStatus"] == "complete" and job["descriptionSource"] == "next_data"
