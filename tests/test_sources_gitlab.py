"""Tests for the GitLab source handlers in portfolio/sources.py.

Covers:
- `gitlab` and `gitlab-author` registration in known_source_types() / _HANDLERS
- Dispatch resolves subject == author, defers extraction
- Missing --source / --author raises ValueError
- parse_gitlab_source: acceptance (nested namespace, self-managed host, .git suffix)
- parse_gitlab_source: SSRF rejection (IP-literal, userinfo, explicit port, scheme,
  query/fragment, empty/dot/dotdot segments)
- Host-qualified return form for non-gitlab.com hosts

No live `glab` is used — a fake extractor is injected via SourceRequest.
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
    parse_gitlab_source,
    resolve_source,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_gitlab_extractor(**kwargs) -> list[Evidence]:
    return [Evidence(kind="pr", ref="group/project!1", url="https://gitlab.com/group/project/-/merge_requests/1")]


def _recording_gitlab_extractor():
    calls: list[dict] = []

    def extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return [Evidence(kind="pr", ref="group/project!1")]

    return extractor, calls


def _recording_gitlab_author_extractor():
    calls: list[dict] = []

    def extractor(**kwargs) -> list[Evidence]:
        calls.append(kwargs)
        return [Evidence(kind="pr", ref="group/project!1")]

    return extractor, calls


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_gitlab_in_known_source_types():
    """`known_source_types()` includes `"gitlab"` — Done-when: handler registered."""
    assert "gitlab" in known_source_types()


def test_gitlab_author_in_known_source_types():
    """`known_source_types()` includes `"gitlab-author"` — Done-when: handler registered."""
    assert "gitlab-author" in known_source_types()


# ---------------------------------------------------------------------------
# gitlab dispatch
# ---------------------------------------------------------------------------


def test_gitlab_resolves_subject_equals_author():
    """`resolve_source("gitlab", ...)` returns subject == author."""
    extractor, _ = _recording_gitlab_extractor()
    resolved = resolve_source(
        "gitlab",
        SourceRequest(
            source="https://gitlab.com/group/project",
            author="alice",
            gitlab_extractor=extractor,
        ),
    )
    assert isinstance(resolved, ResolvedSource)
    assert resolved.subject == "alice"


def test_gitlab_defers_extraction():
    """The extractor is NOT called until `extract()` is invoked."""
    extractor, calls = _recording_gitlab_extractor()
    resolved = resolve_source(
        "gitlab",
        SourceRequest(
            source="https://gitlab.com/group/project",
            author="alice",
            gitlab_extractor=extractor,
        ),
    )
    assert calls == []  # not called yet

    resolved.extract()
    assert len(calls) == 1


def test_gitlab_extractor_receives_project_and_author():
    """The extractor receives `project` (parsed URL) and `author` as kwargs."""
    extractor, calls = _recording_gitlab_extractor()
    resolved = resolve_source(
        "gitlab",
        SourceRequest(
            source="https://gitlab.com/group/project",
            author="alice",
            gitlab_extractor=extractor,
        ),
    )
    resolved.extract()
    assert calls[0]["project"] == "group/project"
    assert calls[0]["author"] == "alice"


def test_gitlab_nested_namespace_project_passed_to_extractor():
    """A nested namespace URL passes the full project path to the extractor."""
    extractor, calls = _recording_gitlab_extractor()
    resolve_source(
        "gitlab",
        SourceRequest(
            source="https://gitlab.com/group/subgroup/project",
            author="alice",
            gitlab_extractor=extractor,
        ),
    ).extract()
    assert calls[0]["project"] == "group/subgroup/project"


def test_gitlab_missing_source_raises():
    """Missing --source raises ValueError before extraction."""
    with pytest.raises(ValueError, match="--source"):
        resolve_source("gitlab", SourceRequest(source=None, author="alice"))


def test_gitlab_missing_author_raises():
    """Missing --author raises ValueError before extraction."""
    extractor, calls = _recording_gitlab_extractor()
    with pytest.raises(ValueError, match="--author"):
        resolve_source(
            "gitlab",
            SourceRequest(source="https://gitlab.com/group/project", author=None, gitlab_extractor=extractor),
        )
    assert calls == []


def test_gitlab_bad_url_raises_before_extraction():
    """A bad GitLab URL is rejected by resolve_source without invoking the extractor."""
    extractor, calls = _recording_gitlab_extractor()
    with pytest.raises(ValueError):
        resolve_source(
            "gitlab",
            SourceRequest(
                source="https://gitlab.com/only-one-segment",
                author="alice",
                gitlab_extractor=extractor,
            ),
        )
    assert calls == []


def test_gitlab_threads_limit_to_extractor():
    """SourceRequest.limit reaches the gitlab extractor."""
    extractor, calls = _recording_gitlab_extractor()
    resolve_source(
        "gitlab",
        SourceRequest(
            source="https://gitlab.com/g/p",
            author="alice",
            gitlab_extractor=extractor,
            limit=200,
        ),
    ).extract()
    assert calls[0]["limit"] == 200


# ---------------------------------------------------------------------------
# gitlab-author dispatch
# ---------------------------------------------------------------------------


def test_gitlab_author_resolves_subject_equals_author():
    """`resolve_source("gitlab-author", ...)` returns subject == author."""
    extractor, _ = _recording_gitlab_author_extractor()
    resolved = resolve_source(
        "gitlab-author",
        SourceRequest(source=None, author="alice", gitlab_author_extractor=extractor),
    )
    assert isinstance(resolved, ResolvedSource)
    assert resolved.subject == "alice"


def test_gitlab_author_defers_extraction():
    """The extractor is NOT called until `extract()` is invoked."""
    extractor, calls = _recording_gitlab_author_extractor()
    resolved = resolve_source(
        "gitlab-author",
        SourceRequest(source=None, author="alice", gitlab_author_extractor=extractor),
    )
    assert calls == []

    resolved.extract()
    assert len(calls) == 1
    assert calls[0]["author"] == "alice"


def test_gitlab_author_source_is_optional_and_ignored():
    """Non-None `source` is accepted but does not reach the extractor."""
    extractor, calls = _recording_gitlab_author_extractor()
    resolve_source(
        "gitlab-author",
        SourceRequest(
            source="https://gitlab.com/group/project",
            author="alice",
            gitlab_author_extractor=extractor,
        ),
    ).extract()
    assert "project" not in calls[0]


def test_gitlab_author_missing_author_raises():
    """Missing or empty --author raises ValueError."""
    with pytest.raises(ValueError):
        resolve_source("gitlab-author", SourceRequest(source=None, author=None))
    with pytest.raises(ValueError):
        resolve_source("gitlab-author", SourceRequest(source=None, author=""))


def test_gitlab_author_threads_limit_to_extractor():
    """SourceRequest.limit reaches the gitlab-author extractor."""
    extractor, calls = _recording_gitlab_author_extractor()
    resolve_source(
        "gitlab-author",
        SourceRequest(source=None, author="alice", gitlab_author_extractor=extractor, limit=150),
    ).extract()
    assert calls[0]["limit"] == 150


# ---------------------------------------------------------------------------
# parse_gitlab_source — acceptance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # gitlab.com → bare project path (no host prefix)
        ("https://gitlab.com/owner/repo", "owner/repo"),
        ("https://gitlab.com/owner/repo/", "owner/repo"),  # trailing slash
        ("https://gitlab.com/owner/repo.git", "owner/repo"),  # .git suffix
        ("http://gitlab.com/owner/repo", "owner/repo"),  # http accepted
        ("https://www.gitlab.com/owner/repo", "owner/repo"),  # www.gitlab.com
        # nested namespaces (key GitLab feature) → bare
        ("https://gitlab.com/group/subgroup/project", "group/subgroup/project"),
        ("https://gitlab.com/group/subgroup/project/", "group/subgroup/project"),
        ("https://gitlab.com/group/sub1/sub2/project", "group/sub1/sub2/project"),
        # self-managed → host-qualified
        ("https://gitlab.corp.io/owner/repo", "gitlab.corp.io/owner/repo"),
        ("https://git.example.com/group/subgroup/project", "git.example.com/group/subgroup/project"),
        ("https://gitlab.sec.example.net/g/s/p", "gitlab.sec.example.net/g/s/p"),
    ],
)
def test_parse_gitlab_source_accepts(url, expected):
    """A clean GitLab project URL parses to the expected project spec."""
    assert parse_gitlab_source(url) == expected


# ---------------------------------------------------------------------------
# parse_gitlab_source — SSRF rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        # IP-literal hosts
        "https://127.0.0.1/group/project",
        "https://169.254.169.254/group/project",
        "https://10.0.0.1/group/project",
        "https://[::1]/group/project",
        "https://[fe80::1]/group/project",
        # Legacy IPv4 (inet_aton accepts, ipaddress does not)
        "https://127.1/group/project",
        "https://0177.0.0.1/group/project",
        "https://0x7f.0.0.1/group/project",
        # userinfo / authority spoofing
        "https://gitlab.com@evil.example/group/project",
        "https://user@gitlab.corp.io/group/project",
        # explicit port
        "https://gitlab.corp.io:443/group/project",
        "https://gitlab.com:8080/group/project",
        "https://gitlab.corp.io:/group/project",
        # non-http(s) scheme
        "git@gitlab.com:group/project.git",
        "ssh://git@gitlab.com/group/project.git",
        "ftp://gitlab.com/group/project",
        # single-label host (no dot)
        "https://localhost/group/project",
        "https://gitlab/group/project",
        # missing host
        "https:///group/project",
        # query / fragment
        "https://gitlab.com/group/project?ref=main",
        "https://gitlab.com/group/project#readme",
        # too few path segments (< 2)
        "https://gitlab.com/only-one",
        "https://gitlab.com/",
        "https://gitlab.com",
        # empty segment
        "https://gitlab.com/group//project",
        # dot segment
        "https://gitlab.com/group/../project",
        "https://gitlab.com/./project",
    ],
)
def test_parse_gitlab_source_rejects(url):
    """A bad GitLab URL raises ValueError — reject rather than guess."""
    with pytest.raises(ValueError):
        parse_gitlab_source(url)


def test_parse_gitlab_source_ssrf_single_line_error():
    """SSRF rejection error message is single-line (no traceback leak)."""
    with pytest.raises(ValueError) as exc_info:
        parse_gitlab_source("https://127.0.0.1/group/project")
    assert "\n" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# GitLab usernames with dots/underscores (wider charset than GitHub)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "author",
    [
        "alice",
        "alice.bob",
        "alice_bob",
        "alice-bob",
        "alice123",
        "alice.b_c-d",
    ],
)
def test_gitlab_author_valid_handles_accepted(author):
    """GitLab usernames with dots/underscores are accepted by the author handler."""
    extractor, _ = _recording_gitlab_author_extractor()
    resolved = resolve_source(
        "gitlab-author",
        SourceRequest(source=None, author=author, gitlab_author_extractor=extractor),
    )
    assert resolved.subject == author


def test_ssrf_rejected_before_gitlab_extractor_called():
    """An SSRF URL is rejected before the extractor is ever invoked."""
    extractor, calls = _recording_gitlab_extractor()
    with pytest.raises(ValueError):
        resolve_source(
            "gitlab",
            SourceRequest(
                source="https://169.254.169.254/group/project",
                author="alice",
                gitlab_extractor=extractor,
            ),
        )
    assert calls == []
