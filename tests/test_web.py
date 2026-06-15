"""Tests for the web/blog article source.

No network: `parse_web_source` and `extract_article_evidence` are pure/offline,
and `fetch_html` is only exercised for its offline scheme guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.web import (  # noqa: E402 — after sys.path setup per test-conventions
    extract_article_evidence,
    fetch_html,
    parse_web_source,
)


# ---------------------------------------------------------------------------
# parse_web_source
# ---------------------------------------------------------------------------


def test_parse_web_source_accepts_normal_article_and_drops_fragment():
    assert parse_web_source("https://blog.example.com/post") == "https://blog.example.com/post"
    # a fragment is dropped; scheme/host/path/query preserved
    assert parse_web_source("http://example.com/a/b?x=1#frag") == "http://example.com/a/b?x=1"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",  # non-http(s) scheme
        "ftp://example.com/x",  # non-http(s) scheme
        "http://localhost/x",  # internal hostname
        "http://LOCALHOST/x",  # uppercase localhost
        "http://localhost./x",  # trailing-dot FQDN localhost
        "http://127.0.0.1/x",  # loopback IP literal
        "http://[::1]/x",  # IPv6 loopback
        "http://0.0.0.0/x",  # unspecified address
        "http://127.1/x",  # legacy short-form loopback
        "http://2130706433/x",  # decimal-int loopback (127.0.0.1)
        "http://0177.0.0.1/x",  # octal loopback
        "http://192.168.0.1/x",  # private IP literal
        "http://169.254.0.1/x",  # link-local IP literal
        "https://",  # missing host
        "//example.com/x",  # scheme-relative -> no scheme
        "not a url",  # no scheme/host
    ],
)
def test_parse_web_source_rejects(url):
    """Non-http(s) or obviously-internal URLs are rejected (offline SSRF guard)."""
    with pytest.raises(ValueError):
        parse_web_source(url)


# ---------------------------------------------------------------------------
# extract_article_evidence (pure)
# ---------------------------------------------------------------------------


def test_extract_article_evidence_uses_title_and_body():
    html = "<html><head><title>  My Great Post </title></head><body>hi there</body></html>"
    ev = extract_article_evidence("https://blog.example.com/post", html)
    assert ev == [
        Evidence(
            kind="article",
            ref="https://blog.example.com/post",
            url="https://blog.example.com/post",
            detail="My Great Post",
            context="hi there",
        )
    ]


def test_body_excerpt_excludes_script_and_style_and_collapses_whitespace():
    """The body excerpt is visible text only — script/style content is skipped —
    and runs of whitespace collapse to single spaces."""
    html = (
        "<html><head><title>T</title><style>.a{color:red}</style></head>"
        "<body><p>Hello\n\n   world</p><script>var secret = 42;</script></body></html>"
    )
    ev = extract_article_evidence("https://blog.example.com/post", html)
    assert ev[0].context == "Hello world"
    assert "secret" not in ev[0].context  # script content excluded
    assert "color" not in ev[0].context  # style content excluded


def test_body_excerpt_separates_block_elements():
    """Text from separate elements is space-joined, not fused (`Helloworld`)."""
    ev = extract_article_evidence("https://blog.example.com/post", "<body><p>Hello</p><p>world</p></body>")
    assert ev[0].context == "Hello world"


def test_body_excerpt_excludes_skipped_content_under_malformed_nesting():
    """A stray/mismatched closing tag must not prematurely end a skip region —
    skipped content stays excluded even under malformed HTML."""
    html = "<body>before<noscript>secret</style>LEAK</noscript>after</body>"
    ev = extract_article_evidence("https://blog.example.com/post", html)
    assert "secret" not in ev[0].context
    assert "LEAK" not in ev[0].context
    assert "before" in ev[0].context and "after" in ev[0].context


def test_body_excerpt_is_truncated():
    """A long body is truncated to the bound with a marker, so the prompt stays bounded."""
    long_text = "word " * 1000  # ~5000 chars
    html = f"<html><body>{long_text}</body></html>"
    ev = extract_article_evidence("https://blog.example.com/post", html)
    assert len(ev[0].context) <= 1501  # ~1500-char bound + the truncation marker
    assert ev[0].context.endswith("…")


def test_extract_article_evidence_no_title_has_empty_detail():
    """No <title> -> empty detail, never an invented one."""
    ev = extract_article_evidence("https://blog.example.com/post", "<html><body>no title here</body></html>")
    assert len(ev) == 1
    assert ev[0].kind == "article"
    assert ev[0].ref == "https://blog.example.com/post"
    assert ev[0].detail == ""


def test_extract_article_evidence_passes_hostile_title_through_raw():
    """A title with Markdown-significant characters is passed through unescaped —
    the renderer is responsible for escaping, not the extractor."""
    html = "<title>Pwn] [x](http://evil) `code`</title>"
    ev = extract_article_evidence("https://blog.example.com/post", html)
    assert ev[0].detail == "Pwn] [x](http://evil) `code`"


# ---------------------------------------------------------------------------
# fetch_html offline guard (no network)
# ---------------------------------------------------------------------------


def test_context_is_not_rendered():
    """The body excerpt (`context`) is narration material only — it must never leak
    into the rendered Markdown, which shows ref/url/detail."""
    from portfolio.model import Claim, Portfolio
    from portfolio.render import render_markdown

    url = "https://blog.example.com/post"
    ev = extract_article_evidence(url, "<html><head><title>Post</title></head><body>SECRET_BODY_TEXT</body></html>")
    assert "SECRET_BODY_TEXT" in ev[0].context  # captured as context
    portfolio = Portfolio(
        subject="alice",
        evidence=ev,
        claims=[Claim(text="Wrote Post", evidence_refs=[url], confidence=0.8, grounded=True)],
    )
    out = render_markdown(portfolio)
    assert "Post" in out  # the title (detail) is rendered
    assert "SECRET_BODY_TEXT" not in out  # the context is NOT rendered


def test_fetch_html_refuses_non_http_scheme():
    """Defense in depth: fetch_html refuses a non-http(s) URL without touching the
    network."""
    with pytest.raises(RuntimeError):
        fetch_html("file:///etc/passwd")
