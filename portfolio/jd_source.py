"""Shared helper for loading a job description from a local path or an http(s) URL.

Exposes a single function `load_jd(value, *, fetcher)` and three typed exception
classes that callers catch individually to produce the correct exit-2 messages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from portfolio.web import _ArticleParser, parse_web_source


class JDFileReadError(Exception):
    """Raised when the file branch cannot read the JD from disk."""


class JDInvalidURLError(Exception):
    """Raised when parse_web_source rejects the URL (e.g. SSRF guard, bad scheme)."""


class JDFetchError(Exception):
    """Raised when the injected fetcher raises while fetching the JD URL."""


def load_jd(value: str, *, fetcher: Callable[[str], str]) -> str:
    """Load a job description from a local filesystem path or an http(s) URL.

    URL detection is scheme-based: `value` is a URL iff
    `urllib.parse.urlparse(value).scheme.lower()` is ``"http"`` or ``"https"``.
    Any other scheme — including empty, ``ftp``, ``file``, ``notes``, ``c`` —
    routes to the file branch.

    URL branch:
      1. Calls `parse_web_source(value)` (offline SSRF guard). On ``ValueError``,
         raises ``JDInvalidURLError``; the fetcher is NOT called.
      2. Calls ``fetcher(parsed_url)`` exactly once. On ``RuntimeError``, raises
         ``JDFetchError``; original message preserved.
      3. Extracts article text via ``extract_article_evidence`` (title + body).

    File branch:
      Reads ``Path(value)`` with ``encoding="utf-8"``. On ``OSError``,
      ``UnicodeDecodeError``, or ``ValueError``, raises ``JDFileReadError``.

    Does NOT print and does NOT call ``sys.exit``.
    """
    scheme = urlparse(value).scheme.lower()
    if scheme in ("http", "https"):
        # URL branch
        try:
            parsed_url = parse_web_source(value)
        except ValueError as exc:
            raise JDInvalidURLError(str(exc)) from exc

        try:
            html = fetcher(parsed_url)
        except RuntimeError as exc:
            raise JDFetchError(str(exc)) from exc

        # Extract the JD text directly via the article parser. We deliberately do
        # NOT call extract_article_evidence: the JD must never become an Evidence
        # object (it only drives selection). _ArticleParser yields the same
        # title/body the web source uses, without constructing Evidence, and
        # cannot raise IndexError on an empty page (parts is simply empty → "").
        parser = _ArticleParser()
        parser.feed(html)
        parts = [p for p in (parser.title, parser.body) if p]
        return "\n\n".join(parts)
    else:
        # File branch
        try:
            return Path(value).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise JDFileReadError(str(exc)) from exc
