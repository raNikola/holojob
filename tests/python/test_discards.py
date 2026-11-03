"""Discard reasons and externalId (slice S2): every ad a provider drops is recorded with a stable reason, and
read == kept + discarded. Offline: each provider runs against fakes for its client; every path is under tmp_path.

The fixtures double as the drop-reason table of docs/DECISIONS.md: each test asserts the exact reasons its provider gives.
"""

import copy
import json
import os
import stat
from pathlib import Path

import pandas as pd
import pytest

import job_history
import staging
from normalize_jobs import _make_job_id
from providers import (
    ashby_provider,
    base_provider,
    greenhouse_provider,
    infostud_client,
    infostud_provider,
    joberty_client,
    joberty_provider,
    jobspy_provider,
    lever_provider,
    remoteok_provider,
    role_filter,
    workable_client,
    workable_provider,
    wwr_provider,
    yc_provider,
)
from test_staging import discover, settled
from test_staging_streaming import collect, SERBIA

TERMS = ["Product Manager", "Product Lead"]
PLACE = ["Zxqville"]  # a place the geography does not know, so only the text of the location decides
COUNTRY = "Serbia"


@pytest.fixture
def run(tmp_path):
    return staging.StagingRun.begin(
        tmp_path, "r1", search_key="k", terms=TERMS, locations=PLACE, country=COUNTRY, remote_filters=[], providers=["x"],
    )


def gather(provider, run, name, tmp_path, locations=None):
    """Run one source the way run_discovery does; return (returned, outcome, source stage, its discard lines)."""
    returned, outcome, stage = collect(provider, run, name, tmp_path, locations or PLACE)
    discards = staging.read_discards(tmp_path / "data/jobs/staging/r1/discards.jsonl").by_source(name)
    return returned, outcome, stage, discards


def accounted(stage, discards, outcome):
    """read == kept + discarded, in the footer and against the lines on disk."""
    footer = stage.footer
    assert footer["discardMismatch"] is False
    assert footer["read"] == footer["kept"] + footer["discarded"] == outcome.read
    assert sum(1 for d in discards if d["counted"]) == footer["discarded"]
    assert sum(1 for d in discards if not d["counted"]) == footer["discardedUncounted"]
    reasons = {}
    for d in discards:
        reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
    assert footer["discardReasons"] == dict(sorted(reasons.items()))
    for d in discards:
        assert d["source"] == stage.source and not staging.discard_problems({**d, "t": "discard"})
        assert "description" not in d
    return {d["reason"] for d in discards if d["counted"]}, {d["reason"] for d in discards if not d["counted"]}


# --- the reason-returning variants give the old answers ----------------------------------------------------------------


def old_is_relevant_role(title, position="", extra_terms=()):
    """The rule as it was before this slice, kept here to hold the new function to it."""
    title_lower = (title or "").lower()
    position_lower = (position or "").lower()
    if any(role_filter._has_phrase(title_lower, term) for term in role_filter.TITLE_EXCLUDE):
        return False
    if position_lower in role_filter.POSITION_WHITELIST:
        return True
    includes = role_filter.TITLE_INCLUDE + tuple(t.lower() for t in extra_terms if t)
    return any(role_filter._has_phrase(title_lower, term) for term in includes)


TITLES = [
    "", None, "Product Manager", "Senior Product Manager", "Junior Product Manager", "Product Owner", "Head of Product",
    "Group Product Manager", "Technical Product Manager", "Technical Production Manager", "Platform Product Lead",
    "Project Manager", "Medior Dev Project Manager", "IT Project Manager", "Delivery Manager", "Account Manager",
    "Sales Manager", "Area Sales Manager", "Brand Manager", "Category Manager", "Product Technologist", "Intern Product Manager",
    "Praktikant Product Manager", "Pripravnik", "Chef", "Product Designer", "Growth Lead", "Program Lead", "Data Product Manager",
    "Product Manager Junior", "PRODUCT MANAGER", "Project Manager Product Owner", "Delivery Lead",
]
POSITIONS = ["", None, "Product Manager", "product owner", "IT Project Manager", "Developer"]
EXTRA = [(), ("Program Lead",), ("Growth", ""), ("delivery lead",)]


@pytest.mark.parametrize("extra", EXTRA, ids=str)
def test_role_drop_reason_agrees_with_the_old_yes_no_for_every_title_and_position(extra):
    for title in TITLES:
        for position in POSITIONS:
            reason = role_filter.role_drop_reason(title, position, extra)
            assert (reason is None) == old_is_relevant_role(title, position, extra), (title, position, extra)
            assert role_filter.is_relevant_role(title, position, extra) == old_is_relevant_role(title, position, extra)


def test_the_reason_codes_of_the_role_filter():
    drop = role_filter.role_drop_reason
    for term in role_filter.TITLE_EXCLUDE:
        title = f"Senior {term.title()} Product Manager"
        assert drop(title) == f"title_excluded:{role_filter.TITLE_EXCLUDE[[t in title.lower() for t in role_filter.TITLE_EXCLUDE].index(True)]}"
    assert drop("Medior Dev Project Manager", "IT Project Manager") == "title_excluded:project manager"
    assert drop("Chef") == "title_not_matched"
    assert drop("Growth Lead") == "title_not_matched" and drop("Growth Lead", "", ("growth",)) is None
    assert drop("Developer", "Product Manager") is None, "a board's own position lets an ad in"
    assert drop("Junior Developer", "Product Manager") == "title_excluded:junior", "but an excluded phrase beats it"
    assert drop("Technical Production Manager") == "title_not_matched", "word boundaries, as before"


def ad(title="Product Manager", location="Zxqville, Serbia", remote=False, description="d"):
    return {"jobId": "x", "title": title, "location": location, "isRemote": remote, "description": description}


FILTER_CASES = [
    # (job, search terms, locations, remote filters, country)
    (ad(), TERMS, ["Zxqville"], [], "Serbia"),
    (ad("Chef"), TERMS, ["Zxqville"], [], "Serbia"),
    (ad("Chef", description="a product manager at heart"), TERMS, ["Zxqville"], [], "Serbia"),
    (ad(location="Berlin"), TERMS, ["Zxqville"], [], "Serbia"),
    (ad(location="Zxqville"), TERMS, ["Zxqville"], [], "Serbia"),
    (ad(location="Zagreb (Croatia)"), TERMS, ["Europe"], [], "Serbia"),
    (ad(location="Austin, TX"), TERMS, ["United States"], [], "Serbia"),
    (ad(location="Austin, TX"), TERMS, ["Serbia"], [], "Serbia"),
    (ad(location="Remote", remote=True), TERMS, ["Remote"], ["remote"], "Serbia"),
    (ad(location="Berlin", remote=True), TERMS, ["Zxqville"], ["remote"], "Serbia"),
    (ad(location="Berlin", remote=True), TERMS, ["Remote"], [], "Serbia"),
    (ad(location=""), TERMS, ["Zxqville"], [], "Serbia"),
    (ad(), [], ["Zxqville"], [], "Serbia"),
    (ad(), TERMS, [], [], ""),
    (ad(location="Anywhere"), TERMS, ["Zxqville"], [], "Europe"),
]


@pytest.mark.parametrize("case", range(len(FILTER_CASES)))
def test_filter_drop_reason_and_split_by_filter_agree_with_filter_jobs(case):
    job, terms, locations, remote, country = FILTER_CASES[case]
    kept = base_provider.filter_jobs([job], terms, locations, remote, country)
    reason = base_provider.filter_drop_reason(job, terms, locations, remote, country)
    assert (reason is None) == (kept == [job])
    split_kept, split_dropped = base_provider.split_by_filter([job], terms, locations, remote, country)
    assert split_kept == kept and [r for _, r in split_dropped] == ([reason] if reason else [])
    strict = base_provider.place_drop_reason(job, locations, remote, country)
    assert (strict is None) == (base_provider.matches_location_filters(job, locations, remote)
                                and base_provider.matches_country(job, country))


def test_the_reason_codes_of_the_place_and_term_filters():
    drop = base_provider.filter_drop_reason
    assert drop(ad("Chef"), TERMS, ["Zxqville"], [], "Serbia") == "search_terms_not_matched"
    assert drop(ad(location="Berlin"), TERMS, ["Zxqville"], [], "Serbia") == "location_not_matched"
    assert drop(ad(location="Zxqville"), TERMS, ["Zxqville"], [], "Serbia") == "country_not_matched"
    assert drop(ad("Chef", location="Berlin"), TERMS, ["Zxqville"], [], "Serbia") == "search_terms_not_matched", "terms first"
    assert drop(ad(), TERMS, ["Zxqville"], [], "Serbia") is None
    assert drop(ad(location="Zagreb (Croatia)"), TERMS, ["Europe"], [], "Serbia") is None, "a place the search names is forgiven"
    assert base_provider.place_drop_reason(ad(location="Zxqville"), ["Zxqville"], [], "Serbia") == "country_not_matched"
    assert base_provider.place_drop_reason(ad(location="Berlin"), ["Zxqville"], [], "Serbia") == "location_not_matched"


# --- the discards file --------------------------------------------------------------------------------------------------


def test_a_discard_line_names_the_ad_and_never_carries_its_description(run, tmp_path):
    writer = run.open_source("greenhouse")
    long_text = "secret ad text " * 500
    job = {"jobId": "j1", "title": "Project Manager", "company": "Acme", "location": "Remote", "jobUrl": "https://a.example/1",
           "description": long_text}
    writer.append([], part="b", read=1, dropped=[base_provider.dropped_ad(job, "title_excluded:project manager", 4711)])
    path = tmp_path / "data/jobs/staging/r1/discards.jsonl"
    assert "secret ad text" not in path.read_text()
    [line] = staging.read_discards(path).records
    assert line == {
        "t": "discard", "source": "greenhouse", "externalId": "4711", "reason": "title_excluded:project manager",
        "jobId": "j1", "title": "Project Manager", "company": "Acme", "location": "Remote", "url": "https://a.example/1",
        "counted": True, "part": "b",
    }


def test_the_discards_file_is_private_and_written_with_fsync_per_part(run, tmp_path, monkeypatch):
    base = tmp_path / "data/jobs/staging"
    assert stat.S_IMODE((base / "r1/discards.jsonl").stat().st_mode) == 0o600
    assert stat.S_IMODE((base / "r1").stat().st_mode) == 0o700 and stat.S_IMODE(base.stat().st_mode) == 0o700
    synced = []
    real = os.fsync
    monkeypatch.setattr(staging.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    writer = run.open_source("lever")
    before = len(synced)
    writer.append([], part="b", dropped=[base_provider.dropped_ad({"title": "t"}, "title_not_matched", None)] * 3)
    assert len(synced) - before == 2, "one fsync for the batch line, one for all three discards"
    assert len(staging.read_discards(base / "r1/discards.jsonl").records) == 3


def test_a_torn_last_discard_line_and_a_bad_line_are_left_out(run, tmp_path):
    writer = run.open_source("lever")
    writer.append([], part="b", dropped=[base_provider.dropped_ad({"title": "a"}, "title_not_matched", "1"),
                                          base_provider.dropped_ad({"title": "b"}, "title_not_matched", "2")])
    path = tmp_path / "data/jobs/staging/r1/discards.jsonl"
    whole = json.dumps({"t": "discard", "source": "lever", "reason": "title_not_matched", "counted": True, "externalId": None}).encode()
    with open(path, "ab") as handle:
        handle.write(b"{broken\n")
        handle.write(json.dumps({"t": "discard", "source": "lever", "reason": "Not A Code", "counted": True}).encode() + b"\n")
        handle.write(json.dumps({"t": "discard", "source": "lever", "reason": "title_not_matched", "counted": True,
                                 "description": "x"}).encode() + b"\n")
        handle.write(whole[: len(whole) // 2])
    found = staging.read_discards(path)
    assert [r["externalId"] for r in found.records] == ["1", "2"]
    assert found.torn and found.unreadable_lines == 1 and found.rejected == 2


def test_discards_that_cannot_be_written_do_not_stop_the_source_and_the_footer_says_so(tmp_path):
    (tmp_path / "data/jobs/staging/r1").mkdir(parents=True)
    (tmp_path / "data/jobs/staging/r1/discards.jsonl").write_text("in the way")  # the exclusive create fails
    run = staging.StagingRun.begin(tmp_path, "r1", search_key="k", terms=[], locations=[], country="", remote_filters=[], providers=[])
    assert run.disabled, "an existing run folder disables the whole run"
    # And a log that fails after it was made:
    run2 = staging.StagingRun.begin(tmp_path, "r2", search_key="k", terms=[], locations=[], country="", remote_filters=[], providers=[])
    run2.discards._fail(OSError("disk full"))
    writer = run2.open_source("lever")
    assert writer.append([{"jobId": "a", "provider": "p", "title": "t"}], part="b",
                         dropped=[base_provider.dropped_ad({"title": "x"}, "title_not_matched", None)]) == 1
    outcome = type("O", (), {"status": "ok", "read": 2, "kept": 1, "error": None, "boards_failed": [], "boards_empty": [],
                             "skip_reason": None})()
    writer.close_source([{"jobId": "a", "provider": "p", "title": "t"}], outcome)
    footer = staging.read_source(tmp_path / "data/jobs/staging/r2/lever.jsonl").footer
    assert footer["discarded"] == 0 and footer["discardMismatch"] is True, "read 2 != kept 1 + discarded 0"


# --- each provider: the table ---------------------------------------------------------------------------------------------


def frame(rows):
    return pd.DataFrame(rows)


def jobspy_row(title, n, ext="li-"):
    return {"title": title, "company": "Acme", "location": "Remote", "job_url": f"https://x.example/{n}", "description": "d",
            "site": "linkedin", "is_remote": True, "id": f"{ext}{n}" if ext else None}


def test_jobspy_drops_and_reasons(run, monkeypatch, tmp_path):
    answers = {
        "Product Manager": frame([jobspy_row("Senior Product Manager", 1), jobspy_row("Project Manager", 2),
                                  jobspy_row("SAP Consultant", 3), jobspy_row("", 4)]),
        "Product Lead": frame([jobspy_row("Product Lead", 5), jobspy_row("Intern Product Manager", 6)]),
    }
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda term, location, remote=False, country="": answers[term])
    returned, outcome, stage, discards = gather(jobspy_provider.JobSpyProvider(), run, "jobspy", tmp_path, ["Remote"])
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"title_excluded:project manager", "title_not_matched", "title_excluded:intern"}
    assert uncounted == {"no_title"}
    assert (outcome.read, outcome.kept, stage.footer["discarded"], stage.footer["discardedUncounted"]) == (5, 2, 3, 1)
    assert stage.external_ids == {j["jobId"]: f"li-{n}" for j, n in zip(returned, (1, 5))}
    [no_title] = [d for d in discards if d["reason"] == "no_title"]
    assert no_title["externalId"] == "li-4" and no_title["url"] == "https://x.example/4"


def test_jobspy_without_an_id_column_gives_no_external_ids_and_the_same_ads(run, monkeypatch, tmp_path):
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda *a, **k: frame([jobspy_row("Product Manager", 1, ext="")]))
    returned, outcome, stage, discards = gather(jobspy_provider.JobSpyProvider(), run, "jobspy", tmp_path, ["Remote"])
    assert returned and stage.external_ids == {} and stage.jobs == returned


def board_postings(kind):
    """Greenhouse, Lever, Ashby: kept, search_terms_not_matched, location_not_matched, country_not_matched, no_title (and not_listed)."""
    shape = {
        "greenhouse": lambda i, t, loc, listed=True: {"id": i, "title": t, "location": {"name": loc}, "absolute_url": f"https://g.example/{i}", "content": "d"},
        "lever": lambda i, t, loc, listed=True: {"id": i, "text": t, "categories": {"location": loc}, "hostedUrl": f"https://l.example/{i}", "descriptionPlain": "d"},
        "ashby": lambda i, t, loc, listed=True: {"id": i, "title": t, "location": loc, "jobUrl": f"https://a.example/{i}", "descriptionPlain": "d", "isListed": listed},
    }[kind]
    rows = [
        shape("p1", "Product Manager", "Zxqville, Serbia"), shape("p2", "Chef", "Zxqville, Serbia"),
        shape("p3", "Product Manager", "Berlin"), shape("p4", "Product Manager", "Zxqville"), shape("p5", "", "Zxqville, Serbia"),
    ]
    if kind == "ashby":
        rows.append(shape("p6", "Product Manager", "Zxqville, Serbia", listed=False))
    return rows


@pytest.mark.parametrize("kind, cls, loader, fetcher", [
    ("greenhouse", greenhouse_provider.GreenhouseProvider, "_load_boards", "_fetch_board"),
    ("lever", lever_provider.LeverProvider, "_load_companies", "_fetch_company"),
    ("ashby", ashby_provider.AshbyProvider, "_load_companies", "_fetch_company"),
])
def test_board_providers_drops_and_reasons(kind, cls, loader, fetcher, run, monkeypatch, tmp_path):
    provider = cls()
    monkeypatch.setattr(provider, loader, lambda: [{"board": "b1"}] if kind == "greenhouse" else ["b1"])
    monkeypatch.setattr(provider, fetcher, lambda board: board_postings(kind))
    returned, outcome, stage, discards = gather(provider, run, kind, tmp_path)
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"search_terms_not_matched", "location_not_matched", "country_not_matched"}
    assert uncounted == ({"no_title", "not_listed"} if kind == "ashby" else {"no_title"})
    assert (outcome.read, outcome.kept, stage.footer["discarded"]) == (4, 1, 3)
    assert stage.external_ids == {returned[0]["jobId"]: "p1"}
    by_ext = {d["externalId"]: d["reason"] for d in discards}
    assert by_ext["p2"] == "search_terms_not_matched" and by_ext["p3"] == "location_not_matched"
    assert by_ext["p4"] == "country_not_matched" and by_ext["p5"] == "no_title"
    if kind == "ashby":
        assert by_ext["p6"] == "not_listed"


def test_wwr_drops_and_reasons(run, monkeypatch, tmp_path):
    def item(n, title, guid=True):
        return {"guid": f"guid-{n}" if guid else "", "title": title, "company": "Acme", "link": f"https://w.example/{n}",
                "description": "d", "pubDate": ""}

    feeds = {
        wwr_provider.RSS_FEEDS[0]: [item(1, "Product Manager"), item(2, "Chef"), item(3, "")],
        wwr_provider.RSS_FEEDS[1]: [item(1, "Product Manager"), item(4, "Product Lead", guid=False)],
        wwr_provider.RSS_FEEDS[2]: [],
    }
    provider = wwr_provider.WWRProvider()
    monkeypatch.setattr(provider, "_parse_feed", lambda url: feeds[url])
    returned, outcome, stage, discards = gather(provider, run, "wwr", tmp_path, ["Remote"])
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"search_terms_not_matched"} and uncounted == {"no_title"}
    assert (outcome.read, outcome.kept) == (3, 2), "the repeat of ad 1 in the second feed is a copy: it is not read twice"
    assert stage.external_ids == {returned[0]["jobId"]: "guid-1"}, "an item with no guid has no external id"


def test_remoteok_and_yc_drops_and_reasons(run, monkeypatch, tmp_path):
    ok = remoteok_provider.RemoteOKProvider()

    def fetch_all():
        ok._unparsable = [{"legal": "notice"}, "stray text"]
        return [{"id": "r1", "position": "Product Manager", "company": "A", "url": "https://r.example/1", "description": "d"},
                {"id": "r2", "position": "Chef", "company": "B", "url": "https://r.example/2", "description": "d"}]

    monkeypatch.setattr(ok, "_fetch_all", fetch_all)
    returned, outcome, stage, discards = gather(ok, run, "remoteok", tmp_path, ["Remote"])
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"search_terms_not_matched"} and uncounted == {"unparsable_row"}
    assert stage.footer["discardedUncounted"] == 2 and stage.external_ids == {returned[0]["jobId"]: "r1"}

    yc = yc_provider.YCProvider()
    monkeypatch.setattr(yc, "_fetch_all", lambda: [
        {"id": 7, "title": "Product Manager", "company": {"name": "Y"}, "location": "Remote", "url": "https://y.example/1"},
        {"id": 8, "title": "Chef", "company": {"name": "Y"}, "location": "Remote", "url": "https://y.example/2"},
        {"id": 9, "title": "", "company": {"name": "Y"}, "location": "Remote", "url": "https://y.example/3"},
    ])
    run2 = staging.StagingRun.begin(tmp_path, "r2", search_key="k", terms=TERMS, locations=["Remote"], country=COUNTRY, remote_filters=[], providers=[])
    import run_discovery
    writer = run2.open_source("yc")
    jobs, outcome = run_discovery.fetch_source(yc, "yc", TERMS, ["Remote"], [], COUNTRY, stage=writer)
    stage = staging.read_source(tmp_path / "data/jobs/staging/r2/yc.jsonl")
    discards = staging.read_discards(tmp_path / "data/jobs/staging/r2/discards.jsonl").by_source("yc")
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"search_terms_not_matched"} and uncounted == {"no_title"}
    assert stage.external_ids == {jobs[0]["jobId"]: "7"}


def infostud_row(n, title, city, position=None):
    return {"id": n, "url": f"https://www.infostud.com/oglas/{n}", "title": title, "companyName": "Acme", "location": city,
            "jobSummary": {"summary": "short"}, "standardizedPosition": {"name": position} if position else None}


def test_infostud_drops_and_reasons(run, monkeypatch, tmp_path):
    rows = [
        infostud_row(1001, "Product Manager", "Zxqville"),
        infostud_row(1002, "Medior Dev Project Manager", "Zxqville", position="IT Project Manager"),
        infostud_row(1003, "Chef", "Zxqville"),
        infostud_row(1004, "Product Manager", "Beograd"),
    ]
    monkeypatch.setattr(infostud_client, "fetch_raw", lambda categories=None: (rows, 4))
    monkeypatch.setattr(infostud_client, "enrich", lambda job, delay=1.0: job)
    returned, outcome, stage, discards = gather(infostud_provider.InfostudProvider(), run, "infostud", tmp_path)
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"title_excluded:project manager", "title_not_matched", "location_not_matched"} and not uncounted
    assert (outcome.read, outcome.kept, stage.footer["total"]) == (4, 1, 4)
    assert stage.external_ids == {returned[0]["jobId"]: "1001"}
    by_ext = {d["externalId"]: d for d in discards}
    assert by_ext["1004"]["reason"] == "location_not_matched" and by_ext["1003"]["reason"] == "title_not_matched"
    for d in discards:
        assert d["jobId"] == _make_job_id(d["url"], d["title"], d["company"], d["location"]), "the id the ad would have had"


def test_infostud_project_manager_with_an_it_position_is_dropped_and_its_id_recorded(run, monkeypatch, tmp_path):
    """The case that prompted this slice: the board's own position says Project Manager, the title says Project Manager."""
    rows = [infostud_row(5150, "Medior Dev Project Manager", "Zxqville", position="IT Project Manager")]
    monkeypatch.setattr(infostud_client, "fetch_raw", lambda categories=None: (rows, 1))
    monkeypatch.setattr(infostud_client, "enrich", lambda job, delay=1.0: pytest.fail("a dropped ad is never read in full"))
    returned, outcome, stage, discards = gather(infostud_provider.InfostudProvider(), run, "infostud", tmp_path)
    assert returned == [] and (outcome.read, outcome.kept) == (1, 0)
    [drop] = discards
    assert drop["reason"] == "title_excluded:project manager" and drop["externalId"] == "5150"
    assert (drop["title"], drop["company"], drop["location"], drop["url"]) == (
        "Medior Dev Project Manager", "Acme", "Zxqville, Serbia", "https://www.infostud.com/oglas/5150")
    assert drop["source"] == "infostud" and drop["counted"] is True and "description" not in drop
    assert role_filter.is_relevant_role("Medior Dev Project Manager", "IT Project Manager") is False, "no rule was changed"


def workable_row(n, title, city, url=True):
    return {"id": f"w{n}", "title": title, "company": "Acme", "url": f"https://jobs.workable.com/view/{n}" if url else "",
            "description": "<p>d</p>", "workplace": "onsite", "location": {"city": city, "countryName": "Serbia" if city == "Zxqville" else ""}}


def test_workable_drops_and_reasons(run, monkeypatch, tmp_path):
    answers = {
        "Product Manager": [workable_row(1, "Product Manager", "Zxqville"), workable_row(2, "Project Manager", "Zxqville"),
                            workable_row(3, "Product Manager", "Paris"), workable_row(4, "Product Manager", "Zxqville", url=False)],
        "Product Lead": [workable_row(2, "Project Manager", "Zxqville"), workable_row(1, "Product Manager", "Zxqville"),
                         workable_row(5, "Chef", "Zxqville"), workable_row(6, "Product Lead", "Zxqville", url=False)],
    }
    monkeypatch.setattr(workable_client, "search", lambda term, location="", limit=100: answers[term])
    monkeypatch.setattr(workable_client.time, "sleep", lambda s: None)
    returned, outcome, stage, discards = gather(workable_provider.WorkableProvider(), run, "workable", tmp_path)
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"title_excluded:project manager", "title_not_matched", "location_not_matched", "no_url"}
    assert uncounted == {"no_url"}, "rows with no address are one entry in `read`: the first is counted, the rest are not"
    assert (outcome.read, outcome.kept) == (5, 1) and [j["jobUrl"][-1] for j in returned] == ["1"]
    assert sum(1 for d in discards if d["reason"] == "title_excluded:project manager") == 1, "seen under two terms, dropped once"
    assert stage.external_ids == {returned[0]["jobId"]: "w1"}


def test_workable_a_place_filter_that_matches_the_city_but_not_the_country(run, monkeypatch, tmp_path):
    rows = [{**workable_row(8, "Product Manager", "Zxqville"), "location": {"city": "Zxqville"}}]
    monkeypatch.setattr(workable_client, "search", lambda term, location="", limit=100: rows)
    monkeypatch.setattr(workable_client.time, "sleep", lambda s: None)
    returned, outcome, stage, discards = gather(workable_provider.WorkableProvider(), run, "workable", tmp_path)
    assert returned == [] and [d["reason"] for d in discards] == ["country_not_matched"]


def test_joberty_drops_and_reasons(run, monkeypatch, tmp_path):
    from test_joberty import CITIES, DETAIL, product_ad

    items = [
        product_ad(1), product_ad(2, title="Project Manager"), product_ad(3, title="Chef"),
        product_ad(4, city="Zagreb (Croatia)"), product_ad(5), product_ad(6),
        {"id": "abc", "jobTitle": "Odd row", "companyName": "Odd"},
        product_ad(3, title="Chef"), product_ad(1),  # the same ads again: copies, not second ads
    ]
    monkeypatch.setattr(joberty_client, "fetch_cities", lambda: CITIES)
    monkeypatch.setattr(joberty_client, "fetch_listing", lambda *a, **k: copy.deepcopy(items))
    monkeypatch.setattr(joberty_client, "fetch_detail", lambda job_id: {} if job_id == 5 else copy.deepcopy(DETAIL))
    monkeypatch.setattr(joberty_client, "MAX_DETAILS", 2)
    returned, outcome, stage, discards = gather(joberty_provider.JobertyProvider(ledger_path=tmp_path / "none.json"), run, "joberty", tmp_path, SERBIA)
    counted, uncounted = accounted(stage, discards, outcome)
    assert counted == {"title_excluded:project manager", "title_not_matched", "location_not_matched", "no_detail_text", "detail_cap"}
    assert uncounted == {"unparsable_row"}
    assert (outcome.read, outcome.kept, stage.footer["discarded"]) == (6, 1, 5)
    assert {d["externalId"]: d["reason"] for d in discards if d["counted"]} == {
        "joberty:2": "title_excluded:project manager", "joberty:3": "title_not_matched", "joberty:4": "location_not_matched",
        "joberty:5": "no_detail_text", "joberty:6": "detail_cap",
    }
    assert stage.external_ids == {returned[0]["jobId"]: "joberty:1"} and returned[0]["externalId"] == "joberty:1"


def test_a_skipped_or_failed_source_has_nothing_to_account_for(run, tmp_path):
    import run_discovery
    from providers import wellfound_provider

    writer = run.open_source("wellfound")
    run_discovery.fetch_source(wellfound_provider.WellfoundProvider(), "wellfound", TERMS, PLACE, [], COUNTRY, stage=writer)
    footer = staging.read_source(tmp_path / "data/jobs/staging/r1/wellfound.jsonl").footer
    assert footer["status"] == "skipped" and footer["discarded"] == 0 and footer["discardMismatch"] is False


def test_a_failed_source_is_not_judged(run, monkeypatch, tmp_path):
    monkeypatch.setattr(infostud_client, "fetch_raw", lambda categories=None: (_ for _ in ()).throw(RuntimeError("down")))
    _, outcome, stage, _ = gather(infostud_provider.InfostudProvider(), run, "infostud", tmp_path)
    assert stage.footer["status"] == "failed" and stage.footer["discardMismatch"] is None


# --- externalId: beside the canonical job, stable, and the job is the one it always was -----------------------------------


def test_external_ids_are_stable_across_two_fetches_and_never_touch_the_job(tmp_path, monkeypatch):
    def fetch_once(run_id):
        provider = greenhouse_provider.GreenhouseProvider()
        monkeypatch.setattr(provider, "_load_boards", lambda: [{"board": "b1"}])
        monkeypatch.setattr(provider, "_fetch_board", lambda board: board_postings("greenhouse"))
        run = staging.StagingRun.begin(tmp_path, run_id, search_key="k", terms=TERMS, locations=PLACE, country=COUNTRY, remote_filters=[], providers=[])
        import run_discovery
        jobs, _ = run_discovery.fetch_source(provider, "greenhouse", TERMS, PLACE, [], COUNTRY, stage=run.open_source("greenhouse"))
        return jobs, staging.read_run(tmp_path, run_id).sources["greenhouse"]

    first_jobs, first = fetch_once("a1")
    second_jobs, second = fetch_once("a2")
    assert first.external_ids == second.external_ids == {first_jobs[0]["jobId"]: "p1"}
    assert [j["jobId"] for j in first_jobs] == [j["jobId"] for j in second_jobs]
    job = first_jobs[0]
    assert job["jobId"] == _make_job_id(job["jobUrl"], job["title"], job["company"], job["location"])
    assert "externalId" not in job and "externalId" not in first.jobs[0], "the canonical job has no such field"


def test_infostud_and_workable_raw_rows_carry_the_id_but_the_canonical_ad_does_not():
    row = infostud_row(77, "Product Manager", "Zxqville")
    raw = infostud_client.normalize(row)
    assert raw["externalId"] == 77
    canonical = infostud_provider.InfostudProvider._to_canonical(raw)
    assert "externalId" not in canonical and canonical["jobId"] == _make_job_id(
        canonical["jobUrl"], canonical["title"], canonical["company"], canonical["location"])
    wraw = workable_client.normalize(workable_row(5, "Product Manager", "Zxqville"))
    assert wraw["externalId"] == "w5" and "externalId" not in workable_provider.WorkableProvider._to_canonical(wraw)


# --- no change for readers --------------------------------------------------------------------------------------------------


def test_what_the_old_commit_path_writes_is_the_same_with_discards_recorded(tmp_path, monkeypatch):
    def provider():
        p = greenhouse_provider.GreenhouseProvider()
        monkeypatch.setattr(p, "_load_boards", lambda: [{"board": "b1"}])
        monkeypatch.setattr(p, "_fetch_board", lambda board: board_postings("greenhouse"))
        return p

    with_staging, without = tmp_path / "with", tmp_path / "without"
    with_staging.mkdir(), without.mkdir()
    # discover() uses the intelligence's own search; the fixture's place is not in it, so drops differ by place only.
    assert discover(with_staging, monkeypatch, {"greenhouse": provider()}) == 0
    assert discover(without, monkeypatch, {"greenhouse": provider()}, staging_on=False) == 0
    assert settled(with_staging) == settled(without)
    [run_id] = staging.list_runs(with_staging)
    found = staging.read_run(with_staging, run_id)
    assert found.discards.records, "the run recorded its drops"
    assert found.sources["greenhouse"].footer["discardMismatch"] is False
