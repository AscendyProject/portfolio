"""Shared helper for loading a job description from a local path or an http(s) URL.

Exposes a single function `load_jd(value, *, fetcher)` and three typed exception
classes that callers catch individually to produce the correct exit-2 messages.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from portfolio.web import _ArticleParser, parse_web_source

# A PDF always begins with the "%PDF-" signature; we detect by bytes, not the
# `.pdf` extension, so a mis-named or extension-less PDF is still handled.
_PDF_MAGIC = b"%PDF-"

# Resource caps for file / PDF JD input (codex IR-001): a malicious or malformed
# PDF must not exhaust memory/CPU. A real job description is far smaller than these.
_JD_MAX_BYTES = 20 * 1024 * 1024  # 20 MiB — file-size ceiling for any --jd file
_PDF_MAX_PAGES = 500  # page-count ceiling for a PDF --jd
_PDF_MAX_TEXT_CHARS = 2 * 1024 * 1024  # extracted-text ceiling (2M chars)


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
        # File branch. Read bytes first so we can sniff a PDF signature; a PDF is
        # extracted to text (best-effort — the JD only drives selection, never
        # grounding), everything else is decoded as UTF-8 as before.
        try:
            size = Path(value).stat().st_size
        except OSError as exc:
            raise JDFileReadError(str(exc)) from exc
        if size > _JD_MAX_BYTES:
            raise JDFileReadError(f"--jd file is too large ({size} bytes > {_JD_MAX_BYTES} limit)")
        try:
            data = Path(value).read_bytes()
        except OSError as exc:
            raise JDFileReadError(str(exc)) from exc
        if data[: len(_PDF_MAGIC)] == _PDF_MAGIC:
            return _extract_pdf_text(data)
        try:
            return data.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise JDFileReadError(str(exc)) from exc


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from a PDF JD (bytes), raising JDFileReadError on any failure.

    `pypdf` is an OPTIONAL dependency (the core install carries no runtime deps),
    imported lazily here: if it is absent we raise a clear, actionable error rather
    than a stack trace. An image-only/scanned PDF yields no text and is rejected so
    the caller never proceeds on an empty JD."""
    try:
        import pypdf
    except ImportError as exc:
        raise JDFileReadError(
            "reading a PDF --jd needs the optional 'pypdf' dependency: "
            "pip install 'portfolio[pdf]' (or convert the PDF to a UTF-8 .txt)"
        ) from exc

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise JDFileReadError("the PDF --jd is encrypted; decrypt it or convert to a UTF-8 .txt")
        n_pages = len(reader.pages)
        if n_pages > _PDF_MAX_PAGES:
            raise JDFileReadError(f"the PDF --jd has too many pages ({n_pages} > {_PDF_MAX_PAGES} limit)")
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            # pypdf has no streaming text API, so a page is materialized by
            # extract_text() before we can measure it. The per-page check below
            # rejects a single oversized page immediately (no accumulation), and
            # the file (20 MiB) + page (500) caps bound the worst single page.
            # Full isolation of extract_text() (subprocess + timeout/rlimit) is a
            # documented follow-up, not done here.
            chunk = page.extract_text() or ""
            if len(chunk) > _PDF_MAX_TEXT_CHARS or total + len(chunk) > _PDF_MAX_TEXT_CHARS:
                raise JDFileReadError(f"the PDF --jd extracted text exceeds the {_PDF_MAX_TEXT_CHARS}-char limit")
            total += len(chunk)
            parts.append(chunk)
        text = "\n".join(parts)
    except JDFileReadError:
        raise  # our own limit/encryption errors are already actionable
    except Exception as exc:  # pypdf raises various errors on malformed PDFs
        raise JDFileReadError(f"could not read the PDF --jd: {exc}") from exc

    text = text.strip()
    if not text:
        raise JDFileReadError("the PDF --jd has no extractable text (scanned/image-only?); convert it to a UTF-8 .txt")
    return text
