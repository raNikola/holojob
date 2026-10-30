"""Joberty: an opt-in source reading an undocumented public API. Offline, from recorded responses."""

import copy
import io
import json
import urllib.error
from pathlib import Path

import pytest

from dedupe_jobs import _crosspost_key, dedupe_jobs
from providers import joberty_client, joberty_provider
from providers.provider_registry import PROVIDER_CLASSES, PROVIDER_GROUPS, resolve_providers

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "joberty"
LOCATIONS = ["Niš, Serbia", "Serbia"]
REMOTE = ["remote", "hybrid", "flexible"]
TERMS = ["Product Manager"]


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


LISTING = fixture("listing.json")
DETAIL = fixture("detail.json")
CITIES = [f["value"] for f in fixture("filters-all.json")[0]["filters"]]
FIVETRAN = next(i for i in LISTING["items"] if i["companyName"] == "Fivetran Serbia")


def product_ad(job_id, city="Belgrade (Serbia)", title="Product Manager"):
    return {**copy.deepcopy(FIVETRAN), "id": job_id, "jobTitle": title, "cities": [city]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wire(monkeypatch):
    """Replace the network: `script` is a list of JSON bodies or exceptions, one per request."""
    sleeps, urls, script = [], [], []
    monkeypatch.setattr(joberty_client, "_sleep", sleeps.append)
    monkeypatch.setattr(joberty_client, "_last_request", None)

    def urlopen(request, timeout):
        urls.append(request.full_url)
        assert request.get_header("User-agent").startswith("Mozilla/5.0")
        assert timeout == 30
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return FakeResponse(json.dumps(step).encode())

    monkeypatch.setattr(joberty_client.urllib.request, "urlopen", urlopen)
    return type("Wire", (), {"sleeps": sleeps, "urls": urls, "script": script})


def http_error(code):
    return urllib.error.HTTPError("https://backend.joberty.com/x", code, "x", {}, None)


@pytest.fixture
def board(monkeypatch, tmp_path):
    """The provider against a fake client; `calls` records what it asked for."""
    calls = {"listing": 0, "details": []}
    state = {"items": copy.deepcopy(LISTING["items"]), "cities": CITIES}

    def fetch_listing(*args, **kwargs):
        calls["listing"] += 1
        return copy.deepcopy(state["items"])

    def fetch_detail(job_id):
        calls["details"].append(job_id)
        return copy.deepcopy(DETAIL)

    monkeypatch.setattr(joberty_client, "fetch_cities", lambda: state["cities"])
    monkeypatch.setattr(joberty_client, "fetch_listing", fetch_listing)
    monkeypatch.setattr(joberty_client, "fetch_detail", fetch_detail)
    provider = joberty_provider.JobertyProvider(ledger_path=tmp_path / "job_history.json")
    return type("Board", (), {"calls": calls, "state": state, "provider": provider})


def run(board, country="Serbia", locations=LOCATIONS):
    return board.provider.fetch_jobs(TERMS, locations, REMOTE, country)


# --- mapping ---------------------------------------------------------------

def test_an_ad_maps_onto_the_job_shape(board):
    [job] = run(board)
    assert job["title"] == "Sr. Staff Technical Product Manager"
    assert job["company"] == "Fivetran Serbia"
    assert job["location"] == "Novi Sad (Serbia)"
    assert job["jobUrl"] == "https://www.joberty.com/sr/job/fivetran-serbia/sr-staff-technical-product-manager/83188"
    assert job["provider"] == job["source"] == job["site"] == "joberty"
    assert job["description"].startswith("About Us")
    assert "<p>" not in job["description"]
    assert job["domains"] == ["Product Management"]
    assert job["technologies"] == ["Jira", "SQL", "Zendesk", "Salesforce"]
    assert job["seniority"] == "Senior"
    assert job["applyUrl"] == "https://www.fivetran.com/careers/job?gh_jid=7818224003"
    assert job["expiresAt"] == "2026-11-01"
    assert job["externalId"] == "joberty:83188"
    assert job["isRemote"] is False
    assert job["salary"] == job["datePosted"] == job["employmentType"] == ""


def test_the_job_id_depends_only_on_the_stable_url(board):
    first = run(board)[0]["jobId"]
    board.state["items"][2]["seniority"] = "Intermediate"
    board.state["items"][2]["technologies"] = []
    assert run(board)[0]["jobId"] == first


def test_several_cities_are_joined_and_remote_is_flagged_only_when_a_city_says_so(board):
    board.state["items"] = [
        {**product_ad(1), "cities": ["Belgrade (Serbia)", "Remote (Serbia)"]},
        {**product_ad(2), "cities": ["Belgrade (Serbia)", "Novi Sad (Serbia)"]},
    ]
    remote, onsite = run(board)
    assert remote["location"] == "Belgrade (Serbia); Remote (Serbia)" and remote["isRemote"] is True
    assert onsite["location"] == "Belgrade (Serbia); Novi Sad (Serbia)" and onsite["isRemote"] is False


def test_only_product_roles_are_kept_whatever_the_domain_tag(board):
    # The fixture also holds an "Implementation Manager" and a "Junior Product Owner", both tagged Product Management.
    assert [j["title"] for j in run(board)] == ["Sr. Staff Technical Product Manager"]
    assert board.calls["details"] == [83188]


def test_an_unknown_city_is_kept_not_dropped(board):
    board.state["items"] = [product_ad(1, city="Smederevo (Serbia)"), {**product_ad(2), "cities": []}]
    assert [j["jobId"] for j in run(board)] and len(run(board)) == 2


# --- country ---------------------------------------------------------------

def test_an_unsupported_country_returns_nothing_and_asks_for_nothing_more(board, caplog):
    with caplog.at_level("INFO"):
        assert run(board, country="Germany", locations=["Berlin, Germany"]) == []
    assert board.calls == {"listing": 0, "details": []}
    assert "Germany" in caplog.text


def test_supported_countries_come_from_the_facets_not_from_a_list_in_the_code(board):
    board.state["items"] = [product_ad(1, city="Zagreb (Croatia)")]
    assert len(run(board, country="Croatia", locations=["Zagreb, Croatia"])) == 1
    board.state["cities"] = ["Belgrade (Serbia)"]
    assert run(board, country="Croatia", locations=["Zagreb, Croatia"]) == []


def test_no_country_means_no_run(board):
    assert run(board, country="") == []
    assert board.calls["listing"] == 0


# --- caps, ledger, fail-soft -----------------------------------------------

def test_at_most_25_details_are_read_and_the_rest_wait_for_the_next_run(board):
    board.state["items"] = [product_ad(i) for i in range(1, 31)]
    assert len(run(board)) == 25
    assert board.calls["details"] == list(range(1, 26))


def test_an_ad_the_ledger_already_holds_is_not_fetched_again(board, tmp_path):
    known = joberty_provider.to_canonical(FIVETRAN)["jobId"]
    ledger = {"version": 1, "jobs": {known: {"job": {"description": "x" * 400}}}}
    (tmp_path / "job_history.json").write_text(json.dumps(ledger))
    [job] = run(board)
    assert board.calls["details"] == []
    assert job["jobId"] == known and job["description"] == ""  # the ledger restores its own


def test_a_known_ad_with_only_a_thin_description_is_read_again(board, tmp_path):
    known = joberty_provider.to_canonical(FIVETRAN)["jobId"]
    (tmp_path / "job_history.json").write_text(json.dumps({"version": 1, "jobs": {known: {"job": {"description": "short"}}}}))
    run(board)
    assert board.calls["details"] == [83188]


def test_an_ad_whose_detail_cannot_be_read_is_left_for_the_next_run(board, monkeypatch):
    monkeypatch.setattr(joberty_client, "fetch_detail", lambda job_id: {})
    assert run(board) == []


def test_a_crash_inside_the_provider_returns_nothing(board, monkeypatch):
    def boom():
        raise ValueError("shape changed")

    monkeypatch.setattr(joberty_client, "fetch_cities", boom)
    assert run(board) == []


# --- client ----------------------------------------------------------------

def page(n, total_pages, ids):
    return {"items": [{"id": i, "logo": "AAAA", "jobTitle": "Product Manager"} for i in ids], "totalElements": 99, "totalPage": total_pages}


def test_the_listing_stops_after_three_pages_and_drops_the_logos(wire):
    wire.script += [page(n, 10, [n]) for n in range(5)]
    items = joberty_client.fetch_listing()
    assert [i["id"] for i in items] == [0, 1, 2]
    assert all("logo" not in i for i in items)
    assert len(wire.urls) == 3
    assert "page=0" in wire.urls[0] and "page=2" in wire.urls[2]
    assert "domains=Product+Management" in wire.urls[0] and "sort=created" in wire.urls[0]


def test_the_listing_stops_at_the_last_page(wire):
    wire.script += [page(0, 2, [1]), page(1, 2, [2]), page(2, 2, [3])]
    assert [i["id"] for i in joberty_client.fetch_listing()] == [1, 2]


def test_requests_are_spaced_1_5_to_2_seconds_apart(wire):
    wire.script += [page(0, 3, [1]), page(1, 3, [2]), page(2, 3, [3])]
    joberty_client.fetch_listing()
    assert len(wire.sleeps) == 2 and all(1.5 <= s <= 2.0 for s in wire.sleeps)


def test_a_503_and_a_429_are_retried_with_backoff(wire):
    wire.script += [http_error(503), http_error(429), DETAIL]
    assert joberty_client.fetch_detail(83188)["id"] == 83188
    assert len(wire.urls) == 3
    assert wire.sleeps.count(joberty_client.BACKOFF) == 1 and wire.sleeps.count(joberty_client.BACKOFF * 2) == 1


def test_it_gives_up_after_two_retries_and_returns_nothing(wire):
    wire.script += [http_error(500)] * 3
    assert joberty_client.fetch_listing() == []
    assert len(wire.urls) == 3


def test_a_404_is_not_retried(wire):
    wire.script += [http_error(404)]
    assert joberty_client.fetch_detail(1) == {}
    assert len(wire.urls) == 1


def test_a_timeout_and_a_changed_shape_fail_soft(wire):
    wire.script += [TimeoutError()] * 3
    assert joberty_client.fetch_detail(1) == {}
    wire.script += [{"unexpected": True}]
    assert joberty_client.fetch_listing() == []
    wire.script += [{"unexpected": True}]
    assert joberty_client.fetch_cities() == []


def test_the_city_facet_is_read_from_filters_all(wire):
    wire.script += [fixture("filters-all.json")]
    assert "Remote (Serbia)" in joberty_client.fetch_cities()
    assert wire.urls == ["https://backend.joberty.com/api/v1/jobs/filters-all"]


# --- registration and dedupe -----------------------------------------------

def test_joberty_runs_only_when_named():
    assert "joberty" in PROVIDER_CLASSES
    assert not any("joberty" in members for members in PROVIDER_GROUPS.values())
    assert resolve_providers("joberty") == ["joberty"]
    assert resolve_providers(None) == PROVIDER_GROUPS["serbia"]


def test_a_list_may_mix_a_group_and_a_name():
    assert resolve_providers("serbia,joberty") == PROVIDER_GROUPS["serbia"] + ["joberty"]
    assert resolve_providers("serbia, serbia,joberty") == PROVIDER_GROUPS["serbia"] + ["joberty"]


def _role(company):
    return {"title": "Senior Product Manager", "company": company, "location": "Belgrade", "jobUrl": f"https://x/{company}"}


def test_a_country_suffix_does_not_defeat_the_title_and_company_key():
    assert _crosspost_key(_role("Fivetran Serbia")) == _crosspost_key(_role("Fivetran"))
    assert _crosspost_key(_role("Acme North Macedonia")) == _crosspost_key(_role("Acme"))
    assert len(dedupe_jobs([_role("Fivetran Serbia"), _role("Fivetran")])) == 1


def test_a_name_that_is_only_or_of_a_country_is_left_whole():
    assert _crosspost_key(_role("Serbia")).endswith("|serbia")
    assert _crosspost_key(_role("Bank of Serbia")).endswith("|bank of serbia")
    assert _crosspost_key(_role("Fivetran")).endswith("|fivetran")
