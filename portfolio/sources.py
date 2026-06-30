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

import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from portfolio.extract import extract_authored_prs, extract_merged_prs
from portfolio.extract_gitlab import extract_authored_mrs, extract_merged_mrs
from portfolio.model import Evidence, Portfolio
from portfolio.web import extract_article_evidence, fetch_html, parse_web_source

# github.com is special-cased only in the *return format* (bare `owner/repo`);
# any other syntactically valid host is treated as a GitHub Enterprise Server
# and returned host-qualified. We cannot tell a GHES host from a non-GitHub host
# (e.g. gitlab.com) by name alone, so host *validity* is left to `gh`, which
# fails with a clear auth error for a host it is not logged into.
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
# gitlab.com is special-cased in the *return format* (bare namespace/project);
# any other host is returned host-qualified for self-managed GitLab.
_GITLAB_HOSTS = frozenset({"gitlab.com", "www.gitlab.com"})
# owner/repo segments must be clean GitHub names. This rejects %-encoding (e.g.
# %2F), whitespace, and any other character that would otherwise reach
# `gh --repo` as garbage instead of being refused up front.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# A syntactically valid DNS hostname: dot-separated labels of [A-Za-z0-9-], each
# 1–63 chars with no leading/trailing hyphen. Guards against junk (spaces,
# slashes, empty labels) reaching `gh` as a host. Requires at least one dot so a
# bare label (e.g. `localhost`) is not mistaken for a repo host.
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
# GitHub handle: alphanumeric + hyphens only. Leading/trailing hyphens are not
# valid GitHub usernames; we also reject the bare "-" single-char handle.
_AUTHOR_RE = re.compile(r"^[A-Za-z0-9-]+$")
# GitLab username: alphanumeric + hyphens, underscores, and dots. Wider than
# GitHub (GitLab legally allows "." and "_" in usernames).
_GITLAB_AUTHOR_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class UnsupportedSourceError(Exception):
    """A source type that is recognized-but-unimplemented (e.g. `others`) or
    entirely unknown was requested."""


@dataclass(frozen=True)
class SourceRequest:
    """The raw CLI inputs a source handler needs. `extractor` (the `gh` seam),
    `fetcher` (the web-fetch seam), and `author_extractor` (the author-wide `gh`
    seam) are injectable so handlers are testable without a live `gh`/network; a
    handler ignores the seams it doesn't use."""

    source: str | None
    author: str | None
    extractor: Callable[..., list[Evidence]] = extract_merged_prs
    fetcher: Callable[[str], str] = fetch_html
    author_extractor: Callable[..., list[Evidence]] = extract_authored_prs
    # Max merged PRs to pull for the github / github-author sources (the `gh`
    # --limit). Default mirrors the extractors' own default; the CLI can raise it
    # to capture more of a prolific author's history. Ignored by web/portfolio.
    limit: int = 100
    # Injectable extractors for the gitlab / gitlab-author source types (the
    # `glab` seam). Defaults to the module-level functions; tests substitute
    # fakes here so the full suite runs without a real `glab` binary.
    gitlab_extractor: Callable[..., list[Evidence]] = extract_merged_mrs
    gitlab_author_extractor: Callable[..., list[Evidence]] = extract_authored_mrs


@dataclass(frozen=True)
class ResolvedSource:
    """A resolved source: who the portfolio is for, plus a deferred `extract()`
    that performs the (network) extraction only when called."""

    subject: str
    extract: Callable[[], list[Evidence]]
    prebuilt: "Portfolio | None" = None


def parse_github_source(url: str) -> str:
    """Parse a GitHub repo URL into the repo spec the extractor (`gh`) needs.

    Accepts `http(s)://<host>/<owner>/<repo>` with an optional trailing slash or
    `.git` suffix, for github.com **or a GitHub Enterprise Server host**. For
    github.com the result is the bare `owner/repo` (unchanged); for any other
    host it is `host/owner/repo` — the `[HOST/]OWNER/REPO` form `gh --repo`
    accepts, so the call routes to that server.

    Anything that is not a clean repo URL (junk/missing host, missing repo,
    extra/empty path segments, query/fragment, ssh form, no scheme, or names with
    characters outside `[A-Za-z0-9._-]`) raises ValueError — reject rather than
    guess, so no garbage reaches `gh`. Whether a syntactically valid host is a
    real GitHub instance is left to `gh` (it errors clearly for an unknown host).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"expected an http(s) URL, got {url!r}")
    # Reject userinfo (e.g. user@host or github.com@evil.example — authority spoofing)
    if parsed.username is not None:
        raise ValueError(f"userinfo in URL authority is not allowed: {url!r}")
    # Reject explicit port — inspect raw netloc directly because urlparse(...).port
    # is None for an empty ":" and raises ValueError for malformed ":abc"/":99999".
    netloc = parsed.netloc
    # Strip IPv6 brackets so "[::1]" → "" and "[::1]:port" → ":port"
    if netloc.startswith("["):
        close = netloc.find("]")
        if close >= 0:
            netloc = netloc[close + 1 :]
    if ":" in netloc:
        raise ValueError(f"explicit port is not allowed in {url!r}")
    host = parsed.hostname  # lowercased, brackets/port/userinfo stripped by urlparse
    if not host:
        raise ValueError(f"invalid or missing host in {url!r}")
    # Reject canonical IP-literal hosts (127.0.0.1, ::1 after bracket-strip, etc.)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(f"IP-literal hosts are not allowed in {url!r}")
    # Reject legacy and mixed-base IPv4 forms that socket.inet_aton accepts but
    # ipaddress does not (127.1, 0177.0.0.1, 0x7f.0.0.1, 127.0x1, 127.0x0.1, …)
    # inet_aton mirrors the C resolver's full IPv4 grammar (decimal/octal/hex parts,
    # 1-/2-/3-/4-part forms, and any mix), so it rejects real DNS names with OSError.
    try:
        socket.inet_aton(host)
    except OSError:
        pass
    else:
        raise ValueError(f"IP-literal hosts are not allowed in {url!r}")
    if not _HOST_RE.match(host):
        raise ValueError(f"invalid or missing host in {url!r}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"unexpected query/fragment in {url!r}")
    # Expect the path to be exactly /<owner>/<repo> (one optional trailing slash).
    # Split WITHOUT dropping empties so `/owner//repo` is rejected, not collapsed.
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    segments = path.split("/")
    if len(segments) != 3 or segments[0] != "":
        raise ValueError(f"expected exactly <host>/<owner>/<repo>, got {url!r}")
    owner, repo = segments[1], segments[2]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        raise ValueError(f"invalid owner/repo name in {url!r}")
    if owner in (".", "..") or repo in (".", ".."):  # dot segments are never real names
        raise ValueError(f"invalid owner/repo name in {url!r}")
    # github.com -> bare owner/repo (unchanged); GHES -> host-qualified for `gh --repo`.
    if host in _GITHUB_HOSTS:
        return f"{owner}/{repo}"
    return f"{host}/{owner}/{repo}"


def parse_gitlab_source(url: str) -> str:
    """Parse a GitLab project URL into the project spec ``glab --repo`` needs.

    Accepts ``http(s)://<host>/<namespace>[/<subgroup>...]/<project>`` with an
    optional trailing slash or ``.git`` suffix.  Nested namespaces
    (``group/subgroup/project``) are supported — the path must have **at least
    two** non-empty segments after the host.

    For ``gitlab.com`` (and ``www.gitlab.com``) the result is the bare
    ``<namespace>/<project-path>`` (e.g. ``group/subgroup/project``).  For any
    other host (self-managed GitLab) it is ``<host>/<namespace>/<project-path>``
    — the form ``glab --repo`` accepts, so the call routes to that server.

    Applies the same SSRF hardening as ``parse_github_source``:
    rejects IP-literal hosts (canonical ``ipaddress`` + legacy ``inet_aton``
    forms), userinfo (``user@host``), explicit ports, non-http(s) schemes,
    query strings, fragments, single-label hosts, and empty/``./..`` path
    segments.  Raises ``ValueError`` on any violation.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"expected an http(s) URL, got {url!r}")
    # Reject userinfo (authority spoofing)
    if parsed.username is not None:
        raise ValueError(f"userinfo in URL authority is not allowed: {url!r}")
    # Reject explicit port (inspect raw netloc — same technique as parse_github_source)
    netloc = parsed.netloc
    if netloc.startswith("["):
        close = netloc.find("]")
        if close >= 0:
            netloc = netloc[close + 1 :]
    if ":" in netloc:
        raise ValueError(f"explicit port is not allowed in {url!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"invalid or missing host in {url!r}")
    # Reject canonical IP-literal hosts
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(f"IP-literal hosts are not allowed in {url!r}")
    # Reject legacy / mixed-base IPv4 forms (mirrors parse_github_source)
    try:
        socket.inet_aton(host)
    except OSError:
        pass
    else:
        raise ValueError(f"IP-literal hosts are not allowed in {url!r}")
    if not _HOST_RE.match(host):
        raise ValueError(f"invalid or missing host in {url!r}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"unexpected query/fragment in {url!r}")
    # Require at least two non-empty path segments (owner + project).
    # Keep empties from split so "/owner//project" is rejected, not collapsed.
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    raw_segments = path.split("/")
    if not raw_segments or raw_segments[0] != "":
        raise ValueError(f"expected path starting with /, got {url!r}")
    parts = raw_segments[1:]  # strip leading empty string from the leading "/"
    if len(parts) < 2 or any(p == "" for p in parts):
        raise ValueError(f"expected at least <owner>/<project> in path, got {url!r}")
    # Strip .git suffix from the final segment
    final = parts[-1]
    if final.endswith(".git"):
        parts = list(parts)
        parts[-1] = final[:-4]
    # Validate every segment
    for p in parts:
        if not _NAME_RE.match(p) or p in (".", ".."):
            raise ValueError(f"invalid path segment {p!r} in {url!r}")
    project_path = "/".join(parts)
    if host in _GITLAB_HOSTS:
        return project_path
    return f"{host}/{project_path}"


def _validate_gitlab_author(author: str | None) -> str:
    """Validate a GitLab username: non-empty, matches ``[A-Za-z0-9._-]+``.

    GitLab usernames may legally include dots and underscores (unlike GitHub
    handles, which are restricted to ``[A-Za-z0-9-]+``). Raises ``ValueError``
    on any violation.
    """
    if not author:
        raise ValueError("--author is required for --source-type gitlab-author")
    if not _GITLAB_AUTHOR_RE.match(author):
        raise ValueError(
            f"invalid GitLab username {author!r}: only letters, digits, hyphens, dots, and underscores are allowed"
        )
    return author


def _gitlab_handler(request: SourceRequest) -> ResolvedSource:
    """Resolve a project-scoped GitLab source: validate URL + author now, defer extraction."""
    if not request.source:
        raise ValueError("--source is required for --source-type gitlab")
    if not request.author:
        raise ValueError("--author is required for --source-type gitlab")
    project = parse_gitlab_source(request.source)
    author = request.author
    extractor = request.gitlab_extractor
    limit = request.limit
    return ResolvedSource(subject=author, extract=lambda: extractor(project=project, author=author, limit=limit))


def _gitlab_author_handler(request: SourceRequest) -> ResolvedSource:
    """Resolve an author-wide GitLab source: validate author now, defer extraction.
    ``--source`` is optional and ignored for this source type."""
    author = _validate_gitlab_author(request.author)
    extractor = request.gitlab_author_extractor
    limit = request.limit
    return ResolvedSource(subject=author, extract=lambda: extractor(author=author, limit=limit))


def _github_handler(request: SourceRequest) -> ResolvedSource:
    """Resolve a GitHub source: validate the URL + author now, defer extraction."""
    if not request.source:
        raise ValueError("--source is required for --source-type github")
    if not request.author:
        raise ValueError("--author is required for --source-type github")
    repo = parse_github_source(request.source)  # validation; raises ValueError on a bad URL
    author = request.author
    extractor = request.extractor
    limit = request.limit
    return ResolvedSource(subject=author, extract=lambda: extractor(repo=repo, author=author, limit=limit))


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


def _validate_github_author(author: str | None) -> str:
    """Validate a GitHub handle: non-empty, matches [A-Za-z0-9-]+, no leading or
    trailing hyphens. Raises ValueError on any violation."""
    if not author:
        raise ValueError("--author is required for --source-type github-author")
    if not _AUTHOR_RE.match(author):
        raise ValueError(f"invalid GitHub handle {author!r}: only letters, digits, and hyphens are allowed")
    if author.startswith("-") or author.endswith("-"):
        raise ValueError(f"invalid GitHub handle {author!r}: leading/trailing hyphens are not allowed")
    return author


def _github_author_handler(request: SourceRequest) -> ResolvedSource:
    """Resolve an author-wide GitHub source: validate the author now, defer
    extraction. `--source` is optional and ignored for this source type."""
    author = _validate_github_author(request.author)
    author_extractor = request.author_extractor
    limit = request.limit
    return ResolvedSource(subject=author, extract=lambda: author_extractor(author=author, limit=limit))


def _portfolio_handler(request: SourceRequest) -> ResolvedSource:
    """Resolve a portfolio JSON file source: validate path now, defer load to prebuilt."""
    from pathlib import Path as _Path

    from portfolio.store import PortfolioStoreError, portfolio_from_json

    if not request.source:
        raise ValueError("--source is required for --source-type portfolio")
    path = _Path(request.source)
    if not path.exists():
        raise ValueError(f"portfolio file not found: {request.source!r}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        # UnicodeDecodeError (invalid UTF-8) is a UnicodeError, NOT an OSError —
        # catch it so a malformed file produces a clean exit-2 message, not a traceback.
        raise ValueError(f"cannot read portfolio file {request.source!r}: {exc}") from exc
    try:
        loaded = portfolio_from_json(text)
    except PortfolioStoreError as exc:
        raise ValueError(f"invalid portfolio JSON in {request.source!r}: {exc}") from exc
    # prebuilt carries the loaded Portfolio; extract() is a no-op placeholder
    return ResolvedSource(subject=loaded.subject, extract=lambda: [], prebuilt=loaded)


# Source type -> handler. Register a handler here to add an *implemented* source;
# it immediately becomes CLI-usable (see `known_source_types`) with no CLI change.
SourceHandler = Callable[[SourceRequest], ResolvedSource]
_HANDLERS: dict[str, SourceHandler] = {
    "github": _github_handler,
    "web": _web_handler,
    "github-author": _github_author_handler,
    "portfolio": _portfolio_handler,
    "gitlab": _gitlab_handler,
    "gitlab-author": _gitlab_author_handler,
}

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
