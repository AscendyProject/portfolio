"""Tests for portfolio/extract_bitbucket.py.

Covers:
- parse_bitbucket_pr_list: correct ref, url, detail, adds=0, dels=0 from canned JSON
- parse_bitbucket_pr_list: missing fields — graceful degradation
- parse_bitbucket_diffstat: correct adds/dels, file evidence for code files
- parse_bitbucket_diffstat: non-code files filtered by denylist
- parse_bitbucket_diffstat: deleted files use old.path
- Pagination: fetcher called with next URL; stops when next is absent
- SSRF: next URL with wrong host is refused (no call made to it)
- Injected fetcher receives expected URL; auth is not None
- Secret not in any Evidence field or error message
- Code-only filter: lockfile not in file evidence
- Best-effort: one PR's diffstat raises → that PR gets 0/0 no files; other PR intact
- Missing credentials → clean RuntimeError naming env var
- Credential not in any Evidence field or error message
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.extract_bitbucket import (  # noqa: E402
    extract_merged_prs_bitbucket,
    parse_bitbucket_diffstat,
    parse_bitbucket_pr_list,
)

# ---------------------------------------------------------------------------
# Canned JSON fixtures
# ---------------------------------------------------------------------------

_PR_LIST_PAGE = {
    "values": [
        {
            "id": 7,
            "title": "Fix login bug",
            "links": {"html": {"href": "https://bitbucket.org/acme/widgets/pull-requests/7"}},
        },
        {
            "id": 8,
            "title": "Add feature X",
            "links": {"html": {"href": "https://bitbucket.org/acme/widgets/pull-requests/8"}},
        },
    ],
}

_DIFFSTAT_PAGE = {
    "values": [
        {
            "status": "modified",
            "lines_added": 10,
            "lines_removed": 3,
            "new": {"path": "src/main.py"},
            "old": {"path": "src/main.py"},
        },
        {
            "status": "modified",
            "lines_added": 5,
            "lines_removed": 1,
            "new": {"path": "src/util.py"},
            "old": {"path": "src/util.py"},
        },
    ],
}

_DIFFSTAT_WITH_LOCKFILE = {
    "values": [
        {
            "status": "modified",
            "lines_added": 100,
            "lines_removed": 50,
            "new": {"path": "package-lock.json"},
            "old": {"path": "package-lock.json"},
        },
        {
            "status": "modified",
            "lines_added": 20,
            "lines_removed": 5,
            "new": {"path": "app/server.py"},
            "old": {"path": "app/server.py"},
        },
    ],
}

_DIFFSTAT_DELETED_FILE = {
    "values": [
        {
            "status": "removed",
            "lines_added": 0,
            "lines_removed": 42,
            "new": None,
            "old": {"path": "src/old_module.py"},
        },
    ],
}

_DIFFSTAT_NON_CODE_ONLY = {
    "values": [
        {
            "status": "modified",
            "lines_added": 999,
            "lines_removed": 500,
            "new": {"path": "README.md"},
            "old": {"path": "README.md"},
        },
        {
            "status": "modified",
            "lines_added": 200,
            "lines_removed": 100,
            "new": {"path": "config/settings.yaml"},
            "old": {"path": "config/settings.yaml"},
        },
    ],
}


# ---------------------------------------------------------------------------
# parse_bitbucket_pr_list
# ---------------------------------------------------------------------------


def test_parse_pr_list_basic():
    """parse_bitbucket_pr_list returns one Evidence per PR with correct ref/url/detail."""
    result = parse_bitbucket_pr_list(_PR_LIST_PAGE, "bitbucket.org", "acme", "widgets")
    assert len(result) == 2

    pr7 = result[0]
    assert pr7.kind == "pr"
    assert pr7.ref == "bitbucket.org/acme/widgets#7"
    assert pr7.url == "https://bitbucket.org/acme/widgets/pull-requests/7"
    assert pr7.detail == "Fix login bug"
    assert pr7.additions == 0
    assert pr7.deletions == 0


def test_parse_pr_list_second_pr():
    """Second PR is also parsed correctly."""
    result = parse_bitbucket_pr_list(_PR_LIST_PAGE, "bitbucket.org", "acme", "widgets")
    pr8 = result[1]
    assert pr8.ref == "bitbucket.org/acme/widgets#8"
    assert pr8.detail == "Add feature X"


def test_parse_pr_list_empty_values():
    """Empty values list returns empty Evidence list."""
    result = parse_bitbucket_pr_list({"values": []}, "bitbucket.org", "ws", "repo")
    assert result == []


def test_parse_pr_list_missing_id_skipped():
    """A PR entry missing 'id' is silently skipped."""
    data = {"values": [{"title": "No ID PR", "links": {"html": {"href": "https://..."}}}]}
    result = parse_bitbucket_pr_list(data, "bitbucket.org", "ws", "repo")
    assert result == []


def test_parse_pr_list_missing_links_graceful():
    """A PR entry missing 'links' produces empty url."""
    data = {"values": [{"id": 1, "title": "Test PR"}]}
    result = parse_bitbucket_pr_list(data, "bitbucket.org", "ws", "repo")
    assert len(result) == 1
    assert result[0].url == ""


def test_parse_pr_list_null_links_graceful():
    """A PR entry with null 'links' produces empty url."""
    data = {"values": [{"id": 1, "title": "Test PR", "links": None}]}
    result = parse_bitbucket_pr_list(data, "bitbucket.org", "ws", "repo")
    assert len(result) == 1
    assert result[0].url == ""


def test_parse_pr_list_non_dict_value_skipped():
    """Non-dict entries in values list are silently skipped."""
    data = {"values": ["not-a-dict", None, {"id": 5, "title": "Real PR"}]}
    result = parse_bitbucket_pr_list(data, "bitbucket.org", "ws", "repo")
    assert len(result) == 1
    assert result[0].ref == "bitbucket.org/ws/repo#5"


def test_parse_pr_list_missing_values_key():
    """A response missing 'values' key returns empty list."""
    result = parse_bitbucket_pr_list({}, "bitbucket.org", "ws", "repo")
    assert result == []


# ---------------------------------------------------------------------------
# parse_bitbucket_diffstat
# ---------------------------------------------------------------------------


def test_parse_diffstat_code_files():
    """parse_bitbucket_diffstat sums adds/dels for code files and emits file evidence."""
    pr_ref = "bitbucket.org/acme/widgets#7"
    adds, dels, files = parse_bitbucket_diffstat(_DIFFSTAT_PAGE, pr_ref)
    assert adds == 15  # 10 + 5
    assert dels == 4  # 3 + 1
    assert len(files) == 2
    paths = {f.ref for f in files}
    assert "src/main.py" in paths
    assert "src/util.py" in paths


def test_parse_diffstat_file_kind():
    """File evidence entries have kind="file"."""
    _, _, files = parse_bitbucket_diffstat(_DIFFSTAT_PAGE, "bitbucket.org/acme/widgets#7")
    for f in files:
        assert f.kind == "file"


def test_parse_diffstat_file_detail_contains_pr_ref():
    """File evidence detail contains the PR ref."""
    pr_ref = "bitbucket.org/acme/widgets#7"
    _, _, files = parse_bitbucket_diffstat(_DIFFSTAT_PAGE, pr_ref)
    for f in files:
        assert pr_ref in f.detail


def test_parse_diffstat_lockfile_excluded():
    """Lockfiles are excluded from adds/dels and file evidence."""
    pr_ref = "bitbucket.org/acme/widgets#7"
    adds, dels, files = parse_bitbucket_diffstat(_DIFFSTAT_WITH_LOCKFILE, pr_ref)
    # only app/server.py counts; package-lock.json is excluded
    assert adds == 20
    assert dels == 5
    assert len(files) == 1
    assert files[0].ref == "app/server.py"


def test_parse_diffstat_non_code_files_excluded():
    """Non-code files (.md, .yaml) are excluded entirely."""
    pr_ref = "bitbucket.org/acme/widgets#7"
    adds, dels, files = parse_bitbucket_diffstat(_DIFFSTAT_NON_CODE_ONLY, pr_ref)
    assert adds == 0
    assert dels == 0
    assert files == []


def test_parse_diffstat_deleted_file_uses_old_path():
    """Deleted files (status='removed') use old.path as ref."""
    pr_ref = "bitbucket.org/acme/widgets#7"
    adds, dels, files = parse_bitbucket_diffstat(_DIFFSTAT_DELETED_FILE, pr_ref)
    assert dels == 42
    assert len(files) == 1
    assert files[0].ref == "src/old_module.py"


def test_parse_diffstat_empty_values():
    """Empty diffstat values returns (0, 0, [])."""
    adds, dels, files = parse_bitbucket_diffstat({"values": []}, "bitbucket.org/ws/repo#1")
    assert (adds, dels, files) == (0, 0, [])


def test_parse_diffstat_missing_values():
    """Missing 'values' key returns (0, 0, [])."""
    adds, dels, files = parse_bitbucket_diffstat({}, "bitbucket.org/ws/repo#1")
    assert (adds, dels, files) == (0, 0, [])


def test_parse_diffstat_none_lines_treated_as_zero():
    """None values for lines_added/lines_removed are treated as 0."""
    data = {
        "values": [
            {
                "status": "modified",
                "lines_added": None,
                "lines_removed": None,
                "new": {"path": "src/app.py"},
                "old": {"path": "src/app.py"},
            }
        ]
    }
    adds, dels, files = parse_bitbucket_diffstat(data, "bitbucket.org/ws/repo#1")
    assert adds == 0
    assert dels == 0
    assert len(files) == 1


# ---------------------------------------------------------------------------
# extract_merged_prs_bitbucket — injected fetcher, pagination, SSRF
# ---------------------------------------------------------------------------


def _make_pr_page(pr_id: int, title: str, workspace: str, repo: str, next_url: str | None = None) -> dict:
    page: dict = {
        "values": [
            {
                "id": pr_id,
                "title": title,
                "links": {"html": {"href": f"https://bitbucket.org/{workspace}/{repo}/pull-requests/{pr_id}"}},
            }
        ]
    }
    if next_url:
        page["next"] = next_url
    return page


def _make_diffstat_page(paths: list[str], adds: int, dels: int) -> dict:
    return {
        "values": [
            {
                "status": "modified",
                "lines_added": adds,
                "lines_removed": dels,
                "new": {"path": p},
                "old": {"path": p},
            }
            for p in paths
        ]
    }


def test_extract_calls_fetcher_with_expected_url():
    """The fetcher is called with the API list URL and the auth kwarg."""
    calls: list[tuple] = []

    def fake_fetcher(url: str, *, auth) -> dict:
        calls.append((url, auth))
        if "pullrequests" in url:
            return {"values": []}
        return {"values": []}

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok123"}, clear=False):
        result = extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    assert len(calls) >= 1
    list_url, auth_val = calls[0]
    assert "api.bitbucket.org" in list_url
    assert "ws" in list_url
    assert "repo" in list_url
    # auth is not None
    assert auth_val is not None
    # secret not in any Evidence field
    for ev in result:
        assert "tok123" not in ev.ref
        assert "tok123" not in ev.detail
        assert "tok123" not in ev.url


def test_extract_pagination_follows_next():
    """Extractor follows 'next' URL until exhausted."""
    page2_url = "https://api.bitbucket.org/2.0/repositories/ws/repo/pullrequests?page=2"
    page1 = _make_pr_page(1, "PR one", "ws", "repo", next_url=page2_url)
    page2 = _make_pr_page(2, "PR two", "ws", "repo")
    diffstat_empty: dict = {"values": []}

    fetched_urls: list[str] = []

    def fake_fetcher(url: str, *, auth) -> dict:
        fetched_urls.append(url)
        if "pullrequests/1/diffstat" in url:
            return diffstat_empty
        if "pullrequests/2/diffstat" in url:
            return diffstat_empty
        if page2_url in url or url == page2_url:
            return page2
        return page1

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        result = extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    pr_refs = [ev.ref for ev in result if ev.kind == "pr"]
    assert "ws/repo/repo#1" not in pr_refs  # should be bitbucket.org/...
    assert any("#1" in r for r in pr_refs)
    assert any("#2" in r for r in pr_refs)
    assert len(pr_refs) == 2


def test_extract_pagination_stops_at_limit():
    """Extractor stops collecting once `limit` PRs have been collected."""
    page_with_two = {
        "values": [
            {
                "id": 1,
                "title": "PR 1",
                "links": {"html": {"href": "https://bitbucket.org/ws/repo/pull-requests/1"}},
            },
            {
                "id": 2,
                "title": "PR 2",
                "links": {"html": {"href": "https://bitbucket.org/ws/repo/pull-requests/2"}},
            },
        ]
    }
    diffstat_empty: dict = {"values": []}

    def fake_fetcher(url: str, *, auth) -> dict:
        if "diffstat" in url:
            return diffstat_empty
        return page_with_two

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        result = extract_merged_prs_bitbucket("ws", "repo", "alice", limit=1, fetcher=fake_fetcher)

    pr_evs = [ev for ev in result if ev.kind == "pr"]
    assert len(pr_evs) == 1


def test_extract_ssrf_next_url_refused():
    """A 'next' URL pointing to a non-api.bitbucket.org host is refused (not fetched)."""
    evil_url = "https://evil.example.com/steal?data=prs"
    page1 = _make_pr_page(1, "PR 1", "ws", "repo", next_url=evil_url)
    diffstat_empty: dict = {"values": []}

    fetched_urls: list[str] = []

    def fake_fetcher(url: str, *, auth) -> dict:
        fetched_urls.append(url)
        if "diffstat" in url:
            return diffstat_empty
        return page1

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    # The evil URL must never have been fetched
    assert evil_url not in fetched_urls


def test_extract_diffstat_ssrf_next_refused():
    """A 'next' URL in a diffstat response pointing to a non-api host is refused."""
    evil_diffstat_next = "https://evil.example.com/diffstat?page=2"
    pr_page = _make_pr_page(1, "PR 1", "ws", "repo")
    diffstat_page1 = {
        "values": [
            {
                "status": "modified",
                "lines_added": 5,
                "lines_removed": 2,
                "new": {"path": "src/app.py"},
                "old": {"path": "src/app.py"},
            }
        ],
        "next": evil_diffstat_next,
    }

    fetched_urls: list[str] = []

    def fake_fetcher(url: str, *, auth) -> dict:
        fetched_urls.append(url)
        if "diffstat" in url and evil_diffstat_next not in url:
            return diffstat_page1
        return pr_page

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    assert evil_diffstat_next not in fetched_urls


def test_extract_best_effort_diffstat_failure():
    """If one PR's diffstat raises, that PR gets 0/0 no files; other PR intact."""
    pr_page = {
        "values": [
            {
                "id": 1,
                "title": "PR 1",
                "links": {"html": {"href": "https://bitbucket.org/ws/repo/pull-requests/1"}},
            },
            {
                "id": 2,
                "title": "PR 2",
                "links": {"html": {"href": "https://bitbucket.org/ws/repo/pull-requests/2"}},
            },
        ]
    }
    good_diffstat = _make_diffstat_page(["src/app.py"], 10, 3)

    def fake_fetcher(url: str, *, auth) -> dict:
        if "pullrequests/1/diffstat" in url:
            raise RuntimeError("API error for PR 1")
        if "pullrequests/2/diffstat" in url:
            return good_diffstat
        return pr_page

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        result = extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    pr1_ev = next((ev for ev in result if ev.kind == "pr" and "#1" in ev.ref), None)
    pr2_ev = next((ev for ev in result if ev.kind == "pr" and "#2" in ev.ref), None)

    assert pr1_ev is not None
    assert pr1_ev.additions == 0
    assert pr1_ev.deletions == 0

    assert pr2_ev is not None
    assert pr2_ev.additions == 10
    assert pr2_ev.deletions == 3

    # PR 1 has no file evidence
    pr1_files = [ev for ev in result if ev.kind == "file" and "bitbucket.org/ws/repo#1" in ev.detail]
    assert pr1_files == []

    # PR 2 has file evidence
    pr2_files = [ev for ev in result if ev.kind == "file" and "bitbucket.org/ws/repo#2" in ev.detail]
    assert len(pr2_files) == 1


def test_extract_bearer_auth_used():
    """When BITBUCKET_TOKEN is set, Bearer auth is passed (not Basic)."""
    received_auth = []

    def fake_fetcher(url: str, *, auth) -> dict:
        received_auth.append(auth)
        return {"values": []}

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "mytoken"}, clear=False):
        # Remove app-password env vars to ensure Bearer is used
        env = {"BITBUCKET_TOKEN": "mytoken"}
        with patch.dict(os.environ, env, clear=False):
            extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    assert len(received_auth) >= 1
    # auth is a string (Bearer token), not a tuple
    assert isinstance(received_auth[0], str)
    assert received_auth[0] == "mytoken"


def test_extract_basic_auth_used():
    """When BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD are set (no TOKEN), Basic auth is used."""
    received_auth = []

    def fake_fetcher(url: str, *, auth) -> dict:
        received_auth.append(auth)
        return {"values": []}

    env = {"BITBUCKET_USERNAME": "user1", "BITBUCKET_APP_PASSWORD": "pass1"}
    # Ensure BITBUCKET_TOKEN is not set
    with patch.dict(os.environ, env, clear=False):
        os_env_backup = os.environ.pop("BITBUCKET_TOKEN", None)
        try:
            extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)
        finally:
            if os_env_backup is not None:
                os.environ["BITBUCKET_TOKEN"] = os_env_backup

    assert len(received_auth) >= 1
    # auth is a tuple (username, app_password) for Basic
    assert isinstance(received_auth[0], tuple)
    assert received_auth[0] == ("user1", "pass1")


def test_extract_missing_credentials_raises_runtime_error():
    """When no credentials are set, raises RuntimeError naming the env vars."""
    env_keys = ["BITBUCKET_TOKEN", "BITBUCKET_USERNAME", "BITBUCKET_APP_PASSWORD"]
    backup = {k: os.environ.pop(k, None) for k in env_keys}
    try:
        with pytest.raises(RuntimeError) as exc_info:
            extract_merged_prs_bitbucket("ws", "repo", "alice")
        msg = str(exc_info.value)
        # Message names the env vars
        assert "BITBUCKET_TOKEN" in msg or "BITBUCKET_USERNAME" in msg
        # No traceback bytes in the message
        assert "Traceback" not in msg
    finally:
        for k, v in backup.items():
            if v is not None:
                os.environ[k] = v


def test_secret_not_in_evidence_fields():
    """The credential string never appears in any Evidence field."""
    secret = "super-secret-token-xyz"

    def fake_fetcher(url: str, *, auth) -> dict:
        if "diffstat" in url:
            return _make_diffstat_page(["src/app.py"], 5, 2)
        return _make_pr_page(1, "My PR", "ws", "repo")

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": secret}, clear=False):
        result = extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    for ev in result:
        assert secret not in ev.ref
        assert secret not in ev.url
        assert secret not in ev.detail
        assert secret not in ev.context


def test_extract_file_evidence_for_code_files():
    """Each code file in the diffstat produces a kind="file" Evidence with bare path ref."""
    pr_page = _make_pr_page(1, "My PR", "ws", "repo")
    diff_page = _make_diffstat_page(["src/app.py", "src/utils.py"], 15, 5)

    def fake_fetcher(url: str, *, auth) -> dict:
        if "diffstat" in url:
            return diff_page
        return pr_page

    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        result = extract_merged_prs_bitbucket("ws", "repo", "alice", fetcher=fake_fetcher)

    file_evs = [ev for ev in result if ev.kind == "file"]
    assert len(file_evs) == 2
    file_refs = {ev.ref for ev in file_evs}
    assert "src/app.py" in file_refs
    assert "src/utils.py" in file_refs


# ---------------------------------------------------------------------------
# Bitbucket query-language injection guard (codex IR-001)
# ---------------------------------------------------------------------------


def test_extract_rejects_query_injection_author():
    """An author containing quotes/operators/spaces is rejected before the query is
    built — URL-encoding alone would not stop Bitbucket-query-language injection."""

    def _unused_fetcher(url, *, auth):  # must never be reached
        raise AssertionError("fetcher must not be called for an invalid author")

    malicious = ['alice" OR state="OPEN', "a b", 'x"y', "a'b", "a;b", "a&b"]
    with patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}, clear=False):
        for bad in malicious:
            with pytest.raises(ValueError):
                extract_merged_prs_bitbucket("ws", "repo", bad, fetcher=_unused_fetcher)


def test_safe_api_host_requires_https_and_exact_host():
    """The pagination guard refuses non-HTTPS and non-api.bitbucket.org URLs so the
    Authorization header is never sent over plaintext or to another host (codex IR-001)."""
    from portfolio.extract_bitbucket import _safe_api_host

    assert _safe_api_host("https://api.bitbucket.org/2.0/repositories/ws/repo/pullrequests")
    # Plaintext to the right host must be refused (no creds over http).
    assert not _safe_api_host("http://api.bitbucket.org/2.0/repositories/ws/repo/pullrequests")
    # Other hosts (incl. lookalikes) refused.
    assert not _safe_api_host("https://evil.example.com/x")
    assert not _safe_api_host("https://api.bitbucket.org.evil.com/x")
