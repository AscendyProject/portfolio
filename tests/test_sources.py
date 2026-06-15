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
            SourceRequest(source="https://gitlab.com/owner/repo", author="alice", extractor=extractor),
        )
    assert calls == []


def test_github_requires_source_and_author():
    """The github handler raises ValueError when --source or --author is missing."""
    with pytest.raises(ValueError):
        resolve_source("github", SourceRequest(source=None, author="alice"))
    with pytest.raises(ValueError):
        resolve_source("github", SourceRequest(source="https://github.com/owner/repo", author=None))


# ---------------------------------------------------------------------------
# resolve_source: unsupported / unknown types
# ---------------------------------------------------------------------------


def test_others_is_recognized_but_unsupported():
    """`others` is in KNOWN_SOURCE_TYPES but has no handler -> UnsupportedSourceError
    with a "not supported yet" message."""
    assert "others" in known_source_types()
    with pytest.raises(UnsupportedSourceError, match="not supported yet"):
        resolve_source("others", SourceRequest(source="https://example.com/blog", author=None))


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
    ],
)
def test_parse_github_source_accepts(url, expected):
    """A clean GitHub repo URL parses to owner/repo (trailing slash / .git / http tolerated)."""
    assert parse_github_source(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/owner/repo",  # wrong host
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
