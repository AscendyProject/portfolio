"""Tests for the source dispatcher.

No live services: a fake `extractor` is injected via `SourceRequest`, and the
deferred `ResolvedSource.extract()` is only called explicitly. Per
test-conventions, objects are built directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402 — after sys.path setup per test-conventions
from portfolio.sources import (  # noqa: E402 — after sys.path setup per test-conventions
    _HANDLERS,
    ResolvedSource,
    SourceRequest,
    UnsupportedSourceError,
    known_source_types,
    parse_github_source,
    resolve_source,
)


# ---------------------------------------------------------------------------
# resolve_source: github dispatch + deferred extraction
# ---------------------------------------------------------------------------


def _recording_extractor():
    calls: list[dict] = []

    def extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return [Evidence(kind="pr", ref="PR#1")]

    return extractor, calls


def test_github_resolves_subject_and_defers_extraction():
    """`github` resolves subject==author and a deferred extract() that, when
    called, invokes the injected extractor with the parsed owner/repo. The
    extractor must NOT be called until extract() is invoked."""
    extractor, calls = _recording_extractor()
    resolved = resolve_source(
        "github",
        SourceRequest(source="https://github.com/owner/repo", author="alice", extractor=extractor),
    )
    assert isinstance(resolved, ResolvedSource)
    assert resolved.subject == "alice"
    assert calls == []  # nothing extracted yet — resolve_source does no network

    evidence = resolved.extract()
    assert len(calls) == 1
    assert calls[0]["repo"] == "owner/repo"
    assert calls[0]["author"] == "alice"
    assert evidence == [Evidence(kind="pr", ref="PR#1")]


def test_bad_github_url_raises_before_extraction():
    """A bad source URL is rejected (ValueError) by resolve_source, without ever
    invoking the extractor."""
    extractor, calls = _recording_extractor()
    with pytest.raises(ValueError):
        resolve_source(
            "github",
            SourceRequest(source="https://github.com/owner", author="alice", extractor=extractor),  # missing repo
        )
    assert calls == []


def test_github_enterprise_host_resolves_host_qualified():
    """A GitHub Enterprise Server URL resolves to a host-qualified repo spec
    (`host/owner/repo`) passed to the extractor, so `gh --repo` routes to that
    server instead of github.com."""
    extractor, calls = _recording_extractor()
    resolved = resolve_source(
        "github",
        SourceRequest(
            source="https://github.sec.samsung.net/bdp/data-integration-platform",
            author="hunmin1-park",
            extractor=extractor,
        ),
    )
    resolved.extract()
    assert calls[0]["repo"] == "github.sec.samsung.net/bdp/data-integration-platform"
    assert calls[0]["author"] == "hunmin1-park"


def test_github_requires_source_and_author():
    """The github handler raises ValueError when --source or --author is missing."""
    with pytest.raises(ValueError):
        resolve_source("github", SourceRequest(source=None, author="alice"))
    with pytest.raises(ValueError):
        resolve_source("github", SourceRequest(source="https://github.com/owner/repo", author=None))


# ---------------------------------------------------------------------------
# resolve_source: unsupported / unknown types
# ---------------------------------------------------------------------------


def test_known_source_types_includes_github_and_web():
    """All implemented handlers are advertised to the CLI; no unimplemented stubs."""
    types = known_source_types()
    assert "github" in types
    assert "web" in types


def test_web_resolves_and_defers_fetch():
    """`web` resolves subject==author and a deferred extract() that, when called,
    invokes the injected fetcher and produces an article Evidence. The fetcher must
    NOT be called until extract() is invoked."""
    fetched: list[str] = []

    def fake_fetcher(url: str) -> str:
        fetched.append(url)
        return "<title>Hello</title>"

    resolved = resolve_source(
        "web",
        SourceRequest(source="https://blog.example.com/post#x", author="alice", fetcher=fake_fetcher),
    )
    assert resolved.subject == "alice"
    assert fetched == []  # no fetch until extract() is called

    evidence = resolved.extract()
    assert fetched == ["https://blog.example.com/post"]  # normalized (fragment dropped)
    assert evidence == [
        Evidence(
            kind="article", ref="https://blog.example.com/post", url="https://blog.example.com/post", detail="Hello"
        )
    ]


def test_web_bad_url_raises_before_fetch():
    """A bad/internal web URL is rejected by resolve_source without fetching."""
    fetched: list[str] = []

    def fake_fetcher(url: str) -> str:
        fetched.append(url)
        return ""

    with pytest.raises(ValueError):
        resolve_source("web", SourceRequest(source="http://localhost/x", author="alice", fetcher=fake_fetcher))
    assert fetched == []


def test_unknown_type_raises_unsupported():
    """An entirely unknown source type raises UnsupportedSourceError."""
    with pytest.raises(UnsupportedSourceError, match="unknown source type"):
        resolve_source("carrier-pigeon", SourceRequest(source="x", author=None))


# ---------------------------------------------------------------------------
# Registry seam: a new source type is added by registering a handler
# ---------------------------------------------------------------------------


def test_registering_a_handler_makes_a_new_type_resolvable():
    """Registering a handler makes resolve_source dispatch to a new source type
    with no CLI change — the extension seam this task exists to provide."""
    sentinel = ResolvedSource(subject="someone", extract=lambda: [])
    _HANDLERS["fake"] = lambda _request: sentinel
    try:
        # the new type is both resolvable AND advertised to the CLI choices
        assert resolve_source("fake", SourceRequest(source=None, author=None)) is sentinel
        assert "fake" in known_source_types()
    finally:
        del _HANDLERS["fake"]


# ---------------------------------------------------------------------------
# parse_github_source unit cases (moved from test_cli.py)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo/", "owner/repo"),  # trailing slash
        ("https://github.com/owner/repo.git", "owner/repo"),  # .git suffix
        ("http://github.com/owner/repo", "owner/repo"),  # http accepted
        ("https://www.github.com/owner/repo", "owner/repo"),  # www host stays bare
        # GitHub Enterprise Server hosts -> host-qualified (host/owner/repo)
        (
            "https://github.sec.samsung.net/bdp/data-integration-platform",
            "github.sec.samsung.net/bdp/data-integration-platform",
        ),
        ("https://ghe.example.com/owner/repo/", "ghe.example.com/owner/repo"),  # trailing slash
        ("https://ghe.example.com/owner/repo.git", "ghe.example.com/owner/repo"),  # .git suffix
    ],
)
def test_parse_github_source_accepts(url, expected):
    """A clean GitHub(.com or Enterprise) repo URL parses to the repo spec
    (trailing slash / .git / http tolerated; non-github.com hosts host-qualified)."""
    assert parse_github_source(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/owner/repo",  # bare-label host (no dot) -> not a repo host
        "https:///owner/repo",  # empty host
        "https://github.com/owner",  # missing repo
        "https://github.com/owner/repo/pull/1",  # extra path segments -> reject, don't guess
        "https://github.com/owner//repo",  # empty middle segment -> reject, don't collapse
        "https://github.com/owner/%2Frepo",  # %-encoded separator -> not a clean name
        "https://github.com/owner/re po",  # whitespace in name
        "https://github.com/owner/repo?x=1",  # query string -> reject
        "https://github.com/owner/..",  # dot segment -> never a real name
        "https://github.com/./repo",  # dot segment -> never a real name
        "git@github.com:owner/repo.git",  # ssh form, not http(s)
        "owner/repo",  # no scheme/host
        "",  # empty
    ],
)
def test_parse_github_source_rejects(url):
    """A URL that is not a clean GitHub owner/repo is rejected (raise rather than guess)."""
    with pytest.raises(ValueError):
        parse_github_source(url)


# ---------------------------------------------------------------------------
# resolve_source: github-author dispatch
# ---------------------------------------------------------------------------


def _recording_author_extractor():
    calls: list[dict] = []

    def author_extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return [Evidence(kind="pr", ref="org/repo#1")]

    return author_extractor, calls


def test_github_author_in_known_source_types():
    """`known_source_types()` includes `"github-author"` — Done-when: registration."""
    assert "github-author" in known_source_types()


def test_github_author_resolves_subject_equals_author():
    """`resolve_source("github-author", ...)` returns subject == author —
    Done-when: `_HANDLERS["github-author"]` registered, subject == author."""
    author_extractor, _ = _recording_author_extractor()
    resolved = resolve_source(
        "github-author",
        SourceRequest(source=None, author="alice", author_extractor=author_extractor),
    )
    assert isinstance(resolved, ResolvedSource)
    assert resolved.subject == "alice"


def test_github_author_defers_extraction():
    """The extractor is NOT called until `extract()` is invoked —
    Done-when: deferred extraction seam."""
    author_extractor, calls = _recording_author_extractor()
    resolved = resolve_source(
        "github-author",
        SourceRequest(source=None, author="alice", author_extractor=author_extractor),
    )
    assert calls == []  # deferred

    ev = resolved.extract()
    assert len(calls) == 1
    assert calls[0].get("author") == "alice"
    assert ev == [Evidence(kind="pr", ref="org/repo#1")]


def test_github_author_extractor_seam_swappable():
    """The injected `author_extractor` is invoked exactly once when `extract()` is
    called and receives `author` as a keyword argument — Done-when: seam swap."""
    author_extractor, calls = _recording_author_extractor()
    resolved = resolve_source(
        "github-author",
        SourceRequest(source=None, author="a-1", author_extractor=author_extractor),
    )
    resolved.extract()
    assert len(calls) == 1
    assert calls[0].get("author") == "a-1"


def test_github_author_source_ignored():
    """Non-None `source` is accepted but does not reach the extractor as a repo —
    Done-when: `--source` ignored for github-author."""
    author_extractor, calls = _recording_author_extractor()
    resolved = resolve_source(
        "github-author",
        SourceRequest(
            source="https://github.com/owner/repo",
            author="alice",
            author_extractor=author_extractor,
        ),
    )
    resolved.extract()
    # the extractor must not have received 'repo' in its kwargs
    assert "repo" not in calls[0]


@pytest.mark.parametrize(
    "author",
    [
        None,  # missing
        "",  # empty string
        "-",  # bare hyphen (leading/trailing edge case)
        "a b",  # space
        "bad/handle",  # slash
        "bad@handle",  # at-sign
    ],
)
def test_github_author_invalid_author_raises(author):
    """Missing or junk `author` values are rejected with `ValueError` —
    Done-when: handle validation rejects junk inputs."""
    with pytest.raises(ValueError):
        resolve_source("github-author", SourceRequest(source=None, author=author))


@pytest.mark.parametrize("author", ["alice", "a-1"])
def test_github_author_valid_handles_accepted(author):
    """Valid GitHub handles are accepted — Done-when: valid handles pass validation."""
    author_extractor, _ = _recording_author_extractor()
    resolved = resolve_source(
        "github-author",
        SourceRequest(source=None, author=author, author_extractor=author_extractor),
    )
    assert resolved.subject == author
