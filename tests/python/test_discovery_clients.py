"""Live smoke tests for scrapers that parse other people's page structures.

They fail loudly when the site changes shape (a ValueError from the parser,
or an empty result). A site that cannot be reached at all is skipped: that is
the network, not the parser.
"""

import pytest

from providers import infostud_client, workable_client

pytestmark = pytest.mark.network


def _skip_if_unreachable(exc):
    if "unreachable" in str(exc):
        pytest.skip(str(exc))
    raise exc


def test_infostud_fetch_raw_returns_rows():
    try:
        rows, total = infostud_client.fetch_raw(
            categories=(infostud_client.DEFAULT_CATEGORIES[0],), max_pages=1, delay=0
        )
    except RuntimeError as exc:
        _skip_if_unreachable(exc)
    assert total > 0, "Infostud reported no results: initialSearchResults moved?"
    assert rows, "Infostud returned no job rows: jobs.primary moved?"

    job = infostud_client.normalize(rows[0])
    assert job["title"] and job["jobUrl"] and job["jobId"]
    assert job["location"].endswith("Serbia")


def test_workable_search_returns_jobs():
    try:
        rows = workable_client.search("Product Manager", "Serbia")
    except RuntimeError as exc:
        _skip_if_unreachable(exc)
    assert rows, "Workable returned no jobs: endpoint or response shape changed?"

    job = workable_client.normalize(rows[0])
    assert job["title"] and job["jobUrl"] and job["company"]
    assert len(job["description"]) > 100, "Workable description missing or empty"
