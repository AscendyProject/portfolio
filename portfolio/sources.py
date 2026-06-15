"""Source dispatch: map a `(source_type, source)` spec to the Evidence
extraction for that source.

The CLI is source-agnostic: it hands a `SourceRequest` to `resolve_source`,
which looks the type up in a handler registry and returns a `ResolvedSource`
(a subject plus a *deferred* `extract()` that performs the network work only
when called). Adding a new source type = registering a handler here; the CLI
does not change.

Today only `github` is implemented. `others` is a recognized-but-unimplemented
type that raises `UnsupportedSourceError`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from portfolio.extract import extract_merged_prs
from portfolio.model import Evidence
from portfolio.web import extract_article_evidence, fetch_html, parse_web_source

_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
# owner/repo segments must be clean GitHub names. This rejects %-encoding (e.g.
# %2F), whitespace, and any other character that would otherwise reach
# `gh --repo` as garbage instead of being refused up front.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class UnsupportedSourceError(Exception):
    """A source type that is recognized-but-unimplemented (e.g. `others`) or
    entirely unknown was requested."""


@dataclass(frozen=True)
class SourceRequest:
    """The raw CLI inputs a source handler needs. `extractor` (the `gh` seam) and
    `fetcher` (the web-fetch seam) are injectable so handlers are testable without
    a live `gh`/network; a handler ignores the seam it doesn't use."""

    source: str | None
    author: str | None
    extractor: Callable[..., list[Evidence]] = extract_merged_prs
    fetcher: Callable[[str], str] = fetch_html


@dataclass(frozen=True)
class ResolvedSource:
    """A resolved source: who the portfolio is for, plus a deferred `extract()`
    that performs the (network) extraction only when called."""

    subject: str
    extract: Callable[[], list[Evidence]]


def parse_github_source(url: str) -> str:
    """Parse a GitHub repo URL into the `owner/repo` string the extractor needs.

    Accepts `http(s)://github.com/<owner>/<repo>` with an optional trailing slash
    or `.git` suffix. Anything that is not a clean GitHub `owner/repo` (wrong
    host, missing repo, extra/empty path segments, query/fragment, ssh form, no
    scheme, or names with characters outside `[A-Za-z0-9._-]`) raises
    ValueError — reject rather than guess, so no garbage reaches `gh`.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"expected an http(s) URL, got {url!r}")
    if parsed.netloc.lower() not in _GITHUB_HOSTS:
        raise ValueError(f"not a github.com URL: {url!r}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"unexpected query/fragment in {url!r}")
    # Expect the path to be exactly /<owner>/<repo> (one optional trailing slash).
    # Split WITHOUT dropping empties so `/owner//repo` is rejected, not collapsed.
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    segments = path.split("/")
    if len(segments) != 3 or segments[0] != "":
        raise ValueError(f"expected exactly github.com/<owner>/<repo>, got {url!r}")
    owner, repo = segments[1], segments[2]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        raise ValueError(f"invalid owner/repo name in {url!r}")
    if owner in (".", "..") or repo in (".", ".."):  # dot segments are never real names
        raise ValueError(f"invalid owner/repo name in {url!r}")
    return f"{owner}/{repo}"


def _github_handler(request: SourceRequest) -> ResolvedSource:
    """Resolve a GitHub source: validate the URL + author now, defer extraction."""
    if not request.source:
        raise ValueError("--source is required for --source-type github")
    if not request.author:
        raise ValueError("--author is required for --source-type github")
    repo = parse_github_source(request.source)  # validation; raises ValueError on a bad URL
    author = request.author
    extractor = request.extractor
    return ResolvedSource(subject=author, extract=lambda: extractor(repo=repo, author=author))


def _web_handler(request: SourceRequest) -> ResolvedSource:
    """Resolve a web/blog article source: validate the URL + author now, defer the
    fetch+parse (via the injectable `fetcher`) to `extract()`."""
    if not request.source:
        raise ValueError("--source is required for --source-type web")
    if not request.author:
        raise ValueError("--author is required for --source-type web")
    url = parse_web_source(request.source)  # validation; raises ValueError on a bad/internal URL
    author = request.author
    fetcher = request.fetcher
    return ResolvedSource(subject=author, extract=lambda: extract_article_evidence(url, fetcher(url)))


# Source type -> handler. Register a handler here to add an *implemented* source;
# it immediately becomes CLI-usable (see `known_source_types`) with no CLI change.
SourceHandler = Callable[[SourceRequest], ResolvedSource]
_HANDLERS: dict[str, SourceHandler] = {"github": _github_handler, "web": _web_handler}

# Recognized source types that are intentionally NOT implemented yet — reserved
# in the CLI choices so the user gets "not supported yet" rather than "unknown".
# (Empty now that `web` is implemented; kept as the seam for future stubs.)
_UNIMPLEMENTED_SOURCE_TYPES: tuple[str, ...] = ()


def known_source_types() -> tuple[str, ...]:
    """Every source type the CLI should accept for `--source-type`: all registered
    handlers plus the recognized-but-unimplemented stubs. Because the CLI derives
    its `--source-type` choices from this, registering a handler in `_HANDLERS`
    makes that source CLI-usable without touching the CLI."""
    return (*_HANDLERS.keys(), *_UNIMPLEMENTED_SOURCE_TYPES)


def resolve_source(source_type: str, request: SourceRequest) -> ResolvedSource:
    """Dispatch `request` to the handler for `source_type`.

    Raises `UnsupportedSourceError` for a recognized-but-unimplemented type
    (`others`) or an unknown type. The handler raises `ValueError` for a
    bad/missing source spec. No extraction happens here — call
    `ResolvedSource.extract()` to perform it.
    """
    handler = _HANDLERS.get(source_type)
    if handler is not None:
        return handler(request)
    if source_type in _UNIMPLEMENTED_SOURCE_TYPES:
        raise UnsupportedSourceError(f"source type {source_type!r} is not supported yet")
    raise UnsupportedSourceError(f"unknown source type: {source_type!r}")
