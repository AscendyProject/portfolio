"""Tests for the Bitbucket source handler in portfolio/sources.py.

Covers:
- `"bitbucket"` registration in known_source_types() / _HANDLERS
- Dispatch resolves subject == author, defers extraction
- Missing --source / --author raises ValueError
- parse_bitbucket_source: acceptance (canonical URL, .git suffix, trailing slash)
- parse_bitbucket_source: SSRF rejection (IP-literal incl. legacy/hex/octal forms,
  userinfo, explicit port, non-http(s), query/fragment, single-label host, missing
  host, empty/dot/dotdot segments, wrong segment count)
- Host-qualified return shape (bitbucket.org/<workspace>/<repo>)
- Extractor receives correct workspace, repo, author, limit

No live network or credentials are used — a fake extractor is injected via SourceRequest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.model import Evidence  # noqa: E402
from portfolio.sources import (  # noqa: E402
    ResolvedSource,
    SourceRequest,
    known_source_types,
    parse_bitbucket_source,
    resolve_source,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_bb_extractor(**kwargs) -> list[Evidence]:
    return [Evidence(kind="pr", ref="bitbucket.org/ws/repo#1", url="https://bitbucket.org/ws/repo/pull-requests/1")]


def _recording_bb_extractor():
    calls: list[dict] = []

    def extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return [Evidence(kind="pr", ref="bitbucket.org/ws/repo#1")]

    return extractor, calls


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_bitbucket_in_known_source_types():
    """`known_source_types()` includes `"bitbucket"` — Done-when: handler registered."""
    assert "bitbucket" in known_source_types()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_bitbucket_resolves_subject_equals_author():
    """`resolve_source("bitbucket", ...)` returns subject == author."""
    extractor, _ = _recording_bb_extractor()
    resolved = resolve_source(
        "bitbucket",
        SourceRequest(
            source="https://bitbucket.org/workspace/myrepo",
            author="alice",
            bitbucket_extractor=extractor,
        ),
    )
    assert isinstance(resolved, ResolvedSource)
    assert resolved.subject == "alice"


def test_bitbucket_defers_extraction():
    """The extractor is NOT called until `extract()` is invoked."""
    extractor, calls = _recording_bb_extractor()
    resolved = resolve_source(
        "bitbucket",
        SourceRequest(
            source="https://bitbucket.org/workspace/myrepo",
            author="alice",
            bitbucket_extractor=extractor,
        ),
    )
    assert calls == []  # not called yet
    resolved.extract()
    assert len(calls) == 1


def test_bitbucket_extractor_receives_workspace_repo_author():
    """The extractor receives `workspace`, `repo`, and `author` as kwargs."""
    extractor, calls = _recording_bb_extractor()
    resolve_source(
        "bitbucket",
        SourceRequest(
            source="https://bitbucket.org/myworkspace/myrepo",
            author="alice",
            bitbucket_extractor=extractor,
        ),
    ).extract()
    assert calls[0]["workspace"] == "myworkspace"
    assert calls[0]["repo"] == "myrepo"
    assert calls[0]["author"] == "alice"


def test_bitbucket_threads_limit_to_extractor():
    """SourceRequest.limit reaches the bitbucket extractor."""
    extractor, calls = _recording_bb_extractor()
    resolve_source(
        "bitbucket",
        SourceRequest(
            source="https://bitbucket.org/ws/repo",
            author="alice",
            bitbucket_extractor=extractor,
            limit=50,
        ),
    ).extract()
    assert calls[0]["limit"] == 50


def test_bitbucket_missing_source_raises():
    """Missing --source raises ValueError before extraction."""
    with pytest.raises(ValueError, match="--source"):
        resolve_source("bitbucket", SourceRequest(source=None, author="alice"))


def test_bitbucket_missing_author_raises():
    """Missing --author raises ValueError before extraction."""
    extractor, calls = _recording_bb_extractor()
    with pytest.raises(ValueError, match="--author"):
        resolve_source(
            "bitbucket",
            SourceRequest(source="https://bitbucket.org/ws/repo", author=None, bitbucket_extractor=extractor),
        )
    assert calls == []


def test_bitbucket_bad_url_raises_before_extraction():
    """A bad Bitbucket URL is rejected by resolve_source without invoking the extractor."""
    extractor, calls = _recording_bb_extractor()
    with pytest.raises(ValueError):
        resolve_source(
            "bitbucket",
            SourceRequest(
                source="https://127.0.0.1/ws/repo",
                author="alice",
                bitbucket_extractor=extractor,
            ),
        )
    assert calls == []


# ---------------------------------------------------------------------------
# parse_bitbucket_source — acceptance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # canonical
        ("https://bitbucket.org/workspace/repo", "bitbucket.org/workspace/repo"),
        # trailing slash
        ("https://bitbucket.org/workspace/repo/", "bitbucket.org/workspace/repo"),
        # .git suffix
        ("https://bitbucket.org/workspace/repo.git", "bitbucket.org/workspace/repo"),
        # http accepted
        ("http://bitbucket.org/workspace/repo", "bitbucket.org/workspace/repo"),
        # names with dots/hyphens/underscores
        ("https://bitbucket.org/my-org/my_repo.v2", "bitbucket.org/my-org/my_repo.v2"),
    ],
)
def test_parse_bitbucket_source_accepts(url, expected):
    """A clean Bitbucket repo URL parses to the expected host-qualified key."""
    assert parse_bitbucket_source(url) == expected


def test_parse_bitbucket_source_host_qualified():
    """parse_bitbucket_source always returns a host-qualified key (bitbucket.org/...)."""
    result = parse_bitbucket_source("https://bitbucket.org/acme/widgets")
    assert result.startswith("bitbucket.org/")
    assert result == "bitbucket.org/acme/widgets"


# ---------------------------------------------------------------------------
# parse_bitbucket_source — SSRF rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        # IP-literal hosts
        "https://127.0.0.1/ws/repo",
        "https://169.254.169.254/ws/repo",
        "https://10.0.0.1/ws/repo",
        "https://[::1]/ws/repo",
        "https://[fe80::1]/ws/repo",
        # Legacy IPv4 (inet_aton accepts, ipaddress does not)
        "https://127.1/ws/repo",
        "https://0177.0.0.1/ws/repo",
        "https://0x7f.0.0.1/ws/repo",
        # userinfo / authority spoofing
        "https://bitbucket.org@evil.example/ws/repo",
        "https://user@bitbucket.org/ws/repo",
        # explicit port
        "https://bitbucket.org:443/ws/repo",
        "https://bitbucket.org:8080/ws/repo",
        "https://bitbucket.org:/ws/repo",
        # non-http(s) scheme
        "git@bitbucket.org:ws/repo.git",
        "ssh://git@bitbucket.org/ws/repo.git",
        "ftp://bitbucket.org/ws/repo",
        # single-label host (no dot)
        "https://localhost/ws/repo",
        "https://bitbucket/ws/repo",
        # missing host
        "https:///ws/repo",
        # query / fragment
        "https://bitbucket.org/ws/repo?branch=main",
        "https://bitbucket.org/ws/repo#readme",
        # wrong number of path segments (not exactly 2)
        "https://bitbucket.org/only-one",
        "https://bitbucket.org/",
        "https://bitbucket.org",
        "https://bitbucket.org/a/b/c",  # 3 segments
        # empty segment
        "https://bitbucket.org/ws//repo",
        # dot/dotdot segments
        "https://bitbucket.org/./repo",
        "https://bitbucket.org/../repo",
        "https://bitbucket.org/ws/..",
        "https://bitbucket.org/ws/.",
    ],
)
def test_parse_bitbucket_source_rejects(url):
    """A bad Bitbucket URL raises ValueError — reject rather than guess."""
    with pytest.raises(ValueError):
        parse_bitbucket_source(url)


def test_parse_bitbucket_source_ssrf_error_single_line():
    """SSRF rejection error message is single-line (no traceback leak)."""
    with pytest.raises(ValueError) as exc_info:
        parse_bitbucket_source("https://127.0.0.1/ws/repo")
    assert "\n" not in str(exc_info.value)
