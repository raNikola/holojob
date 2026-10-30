"""Fetch one public web page for the owner, without becoming a way into the home network.

The server reads a URL the owner types. That is a server-side request to an address someone else chose, so it is
limited here: http(s) on the standard ports only, no credentials in the URL, every address the host resolves to must be
public (loopback, private, link-local, carrier-grade NAT such as Tailscale's 100.64/10, and anything else not global are
refused, and so are the redirects that lead there), the connection goes to the address that was checked (a second DNS
answer cannot swap it), redirects are followed by hand, a few at a time, and each hop is checked again. No cookies, no
Authorization, no Referer, no proxy from the environment, no compression; a size cap and one total deadline apply.

Nothing is written. A refusal carries a short code and a message that quotes nothing from the page.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 2_000_000
DEADLINE_SECONDS = 15.0
WAIT_SECONDS = 6.0  # the longest single wait for the server
MAX_REDIRECTS = 3
PORTS = {"http": 80, "https": 443}
REDIRECTS = {301, 302, 303, 307, 308}
HTML_TYPES = ("text/html", "application/xhtml+xml")
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# Names that are never a public site, whatever DNS says about them.
LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".localdomain", ".void", ".intranet", ".corp")
LOGIN_PATH = re.compile(r"/(?:authwall|login|log-in|signin|sign-in|uas/login|checkpoint)(?:/|$|\?)", re.I)


class FetchRefused(Exception):
    """The page was not fetched. `code` names why; `message` is safe to show; `status` is the HTTP status when there was one."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class Page:
    url: str
    html: str


def _refuse(code: str, status: int | None = None) -> FetchRefused:
    messages = {
        "bad_url": "Enter a full web address starting with http:// or https://.",
        "blocked_host": "This address is not allowed: private, local and internal hosts are refused.",
        "unreachable": "The page could not be reached.",
        "timeout": "The page took too long to answer.",
        "too_large": "The page is too large to read.",
        "not_html": "The address does not return a web page.",
        "http_error": "The site refused or did not have the page.",
        "bot_check": "The site asks visitors to pass a bot check before showing the page.",
        "login_wall": "The page needs a login.",
        "redirects": "The address redirects too many times.",
    }
    return FetchRefused(code, messages[code], status)


def check_url(url: str) -> tuple[str, str, int, str]:
    """(scheme, host, port, request target) of a URL the fetcher may use, or FetchRefused."""
    text = str(url or "").strip()
    try:
        parts = urlsplit(text)
        port = parts.port
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        raise _refuse("bad_url") from None
    scheme = parts.scheme.lower()
    if scheme not in PORTS or not host or parts.username is not None or parts.password is not None:
        raise _refuse("bad_url")
    if port not in (None, PORTS[scheme]):
        raise _refuse("blocked_host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise _refuse("bad_url") from None
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES) or ("." not in host and ":" not in host):
        raise _refuse("blocked_host")
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return scheme, host, PORTS[scheme], target


# IPv6 ranges that carry an IPv4 address inside (NAT64, 6to4, Teredo): "global" to the library, but a way to reach
# 127.0.0.1 or 10.x on a network that translates them. No job page lives there.
_TUNNELS = [ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")]


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif any(ip in net for net in _TUNNELS):
            return False
    return ip.is_global and not ip.is_multicast


def resolve_public(host: str, port: int, getaddrinfo=socket.getaddrinfo) -> list[str]:
    """Every address of the host, all of which must be public; FetchRefused otherwise."""
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            addresses = list(dict.fromkeys(info[4][0] for info in getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        except (socket.gaierror, UnicodeError, OSError):
            raise _refuse("unreachable") from None
    if not addresses or not all(_public(a) for a in addresses):
        raise _refuse("blocked_host")
    return addresses


def _request(scheme: str, host: str, ips: list[str], port: int, target: str, deadline: float,
             max_bytes: int = MAX_BYTES) -> tuple[int, dict, bytes]:
    """One GET on a connection to an address that was already checked. (status, lower-cased headers, body)."""
    sock = None
    for ip in ips:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _refuse("timeout")
        try:
            sock = socket.create_connection((ip, port), timeout=min(remaining, 8))
            if scheme == "https":
                sock = tls_context().wrap_socket(sock, server_hostname=host)
            break
        except (OSError, ssl.SSLError):
            sock = None
    if sock is None:
        raise _refuse("unreachable")
    connection = (http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection)(host, port)
    connection.sock = sock  # pinned: http.client does not connect (or resolve) again
    try:
        # One timeout for every wait on this socket (http.client closes it itself when the response ends, so it cannot be
        # adjusted per read): the total deadline is checked between chunks, so it is overrun by one wait at most.
        sock.settimeout(min(max(deadline - time.monotonic(), 0.1), WAIT_SECONDS))
        connection.request("GET", target, headers={
            "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "en;q=0.9", "Accept-Encoding": "identity", "Connection": "close",
        })
        response = connection.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _refuse("timeout")
            chunk = response.read(16384)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise _refuse("too_large")
            chunks.append(chunk)
        return response.status, headers, b"".join(chunks)
    except (socket.timeout, TimeoutError):
        raise _refuse("timeout") from None
    except (OSError, http.client.HTTPException):
        raise _refuse("unreachable") from None
    finally:
        connection.close()


def tls_context() -> ssl.SSLContext:
    """Certificates are checked against certifi's bundle when it is installed (as `requests` did), else the system store."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        return ssl.create_default_context()


def _decode(body: bytes, content_type: str) -> str:
    header = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    meta = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
    name = header.group(1) if header else meta.group(1).decode("ascii", "ignore") if meta else "utf-8"
    try:
        return body.decode(name, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


_CHALLENGE_TITLE = re.compile(rb"<title>\s*just a moment", re.I)


def _bot_check(status: int, headers: dict, body: bytes) -> bool:
    """A Cloudflare-style challenge page: the header Cloudflare sets on it, or its server name plus the "Just a moment" title.
    Recognised only to say so; nothing is done about it (no cookies, no script run, no second try)."""
    if status not in (403, 429):
        return False
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    return "cloudflare" in headers.get("server", "").lower() and _CHALLENGE_TITLE.search(body[:8192]) is not None


def _walled(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if LOGIN_PATH.search(parts.path + ("?" if parts.query else "")):
        return True
    # A post or a feed item is not a job page; LinkedIn shows both only to people who are logged in.
    return host.endswith("linkedin.com") and re.match(r"/(?:posts|feed|pulse)/", parts.path, re.I) is not None


def fetch_page(url: str, *, resolver=socket.getaddrinfo, request=_request, now=time.monotonic,
               max_bytes: int = MAX_BYTES, deadline_seconds: float = DEADLINE_SECONDS) -> Page:
    """The page at `url` (HTML only), or FetchRefused. Every redirect hop goes through the same checks."""
    deadline = now() + deadline_seconds
    current = str(url or "").strip()
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, target = check_url(current)
        if _walled(current):
            raise _refuse("login_wall")
        ips = resolve_public(host, port, resolver)
        status, headers, body = request(scheme, host, ips, port, target, deadline, max_bytes)
        if status in REDIRECTS and headers.get("location"):
            current = urljoin(current, headers["location"])
            continue
        if status >= 300:
            raise _refuse("bot_check" if _bot_check(status, headers, body) else "http_error", status)
        if _walled(current):
            raise _refuse("login_wall")
        content_type = headers.get("content-type", "")
        if not content_type.lower().startswith(HTML_TYPES):
            raise _refuse("not_html", status)
        return Page(current, _decode(body, content_type))
    raise _refuse("redirects")
