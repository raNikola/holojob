"""LinkedIn publishes one role as several ads, one per city."""

from dedupe_jobs import dedupe_jobs


def _ad(city, job_id, company="Acme", title="Senior Product Manager", source="linkedin", **extra):
    return {
        "title": title,
        "company": company,
        "location": f"{city}, Serbia",
        "source": source,
        "jobUrl": f"https://www.linkedin.com/jobs/view/{job_id}",
        "description": "Own the roadmap.",
        **extra,
    }


def test_role_cross_posted_to_three_cities_collapses_to_one():
    ads = [_ad("Belgrade", 1), _ad("Novi Sad", 2), _ad("Nis", 3)]
    assert len(dedupe_jobs(ads)) == 1


def test_the_ad_with_the_fullest_description_survives():
    ads = [
        _ad("Belgrade", 1, description=""),
        _ad("Novi Sad", 2, description="A long, complete description of the role."),
        _ad("Nis", 3, description="Short."),
    ]
    assert dedupe_jobs(ads)[0]["jobUrl"].endswith("/2")


def test_same_url_collapses():
    assert len(dedupe_jobs([_ad("Belgrade", 1), _ad("Belgrade", 1)])) == 1


def test_different_company_is_kept():
    ads = [_ad("Belgrade", 1), _ad("Belgrade", 2, company="Globex")]
    assert len(dedupe_jobs(ads)) == 2


def test_same_title_and_company_on_different_sources_is_kept():
    ads = [_ad("Belgrade", 1), _ad("Belgrade", 2, source="infostud")]
    assert len(dedupe_jobs(ads)) == 2


def test_ad_without_company_is_never_merged_by_title():
    ads = [_ad("Belgrade", 1, company=""), _ad("Nis", 2, company="")]
    assert len(dedupe_jobs(ads)) == 2
