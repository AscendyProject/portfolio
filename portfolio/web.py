"""Web/blog article source.

Turns an article URL into a single `Evidence(kind="article")`. Three pieces,
split so the network is isolated and the rest is pure/testable:

* `parse_web_source` — validate + normalize the URL (offline; rejects non-http(s)
  and obviously-internal hosts).
* `fetch_html` — the network seam (stdlib `urllib`, timeout, size cap).
* `extract_article_evidence` — pure parser: `<title>` -> Evidence.

SSRF protection here is best-effort and OFFLINE (scheme + IP-literal/localhost
checks). DNS-resolution / redirect-target SSRF and DNS rebinding are out of scope
for this CLI, which runs against a URL the user supplies themselves.
"""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse, urlunparse

from portfolio.model import Evidence

_ALLOWED_SCHEMES = ("http", "https")
_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

_TIMEOUT_SEC = 10
_MAX_BYTES = 2_000_000  # cap the response so a huge/streaming page can't exhaust memory
_USER_AGENT = "portfolio/0.0 (+https://github.com/AscendyProject/portfolio)"


def _host_as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Return the IP address `host` denotes if it is an IP literal — including
    legacy IPv4 forms `socket.inet_aton` accepts (`127.1`, `2130706433`,
    `0177.0.0.1`) which `ipaddress` alone rejects. Returns None for a hostname
    (DNS resolution is out of scope)."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_aton(host))  # legacy dotted/decimal/octal/hex IPv4
    except (OSError, ValueError):
        return None


def parse_web_source(url: str) -> str:
    """Validate and normalize an article URL, or raise ValueError.

    Requires an `http(s)` scheme and a non-empty host, refuses `localhost` and
    private/loopback/link-local/reserved **IP literals** (an offline SSRF guard
    covering canonical and legacy IPv4 forms), and drops any fragment. DNS-based
    SSRF is intentionally not handled here.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"expected an http(s) URL, got {url!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"missing host in {url!r}")
    host = host.rstrip(".")  # an FQDN trailing dot (e.g. `localhost.`) resolves the same
    if not host:
        raise ValueError(f"missing host in {url!r}")
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError(f"refusing internal host {host!r}")
    ip = _host_as_ip(host)
    if ip is not None and not ip.is_global:
        raise ValueError(f"refusing non-public address {host!r}")
    return urlunparse(parsed._replace(fragment=""))  # normalized, fragment dropped


def fetch_html(url: str) -> str:
    """Fetch a page's HTML (the network seam). Times out, caps the response size,
    and raises RuntimeError on any transport/HTTP failure."""
    if urlparse(url).scheme not in _ALLOWED_SCHEMES:  # defense in depth vs file:// etc.
        raise RuntimeError(f"refusing to fetch non-http(s) URL {url!r}")
    request = urllib_request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib_request.urlopen(request, timeout=_TIMEOUT_SEC) as resp:  # noqa: S310 — scheme checked above
            raw = resp.read(_MAX_BYTES + 1)[:_MAX_BYTES]
            charset = resp.headers.get_content_charset() or "utf-8"
    except (urllib_error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"failed to fetch {url!r}: {exc}") from exc
    return raw.decode(charset, errors="replace")


# Tags whose text content is not human-readable article body.
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})
_MAX_CONTEXT_CHARS = 1500  # bound the excerpt so a huge page can't blow up the prompt


class _ArticleParser(HTMLParser):
    """Capture the first <title> and the visible body text, skipping the content
    of script/style/noscript/template elements."""

    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._title_done = False
        self._title_parts: list[str] = []
        # Per-tag open counts (NOT one shared depth) so a stray/mismatched closing
        # tag in malformed HTML can't prematurely end a skip region.
        self._skip_counts: dict[str, int] = {}
        self._body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "title" and not self._title_done:
            self._in_title = True
        elif tag in _SKIP_TAGS:
            self._skip_counts[tag] = self._skip_counts.get(tag, 0) + 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_done = True
        elif tag in _SKIP_TAGS and self._skip_counts.get(tag, 0) > 0:
            self._skip_counts[tag] -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif not any(self._skip_counts.values()):
            self._body_parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self._title_parts).strip()

    @property
    def body(self) -> str:
        # Join text nodes with a space so block-element boundaries don't fuse words
        # ("<p>Hello</p><p>world</p>" -> "Hello world"), then collapse whitespace.
        text = " ".join(" ".join(self._body_parts).split())
        if len(text) > _MAX_CONTEXT_CHARS:
            text = text[:_MAX_CONTEXT_CHARS].rstrip() + "…"
        return text


def extract_article_evidence(url: str, html: str) -> list[Evidence]:
    """Pure parser: turn fetched HTML into a single article Evidence. `detail` is
    the raw `<title>` (the renderer escapes it); `context` is a bounded body
    excerpt fed to the narrative model (not rendered). A missing title yields an
    empty detail rather than an invented one."""
    parser = _ArticleParser()
    parser.feed(html)
    return [Evidence(kind="article", ref=url, url=url, detail=parser.title, context=parser.body)]
