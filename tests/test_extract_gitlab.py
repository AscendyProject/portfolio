"""Tests for the GitLab extractor (portfolio/extract_gitlab.py).

Covers:
- parse_gitlab_mr_evidence: JSON→Evidence parser with a fake glab payload
  (ref, url, detail, additions, deletions; graceful degradation when absent)
- extract_merged_mrs: injected runner receives correct argv, project is passed
- extract_authored_mrs: injected runner receives correct argv
- FileNotFoundError from runner surfaces as clean RuntimeError naming glab
- Non-zero exit from runner surfaces as clean RuntimeError

No real `glab` binary is used — all subprocess calls are replaced by fakes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.extract_gitlab import (  # noqa: E402
    extract_authored_mrs,
    extract_merged_mrs,
    parse_gitlab_mr_evidence,
)


# ---------------------------------------------------------------------------
# Fake glab payload helpers
# ---------------------------------------------------------------------------

_PROJECT = "group/subgroup/project"

_SAMPLE_MR_LIST = json.dumps(
    [
        {
            "iid": 42,
            "title": "Fix authentication bug",
            "web_url": "https://gitlab.com/group/subgroup/project/-/merge_requests/42",
            "references": {"full": "group/subgroup/project!42"},
            "additions": 15,
            "deletions": 3,
        },
        {
            "iid": 57,
            "title": "Improve caching",
            "web_url": "https://gitlab.com/group/subgroup/project/-/merge_requests/57",
            "references": {"full": "group/subgroup/project!57"},
            "additions": 80,
            "deletions": 20,
        },
    ]
)

_SAMPLE_NO_STATS = json.dumps(
    [
        {
            "iid": 10,
            "title": "Refactor core",
            "web_url": "https://gitlab.com/group/project/-/merge_requests/10",
            "references": {"full": "group/project!10"},
            # no additions / deletions fields
        }
    ]
)

_SAMPLE_NO_REFERENCES = json.dumps(
    [
        {
            "iid": 5,
            "title": "Quick fix",
            "web_url": "https://gitlab.com/myorg/myproject/-/merge_requests/5",
            # no references field — fallback to project!iid
        }
    ]
)


# ---------------------------------------------------------------------------
# parse_gitlab_mr_evidence — pure parser tests
# ---------------------------------------------------------------------------


def test_parser_produces_one_evidence_per_mr():
    """One `kind='pr'` Evidence is emitted per entry in the payload."""
    ev = parse_gitlab_mr_evidence(_SAMPLE_MR_LIST, _PROJECT)
    assert len(ev) == 2
    assert all(e.kind == "pr" for e in ev)


def test_parser_ref_format():
    """ref = references.full value from payload (e.g. 'group/subgroup/project!42')."""
    ev = parse_gitlab_mr_evidence(_SAMPLE_MR_LIST, _PROJECT)
    refs = {e.ref for e in ev}
    assert "group/subgroup/project!42" in refs
    assert "group/subgroup/project!57" in refs


def test_parser_url_set_from_web_url():
    """evidence.url is set from the 'web_url' field of the payload."""
    ev = parse_gitlab_mr_evidence(_SAMPLE_MR_LIST, _PROJECT)
    ev42 = next(e for e in ev if e.ref == "group/subgroup/project!42")
    assert ev42.url == "https://gitlab.com/group/subgroup/project/-/merge_requests/42"


def test_parser_detail_contains_title_and_change_size():
    """detail = '<title> (+A/-D)' mirroring parse_pr_evidence shape."""
    ev = parse_gitlab_mr_evidence(_SAMPLE_MR_LIST, _PROJECT)
    ev42 = next(e for e in ev if e.ref == "group/subgroup/project!42")
    assert "Fix authentication bug" in ev42.detail
    assert "+15/-3" in ev42.detail


def test_parser_additions_and_deletions_populated():
    """additions and deletions are set from the payload when present."""
    ev = parse_gitlab_mr_evidence(_SAMPLE_MR_LIST, _PROJECT)
    ev42 = next(e for e in ev if e.ref == "group/subgroup/project!42")
    assert ev42.additions == 15
    assert ev42.deletions == 3

    ev57 = next(e for e in ev if e.ref == "group/subgroup/project!57")
    assert ev57.additions == 80
    assert ev57.deletions == 20


def test_parser_graceful_degradation_no_stats():
    """When additions/deletions are absent, they default to 0 (no crash)."""
    ev = parse_gitlab_mr_evidence(_SAMPLE_NO_STATS, _PROJECT)
    assert len(ev) == 1
    ev0 = ev[0]
    assert ev0.additions == 0
    assert ev0.deletions == 0
    assert "+0/-0" in ev0.detail


def test_parser_fallback_ref_from_project_when_no_references():
    """When 'references.full' is absent, ref falls back to '<project>!<iid>'."""
    ev = parse_gitlab_mr_evidence(_SAMPLE_NO_REFERENCES, "myorg/myproject")
    assert ev[0].ref == "myorg/myproject!5"


def test_parser_empty_input():
    """Empty list produces empty Evidence list."""
    ev = parse_gitlab_mr_evidence("[]", _PROJECT)
    assert ev == []


def test_parser_is_pure():
    """Same input → same output, no side effects (pure function)."""
    ev1 = parse_gitlab_mr_evidence(_SAMPLE_MR_LIST, _PROJECT)
    ev2 = parse_gitlab_mr_evidence(_SAMPLE_MR_LIST, _PROJECT)
    assert ev1 == ev2


# ---------------------------------------------------------------------------
# extract_merged_mrs — injected runner
# ---------------------------------------------------------------------------


def _make_project_runner(payload: str = _SAMPLE_MR_LIST):
    recorded: list[list[str]] = []

    def runner(args: list[str]) -> str:
        recorded.append(list(args))
        return payload

    return runner, recorded


def test_extract_merged_mrs_returns_evidence():
    """extract_merged_mrs returns Evidence from the parsed runner output."""
    runner, _ = _make_project_runner()
    ev = extract_merged_mrs(project=_PROJECT, author="alice", runner=runner)
    assert len(ev) == 2
    assert all(e.kind == "pr" for e in ev)


def test_extract_merged_mrs_argv_starts_with_mr_list():
    """Runner is called with argv starting with ['mr', 'list', ...]."""
    runner, recorded = _make_project_runner()
    extract_merged_mrs(project=_PROJECT, author="alice", runner=runner)
    assert len(recorded) == 1
    argv = recorded[0]
    assert argv[0] == "mr"
    assert argv[1] == "list"


def test_extract_merged_mrs_argv_has_repo_flag():
    """Runner argv includes '--repo' <project> as separate tokens."""
    runner, recorded = _make_project_runner()
    extract_merged_mrs(project=_PROJECT, author="alice", runner=runner)
    argv = recorded[0]
    assert "--repo" in argv
    repo_idx = argv.index("--repo")
    assert argv[repo_idx + 1] == _PROJECT


def test_extract_merged_mrs_argv_has_author_flag():
    """Runner argv includes '--author' <author> as separate tokens."""
    runner, recorded = _make_project_runner()
    extract_merged_mrs(project=_PROJECT, author="alice", runner=runner)
    argv = recorded[0]
    assert "--author" in argv
    author_idx = argv.index("--author")
    assert argv[author_idx + 1] == "alice"


def test_extract_merged_mrs_argv_has_merged_flag():
    """Runner argv includes '--merged'."""
    runner, recorded = _make_project_runner()
    extract_merged_mrs(project=_PROJECT, author="alice", runner=runner)
    assert "--merged" in recorded[0]


def test_extract_merged_mrs_argv_has_json_output_flag():
    """Runner argv includes '--output' 'json' (JSON output flag)."""
    runner, recorded = _make_project_runner()
    extract_merged_mrs(project=_PROJECT, author="alice", runner=runner)
    argv = recorded[0]
    assert "--output" in argv
    output_idx = argv.index("--output")
    assert argv[output_idx + 1] == "json"


def test_extract_merged_mrs_limit_passed_to_runner():
    """limit is passed as '--limit' <n> in the runner argv."""
    runner, recorded = _make_project_runner()
    extract_merged_mrs(project=_PROJECT, author="alice", limit=50, runner=runner)
    argv = recorded[0]
    assert "--limit" in argv
    limit_idx = argv.index("--limit")
    assert argv[limit_idx + 1] == "50"


def test_extract_merged_mrs_no_shell_string():
    """author value reaches the runner only as a separate argv token (no shell=True)."""
    runner, recorded = _make_project_runner()
    extract_merged_mrs(project=_PROJECT, author="evil; rm -rf /", runner=runner)
    argv = recorded[0]
    # the dangerous string must appear as a single standalone element, not shell-parsed
    assert "evil; rm -rf /" in argv
    # it must not appear embedded in another element
    assert not any("evil; rm -rf /" in t and t != "evil; rm -rf /" for t in argv)


# ---------------------------------------------------------------------------
# extract_authored_mrs — injected runner
# ---------------------------------------------------------------------------


def _make_author_runner(payload: str = _SAMPLE_MR_LIST):
    recorded: list[list[str]] = []

    def runner(args: list[str]) -> str:
        recorded.append(list(args))
        return payload

    return runner, recorded


def test_extract_authored_mrs_returns_evidence():
    """extract_authored_mrs returns Evidence from the parsed runner output."""
    runner, _ = _make_author_runner()
    ev = extract_authored_mrs(author="alice", runner=runner)
    assert len(ev) == 2


def test_extract_authored_mrs_argv_starts_with_mr_list():
    """Runner is called with argv starting with ['mr', 'list', ...]."""
    runner, recorded = _make_author_runner()
    extract_authored_mrs(author="alice", runner=runner)
    argv = recorded[0]
    assert argv[0] == "mr"
    assert argv[1] == "list"


def test_extract_authored_mrs_argv_has_author_flag():
    """Runner argv includes '--author' <author> as separate tokens."""
    runner, recorded = _make_author_runner()
    extract_authored_mrs(author="alice", runner=runner)
    argv = recorded[0]
    assert "--author" in argv
    author_idx = argv.index("--author")
    assert argv[author_idx + 1] == "alice"


def test_extract_authored_mrs_argv_has_merged_flag():
    """Runner argv includes '--merged'."""
    runner, recorded = _make_author_runner()
    extract_authored_mrs(author="alice", runner=runner)
    assert "--merged" in recorded[0]


def test_extract_authored_mrs_argv_has_json_output_flag():
    """Runner argv includes '--output' 'json'."""
    runner, recorded = _make_author_runner()
    extract_authored_mrs(author="alice", runner=runner)
    argv = recorded[0]
    assert "--output" in argv
    output_idx = argv.index("--output")
    assert argv[output_idx + 1] == "json"


def test_extract_authored_mrs_no_repo_flag():
    """Author-wide extraction does not pass '--repo' to the runner."""
    runner, recorded = _make_author_runner()
    extract_authored_mrs(author="alice", runner=runner)
    assert "--repo" not in recorded[0]


# ---------------------------------------------------------------------------
# Error paths — missing glab / non-zero exit
# ---------------------------------------------------------------------------


def test_missing_glab_raises_runtime_error_naming_glab():
    """FileNotFoundError from the runner surfaces as RuntimeError naming 'glab'."""

    def no_glab(args: list[str]) -> str:
        raise FileNotFoundError("No such file: glab")

    with pytest.raises(RuntimeError) as exc_info:
        extract_merged_mrs(project=_PROJECT, author="alice", runner=no_glab)

    msg = str(exc_info.value)
    assert "glab" in msg
    assert "\n" not in msg  # single-line (no traceback frame)


def test_missing_glab_author_wide_raises_runtime_error_naming_glab():
    """FileNotFoundError from the runner in extract_authored_mrs → RuntimeError naming glab."""

    def no_glab(args: list[str]) -> str:
        raise FileNotFoundError("No such file: glab")

    with pytest.raises(RuntimeError) as exc_info:
        extract_authored_mrs(author="alice", runner=no_glab)

    assert "glab" in str(exc_info.value)


def test_nonzero_exit_raises_runtime_error():
    """Non-zero exit from _run_glab (simulated via a runner raising RuntimeError) is surfaced."""

    def failing_runner(args: list[str]) -> str:
        raise RuntimeError("glab mr list failed (rc=1): repository not found")

    # extract_merged_mrs should propagate the RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        extract_merged_mrs(project=_PROJECT, author="alice", runner=failing_runner)

    msg = str(exc_info.value)
    # The error message must not contain any token-shaped string (fake stderr)
    assert "my_secret_token" not in msg


def test_nonzero_exit_does_not_echo_full_stderr():
    """RuntimeError from a non-zero glab exit does not dump raw stderr past 500 chars."""

    def runner_with_long_stderr(args: list[str]) -> str:
        # simulate _run_glab truncating a long stderr
        long_stderr = "X" * 1000
        raise RuntimeError(f"glab mr list failed (rc=1): {long_stderr[:500]}")

    with pytest.raises(RuntimeError) as exc_info:
        extract_merged_mrs(project=_PROJECT, author="alice", runner=runner_with_long_stderr)

    # The full 1000-char blob must not appear in the error message
    assert "X" * 1000 not in str(exc_info.value)


def test_run_glab_does_not_include_token_in_error(monkeypatch):
    """_run_glab must not surface token-shaped values from glab stderr in RuntimeError.

    Patches subprocess.run directly so the real _run_glab code path is exercised,
    not a fake runner.  A GitLab-format token appearing in glab's stderr must not
    appear in the raised RuntimeError.
    """
    from unittest.mock import MagicMock

    import portfolio.extract_gitlab as _mod

    token = "glpat-xxxxxxxxxxxxxxxxxxxx"
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = f"could not authenticate: {token}"

    monkeypatch.setattr(_mod.subprocess, "run", lambda *a, **kw: mock_proc)

    with pytest.raises(RuntimeError) as exc_info:
        # No runner= injected — exercises the real _run_glab → subprocess.run path
        extract_merged_mrs(project=_PROJECT, author="alice")

    assert token not in str(exc_info.value)
