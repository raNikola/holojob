"""Fill from ad, step 1: a fetcher that cannot be pointed at the home network, and a reader that guesses nothing."""

import http.server
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "job_import"))

import ad_fill  # noqa: E402
import ad_reader  # noqa: E402
import safe_fetch  # noqa: E402
from safe_fetch import FetchRefused  # noqa: E402


def refused(call, code):
    with pytest.raises(FetchRefused) as raised:
        call()
    assert raised.value.code == code
    return raised.value


def resolver_for(*addresses):
    def resolve(host, port, type=None):  # noqa: A002 (getaddrinfo's own name)
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]
    return resolve


# --- which addresses may be fetched --------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "example.com/x", "", "https://",
    "https://user:pw@example.com/x", "https://user@example.com/x",
])
def test_only_plain_http_and_https_addresses_without_credentials(url):
    refused(lambda: safe_fetch.check_url(url), "bad_url")


@pytest.mark.parametrize("url", [
    "http://example.com:3073/x", "https://example.com:8443/x", "http://example.com:22/", "https://example.com:0/",
    "http://localhost/x", "http://LOCALHOST./x", "http://careeros/x", "https://careeros.void/", "http://nas.lan/",
    "http://printer.local/", "http://svc.internal/x", "http://127.0.0.1:3073/api/jobs",
])
def test_odd_ports_and_local_names_are_refused_before_any_lookup(url):
    refused(lambda: safe_fetch.check_url(url), "blocked_host")


def test_a_normal_address_is_accepted():
    assert safe_fetch.check_url("HTTPS://Jobs.Example.com/o/123?x=1#frag") == ("https", "jobs.example.com", 443, "/o/123?x=1")
    assert safe_fetch.check_url("http://example.com")[3] == "/"


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.1.2.3", "10.0.0.5", "172.16.4.4", "192.168.1.20", "169.254.169.254", "0.0.0.0",
    "100.64.0.1", "100.127.255.254",              # carrier-grade NAT: Tailscale lives here
    "224.0.0.1", "240.0.0.1", "192.0.0.8", "198.18.0.1", "255.255.255.255",
    "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1", "2002:7f00:1::1", "2001:0:4136:e378:8000:63bf:80ff:fffe",
])
def test_every_non_public_address_is_refused(address):
    refused(lambda: safe_fetch.resolve_public("jobs.example.com", 443, resolver_for(address)), "blocked_host")


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946", "100.63.255.255", "100.128.0.1"])
def test_public_addresses_pass(address):
    assert safe_fetch.resolve_public("jobs.example.com", 443, resolver_for(address)) == [address]


def test_one_private_answer_among_public_ones_refuses_the_host():
    refused(lambda: safe_fetch.resolve_public("mixed.example.com", 443, resolver_for("93.184.216.34", "10.1.1.1")), "blocked_host")


def test_a_name_that_does_not_resolve_is_unreachable_and_an_ip_literal_is_checked_as_is():
    def nothing(*_a, **_k):
        raise socket.gaierror("no such host")

    refused(lambda: safe_fetch.resolve_public("nope.example.com", 443, nothing), "unreachable")
    refused(lambda: safe_fetch.resolve_public("192.168.0.9", 80, nothing), "blocked_host")
    refused(lambda: safe_fetch.resolve_public("[::1]".strip("[]"), 80, nothing), "blocked_host")


# --- redirects, statuses, walls (the request itself is faked) -----------------------------------------------------

def page(html="<html><title>x</title></html>", content_type="text/html; charset=utf-8", status=200, location=None):
    headers = {"content-type": content_type}
    if location:
        headers["location"] = location
    return status, headers, html.encode()


class Script:
    """A request double that answers from a script and records where it was asked to connect."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, scheme, host, ips, port, target, deadline, max_bytes=safe_fetch.MAX_BYTES):
        self.calls.append((scheme, host, tuple(ips), port, target))
        return self.answers.pop(0)


PUBLIC = resolver_for("93.184.216.34")


def test_a_page_is_returned_with_its_final_address():
    result = safe_fetch.fetch_page("https://jobs.example.com/o/1", resolver=PUBLIC, request=Script(page("<p>hi</p>")))
    assert result.url == "https://jobs.example.com/o/1" and "<p>hi</p>" in result.html


def test_the_connection_goes_to_the_address_that_was_checked():
    script = Script(page())
    safe_fetch.fetch_page("https://jobs.example.com/o/1", resolver=PUBLIC, request=script)
    assert script.calls[0][:3] == ("https", "jobs.example.com", ("93.184.216.34",))


def test_a_redirect_to_a_private_host_is_refused_on_that_hop():
    script = Script(page(status=302, location="http://10.0.0.7/admin"))
    refused(lambda: safe_fetch.fetch_page("https://jobs.example.com/a", resolver=lambda host, port, type=None: resolver_for("93.184.216.34" if host.endswith("example.com") else "10.0.0.7")(host, port),
                                          request=script), "blocked_host")
    assert len(script.calls) == 1  # the private hop was never requested


@pytest.mark.parametrize("location", ["http://127.0.0.1:3073/", "http://localhost/", "ftp://example.com/x", "http://[::1]/", "https://careeros.void/"])
def test_redirects_to_other_schemes_ports_and_local_names_are_refused(location):
    script = Script(page(status=301, location=location))
    with pytest.raises(FetchRefused):
        safe_fetch.fetch_page("https://jobs.example.com/a", resolver=PUBLIC, request=script)
    assert len(script.calls) == 1


def test_relative_redirects_are_followed_and_checked_and_at_most_three_hops():
    ok = Script(page(status=302, location="/moved"), page("<p>final</p>"))
    result = safe_fetch.fetch_page("https://jobs.example.com/a", resolver=PUBLIC, request=ok)
    assert result.url == "https://jobs.example.com/moved" and ok.calls[1][4] == "/moved"
    loop = Script(*[page(status=302, location="/again")] * 6)
    refused(lambda: safe_fetch.fetch_page("https://jobs.example.com/a", resolver=PUBLIC, request=loop), "redirects")
    assert len(loop.calls) == safe_fetch.MAX_REDIRECTS + 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503, 999])
def test_any_error_status_is_a_failure(status):
    refused(lambda: safe_fetch.fetch_page("https://jobs.example.com/a", resolver=PUBLIC, request=Script(page(status=status))), "http_error")


def test_a_redirect_without_a_target_is_a_failure():
    refused(lambda: safe_fetch.fetch_page("https://jobs.example.com/a", resolver=PUBLIC, request=Script(page(status=302))), "http_error")


@pytest.mark.parametrize("content_type", ["application/pdf", "application/json", "image/png", "text/plain", ""])
def test_only_html_is_read(content_type):
    refused(lambda: safe_fetch.fetch_page("https://jobs.example.com/a", resolver=PUBLIC, request=Script(page(content_type=content_type))), "not_html")


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/posts/jane-doe_hiring-activity-123", "https://www.linkedin.com/feed/update/urn:li:activity:1",
    "https://www.linkedin.com/authwall?trk=x", "https://www.linkedin.com/uas/login?session_redirect=x",
    "https://example.com/login?next=/job/1", "https://example.com/signin", "https://example.com/checkpoint/challenge",
])
def test_login_walls_and_posts_are_refused_without_a_request(url):
    script = Script()
    refused(lambda: safe_fetch.fetch_page(url, resolver=PUBLIC, request=script), "login_wall")
    assert not script.calls


def test_a_redirect_to_a_login_page_is_a_wall():
    script = Script(page(status=302, location="https://www.linkedin.com/authwall?x=1"))
    refused(lambda: safe_fetch.fetch_page("https://www.linkedin.com/jobs/view/123", resolver=PUBLIC, request=script), "login_wall")


def test_messages_quote_nothing_from_the_page():
    error = refused(lambda: safe_fetch.fetch_page("https://jobs.example.com/a", resolver=PUBLIC,
                                                  request=Script(page("SECRET-PAGE-TEXT", status=500))), "http_error")
    assert "SECRET" not in error.message


# --- the real request: pinned address, no credentials, limits (against a local server, bypassing the guard) -------------

class _Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *_a):
        pass

    def do_GET(self):  # noqa: N802
        _Handler.seen.append({k.lower(): v for k, v in self.headers.items()})
        if self.path == "/big":
            body = b"x" * 3000
        elif self.path == "/slow":
            time.sleep(1.5)
            body = b"late"
        else:
            body = b"<html>ok</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


@pytest.fixture
def local_server():
    _Handler.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


def test_the_request_carries_no_cookie_auth_referer_or_compression(local_server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    status, headers, body = safe_fetch._request("http", "jobs.example.com", ["127.0.0.1"], local_server, "/ok", time.monotonic() + 5)
    assert (status, body) == (200, b"<html>ok</html>")
    seen = _Handler.seen[0]
    assert seen["host"].startswith("jobs.example.com")  # the name, though the connection went to the checked address
    assert seen["accept-encoding"] == "identity"
    for header in ("cookie", "authorization", "referer", "proxy-authorization"):
        assert header not in seen


def test_a_body_over_the_cap_is_refused(local_server):
    refused(lambda: safe_fetch._request("http", "jobs.example.com", ["127.0.0.1"], local_server, "/big", time.monotonic() + 5, max_bytes=1000), "too_large")


def test_a_slow_page_hits_the_deadline(local_server):
    start = time.monotonic()
    refused(lambda: safe_fetch._request("http", "jobs.example.com", ["127.0.0.1"], local_server, "/slow", time.monotonic() + 0.4), "timeout")
    assert time.monotonic() - start < 1.2


def test_nothing_listening_is_unreachable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    refused(lambda: safe_fetch._request("http", "jobs.example.com", ["127.0.0.1"], port, "/", time.monotonic() + 3), "unreachable")


# --- the reader --------------------------------------------------------------------------------------------------

def ld(**posting):
    body = {"@context": "https://schema.org", "@type": "JobPosting", **posting}
    return f'<html><head><title>Job</title><script type="application/ld+json">{json.dumps(body)}</script></head><body><p>text</p></body></html>'


FULL = dict(
    title="Senior Product Manager", hiringOrganization={"@type": "Organization", "name": "Acme d.o.o."},
    jobLocation={"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Niš", "addressCountry": "RS"}},
    baseSalary={"@type": "MonetaryAmount", "currency": "EUR", "value": {"@type": "QuantitativeValue", "minValue": 2500, "maxValue": 3200, "unitText": "MONTH"}},
    description="&lt;p&gt;Own the roadmap.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Discovery&lt;/li&gt;&lt;li&gt;Delivery&lt;/li&gt;&lt;/ul&gt;&lt;p&gt;Apply today.&lt;/p&gt;",
)


def test_json_ld_full_posting_fills_every_field():
    ad = ad_reader.read_ad(ld(**FULL))
    assert ad["source"] == "json-ld" and ad["missing"] == [] and ad["readable"]
    assert ad["fields"]["title"] == "Senior Product Manager" and ad["fields"]["company"] == "Acme d.o.o."
    assert ad["fields"]["location"] == "Niš, RS"
    assert ad["fields"]["salary"] == "2500 - 3200 monthly EUR"
    assert ad["fields"]["description"] == "Own the roadmap.\n\n- Discovery\n- Delivery\n\nApply today."


def test_a_partial_posting_reports_exactly_what_it_lacks():
    ad = ad_reader.read_ad(ld(title="Product Manager", description="<p>Do things.</p>"))
    assert ad["fields"]["title"] == "Product Manager" and ad["fields"]["description"] == "Do things."
    assert ad["missing"] == ["company", "location", "salary"]


@pytest.mark.parametrize("pay", [
    {"currency": "USD", "value": {"minValue": 5000, "maxValue": 6000, "unitText": "MONTH"}},   # converted: not EUR
    {"currency": "EUR", "value": {"minValue": 15, "maxValue": 20, "unitText": "HOUR"}},         # hourly
    {"currency": "EUR", "value": {"minValue": 2500, "maxValue": 3000}},                         # no interval
    {"currency": "RSD", "value": {"minValue": 300000, "unitText": "MONTH"}},
    {"value": {"minValue": 2500, "unitText": "MONTH"}},                                         # no currency
    {"currency": "EUR", "value": {"minValue": 3, "maxValue": 5, "unitText": "MONTH"}},          # not plausible pay
    "competitive",
])
def test_salary_is_left_unknown_unless_it_is_eur_per_month_with_certainty(pay):
    assert ad_reader.read_ad(ld(title="PM", baseSalary=pay))["fields"]["salary"] == ""


def test_a_yearly_euro_figure_is_normalised_to_months():
    pay = {"currency": "EUR", "value": {"minValue": 36000, "maxValue": 48000, "unitText": "YEAR"}}
    assert ad_reader.read_ad(ld(title="PM", baseSalary=pay))["fields"]["salary"] == "3000 - 4000 monthly EUR"
    assert ad_reader.normalize_salary("USD 5000 monthly") == "" and ad_reader.normalize_salary("3000 monthly EUR") == "3000 monthly EUR"


def test_graph_and_list_shapes_are_found():
    graph = json.dumps({"@graph": [{"@type": "Organization"}, {"@type": ["JobPosting"], "title": "In a graph"}]})
    assert ad_reader.read_ad(f'<script type="application/ld+json">{graph}</script>')["fields"]["title"] == "In a graph"
    listed = json.dumps([{"@type": "WebSite"}, {"@type": "JobPosting", "title": "In a list"}])
    assert ad_reader.read_ad(f'<script type="application/ld+json">{listed}</script>')["fields"]["title"] == "In a list"


def test_no_structured_data_means_everything_is_missing_and_nothing_is_guessed():
    text = "We are hiring a Product Manager at Acme in Niš. " * 12
    ad = ad_reader.read_ad(f"<html><head><title>Careers</title><meta property='og:site_name' content='Acme'></head><body><nav>menu</nav><p>{text}</p><script>var secret=1</script></body></html>")
    assert ad["source"] == "none" and ad["readable"]
    assert ad["missing"] == list(ad_reader.FIELDS) and not any(ad["fields"].values())
    assert "We are hiring" in ad["pageText"] and "secret" not in ad["pageText"] and "menu" not in ad["pageText"]
    assert ad["pageText"].startswith("Page title: Careers") and len(ad["pageText"]) <= ad_reader.PAGE_TEXT_CAP


def test_an_empty_shell_is_not_readable():
    assert ad_reader.read_ad("<html><body><div id='root'></div></body></html>")["readable"] is False
    assert ad_reader.read_ad("")["readable"] is False


def test_broken_json_ld_is_skipped_not_fatal():
    assert ad_reader.read_ad('<script type="application/ld+json">{not json</script><p>' + "text " * 80)["source"] == "none"


# --- the command ---------------------------------------------------------------------------------------------------

def test_fetch_command_answers_with_fields_missing_and_page_text(monkeypatch):
    monkeypatch.setattr(safe_fetch, "fetch_page", lambda url: safe_fetch.Page(url, ld(title="PM")))
    answer = ad_fill.fetch({"url": "https://jobs.example.com/1"})
    assert answer["ok"] and answer["fields"]["title"] == "PM" and "company" in answer["missing"] and answer["pageText"]


def test_fetch_command_reports_a_refusal_without_fields(monkeypatch):
    def boom(url):
        raise FetchRefused("login_wall", "The page needs a login.")

    monkeypatch.setattr(safe_fetch, "fetch_page", boom)
    assert ad_fill.fetch({"url": "https://www.linkedin.com/posts/x"}) == {"ok": False, "error": "login_wall", "message": "The page needs a login."}
    monkeypatch.setattr(safe_fetch, "fetch_page", lambda url: safe_fetch.Page(url, "<div id='root'></div>"))
    assert ad_fill.fetch({"url": "https://jobs.example.com/1"})["error"] == "unreadable"


def test_the_command_writes_nothing_and_takes_only_a_url(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(safe_fetch, "fetch_page", lambda url: safe_fetch.Page(url, ld(title="PM")))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"url": "https://jobs.example.com/1", "notes": "NOTE-CANARY", "profile": {"fullName": "X"}})))
    assert ad_fill.main(["fetch"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["ok"] and "CANARY" not in out
    assert list(tmp_path.iterdir()) == []
    source = (ROOT / "python" / "job_import" / "ad_fill.py").read_text() + (ROOT / "python" / "job_import" / "ad_reader.py").read_text()
    assert "write_text" not in source and "open(" not in source
