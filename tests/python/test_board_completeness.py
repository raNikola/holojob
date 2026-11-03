"""Board completeness evidence (slice S5b): what the staging footer says about each snapshot board. Offline: requests.get is faked."""

import pytest
import requests

import run_discovery
import staging
from providers import ashby_provider, greenhouse_provider, lever_provider
from providers.base_provider import board_read, parts_outcome

TERMS, PLACE, COUNTRY = ["product manager"], ["Remote"], "Serbia"


class Answer:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.body


def postings(count, kind):
    def one(i):
        title = f"Product Manager {i}"
        if kind == "greenhouse":
            return {"id": i, "title": title, "location": {"name": "Remote"}, "absolute_url": f"https://g.example/{i}", "content": "x"}
        if kind == "lever":
            return {"id": str(i), "text": title, "categories": {"location": "Remote"}, "hostedUrl": f"https://l.example/{i}", "descriptionPlain": "x"}
        return {"id": str(i), "title": title, "location": "Remote", "jobUrl": f"https://a.example/{i}", "descriptionPlain": "x"}
    return [one(i) for i in range(count)]


def footer_of(tmp_path, monkeypatch, provider, name, loader, boards, fake_get):
    """Run the real fetch through the real staging writer and read the footer back from disk."""
    monkeypatch.setattr(provider, loader, lambda: boards)
    monkeypatch.setattr(requests, "get", fake_get)
    run = staging.StagingRun.begin(tmp_path, "run0000aaaaaa", search_key="k", terms=TERMS, locations=PLACE, country=COUNTRY, remote_filters=[], providers=[name])
    run_discovery.fetch_source(provider, name, TERMS, PLACE, [], COUNTRY, stage=run.open_source(name))
    run.finish()
    footer = staging.read_run(tmp_path, "run0000aaaaaa").sources[name].footer
    return footer, {row["board"]: row for row in footer["boardsRead"]}


# --- Greenhouse --------------------------------------------------------------------------------------------------------


def greenhouse(tmp_path, monkeypatch, answers):
    def fake(url, **_):
        board = url.split("/boards/")[1].split("/")[0]
        answer = answers[board]
        return answer if isinstance(answer, Answer) else Answer(answer)

    return footer_of(tmp_path, monkeypatch, greenhouse_provider.GreenhouseProvider(), "greenhouse", "_load_boards", [{"board": b} for b in answers], fake)


def test_greenhouse_is_complete_only_when_the_reported_total_is_what_was_read(tmp_path, monkeypatch):
    jobs = postings(3, "greenhouse")
    footer, rows = greenhouse(tmp_path, monkeypatch, {
        "same": {"jobs": jobs, "meta": {"total": 3}},
        "more": {"jobs": jobs, "meta": {"total": 4}},
        "fewer": {"jobs": jobs, "meta": {"total": 2}},
        "nototal": {"jobs": jobs},
        "badtotal": {"jobs": jobs, "meta": {"total": "3"}},
        "badmeta": {"jobs": jobs, "meta": 3},
    })
    assert rows["same"]["complete"] is True and rows["same"]["reason"] is None and rows["same"]["reportedTotal"] == 3
    assert rows["same"]["postings"] == 3 and rows["same"]["read"] == 3
    assert rows["more"]["complete"] is False and "reports 4 postings and 3 were read" in rows["more"]["reason"]
    assert rows["fewer"]["complete"] is False and "reports 2" in rows["fewer"]["reason"]
    for name in ("nototal", "badtotal", "badmeta"):
        assert rows[name]["complete"] is False and rows[name]["reason"] == "the answer reports no total"
    assert footer["status"] == "ok", "an unproven board does not change how the source went"


def test_greenhouse_true_is_not_a_total():
    assert greenhouse_provider.board_completeness(1, True) == (False, "the answer reports no total")


def test_greenhouse_failed_and_empty_boards_are_not_complete(tmp_path, monkeypatch):
    _, rows = greenhouse(tmp_path, monkeypatch, {
        "good": {"jobs": postings(1, "greenhouse"), "meta": {"total": 1}},
        "down": Answer({}, 500),
        "empty": {"jobs": [], "meta": {"total": 0}},
    })
    assert rows["good"]["complete"] is True
    assert rows["down"] == {"board": "down", "read": 0, "postings": 0, "complete": False, "reason": "the board could not be read"}
    assert rows["empty"]["complete"] is False and rows["empty"]["reason"] == "the board answered with no ads"


def test_a_posting_with_no_title_counts_against_the_total_not_as_read(tmp_path, monkeypatch):
    jobs = postings(2, "greenhouse") + [{"id": 9, "title": "", "location": {"name": "Remote"}}]
    _, rows = greenhouse(tmp_path, monkeypatch, {"b": {"jobs": jobs, "meta": {"total": 3}}})
    assert rows["b"]["complete"] is True and rows["b"]["postings"] == 3 and rows["b"]["read"] == 2


# --- Lever -------------------------------------------------------------------------------------------------------------


class LeverApi:
    """The first GET of a company is the list; a GET with `skip` is the end check."""

    def __init__(self, lists, ends=None):
        self.lists, self.ends, self.calls = lists, ends or {}, []

    def __call__(self, url, params=None, **_):
        company = url.rsplit("/", 1)[1]
        host = "eu" if ".eu." in url else "global"
        self.calls.append((host, company, params))
        if params:
            answer = self.ends.get(company, Answer([]))
            if isinstance(answer, Exception):
                raise answer
            return answer if isinstance(answer, Answer) else Answer(answer)
        answer = self.lists[company]
        if isinstance(answer, dict) and host in answer:
            answer = answer[host]
        return answer if isinstance(answer, Answer) else Answer(answer)


def lever(tmp_path, monkeypatch, api):
    return footer_of(tmp_path, monkeypatch, lever_provider.LeverProvider(), "lever", "_load_companies", list(api.lists), api)


def test_lever_is_complete_when_the_end_check_is_empty_with_one_extra_request_on_the_host_that_answered(tmp_path, monkeypatch):
    api = LeverApi({"eurocorp": {"global": Answer({}, 404), "eu": postings(3, "lever")}})
    _, rows = lever(tmp_path, monkeypatch, api)
    assert rows["eurocorp"]["complete"] is True and rows["eurocorp"]["reason"] is None and rows["eurocorp"]["postings"] == 3
    checks = [c for c in api.calls if c[2]]
    assert checks == [("eu", "eurocorp", {"mode": "json", "skip": 3, "limit": 1})]
    assert len([c for c in api.calls if not c[2]]) == 2, "the two hosts, as before"


@pytest.mark.parametrize("end, reason", [
    (postings(1, "lever"), "returned postings past the 3 read"),
    (Answer({}, 500), "request failed (HTTPError)"),
    (requests.ConnectionError("no"), "request failed (ConnectionError)"),
    ({"ok": False}, "did not answer with a list"),
])
def test_lever_a_non_empty_or_failed_end_check_leaves_the_board_unproven_and_nothing_else(tmp_path, monkeypatch, end, reason):
    api = LeverApi({"acme": postings(3, "lever")}, {"acme": end})
    footer, rows = lever(tmp_path, monkeypatch, api)
    assert rows["acme"]["complete"] is False and reason in rows["acme"]["reason"]
    assert footer["status"] == "ok" and footer["read"] == 3 and footer["boardsFailed"] == [], "the read itself stands"


def test_lever_failed_and_empty_boards_are_not_complete_and_make_no_end_check(tmp_path, monkeypatch):
    api = LeverApi({"down": Answer({}, 500), "empty": []})
    _, rows = lever(tmp_path, monkeypatch, api)
    assert rows["down"]["complete"] is False and rows["down"]["reason"] == "the board could not be read"
    assert rows["empty"]["complete"] is False and rows["empty"]["reason"] == "the board answered with no ads"
    assert not [c for c in api.calls if c[2]]


def test_lever_with_no_answering_host_is_unproven_and_makes_no_request(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no request"))
    assert lever_provider.LeverProvider()._end_of_list("acme", 3) == (False, "the end of the list was not checked")


# --- Ashby -------------------------------------------------------------------------------------------------------------


def ashby(tmp_path, monkeypatch, answers):
    def fake(url, **_):
        answer = answers[url.rsplit("/", 1)[1]]
        return answer if isinstance(answer, Answer) else Answer(answer)

    return footer_of(tmp_path, monkeypatch, ashby_provider.AshbyProvider(), "ashby", "_load_companies", list(answers), fake)


def test_ashby_is_never_complete_and_stages_its_counts(tmp_path, monkeypatch):
    _, rows = ashby(tmp_path, monkeypatch, {
        "good": {"jobs": postings(3, "ashby"), "apiVersion": "1"},
        "down": Answer({}, 500),
        "empty": {"jobs": [], "apiVersion": "1"},
    })
    assert rows["good"]["complete"] is False and rows["good"]["reason"] == "no completeness proof available"
    assert rows["good"]["read"] == 3 and rows["good"]["postings"] == 3 and rows["good"]["anomalies"] == []
    assert not any(row["complete"] for row in rows.values())
    assert rows["down"]["reason"] == "the board could not be read" and rows["empty"]["reason"] == "the board answered with no ads"


@pytest.mark.parametrize("field", ["nextPage", "cursor", "totalCount", "hasMore", "offset", "pageSize"])
def test_ashby_a_paging_field_is_recorded_as_an_anomaly_and_never_makes_it_complete(tmp_path, monkeypatch, field):
    provider = ashby_provider.AshbyProvider()
    footer, rows = footer_of(tmp_path, monkeypatch, provider, "ashby", "_load_companies", ["b"],
                             lambda url, **_: Answer({"jobs": postings(1, "ashby"), "apiVersion": "1", field: 1}))
    assert rows["b"]["anomalies"] == [f"paging field in the answer: {field}"] and rows["b"]["complete"] is False
    assert any(field in warning for warning in provider.last_outcome.warnings)
    assert footer["status"] == "ok"


def test_ashby_today_answer_has_no_paging_field():
    assert ashby_provider.paging_fields({"jobs": [], "apiVersion": "1"}) == []


# --- the shared rule ---------------------------------------------------------------------------------------------------


def test_parts_outcome_forces_failed_and_empty_boards_out_of_complete_whatever_a_provider_said():
    claims = [board_read(b, read=1, postings=1, complete=True, reason=None) for b in ("down", "empty", "good")]
    outcome = parts_outcome(read=3, kept=0, total=3, failures={"down": "boom"}, empty=["empty"], boards_read=claims)
    rows = {r["board"]: r for r in outcome.boards_read}
    assert [rows[b]["complete"] for b in ("down", "empty", "good")] == [False, False, True]
    assert rows["down"]["reason"] and rows["empty"]["reason"] and rows["good"]["reason"] is None


def test_an_incomplete_board_always_says_why_and_a_complete_one_never_does():
    assert board_read("b", read=1, postings=1, complete=True, reason="ignored")["reason"] is None
    assert board_read("b", read=1, postings=1, complete=False, reason="why")["reason"] == "why"


def test_a_source_that_is_not_a_board_source_has_no_lines():
    assert parts_outcome(read=1, kept=1, total=1, failures={}).boards_read == []
