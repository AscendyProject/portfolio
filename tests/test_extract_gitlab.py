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
    _count_diff_lines,
    extract_authored_mrs,
    extract_merged_mrs,
    parse_gitlab_mr_evidence,
    parse_mr_changes,
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


# ---------------------------------------------------------------------------
# task-035: _count_diff_lines — pure diff-line counter
# ---------------------------------------------------------------------------

_SAMPLE_DIFF = """\
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,7 +10,9 @@ def login(user):
 context line
+added line one
+added line two
-removed line one
 another context line
\\ No newline at end of file
"""


def test_count_diff_lines_additions_and_deletions():
    """Counts only true +/- change lines; ignores ---/+++, @@, context, and \\No-newline."""
    add, delete = _count_diff_lines(_SAMPLE_DIFF)
    assert add == 2
    assert delete == 1


def test_count_diff_lines_excludes_file_headers():
    """Lines starting with +++ or --- (file headers) are NOT counted."""
    diff = "--- a/foo.py\n+++ b/foo.py\n+real add\n"
    add, delete = _count_diff_lines(diff)
    assert add == 1
    assert delete == 0


def test_count_diff_lines_excludes_hunk_headers():
    """Lines starting with @@ (hunk headers) are NOT counted."""
    diff = "@@ -1,3 +1,4 @@\n+added\n"
    add, delete = _count_diff_lines(diff)
    assert add == 1
    assert delete == 0


def test_count_diff_lines_excludes_no_newline_marker():
    """`\\ No newline at end of file` marker lines are NOT counted."""
    diff = "+real\n\\ No newline at end of file\n"
    add, delete = _count_diff_lines(diff)
    assert add == 1
    assert delete == 0


def test_count_diff_lines_empty_diff():
    """Empty diff text returns (0, 0)."""
    assert _count_diff_lines("") == (0, 0)


def test_count_diff_lines_context_lines_ignored():
    """Context lines (no leading +/-) are NOT counted."""
    diff = " context\n context2\n+added\n"
    add, delete = _count_diff_lines(diff)
    assert add == 1
    assert delete == 0


# ---------------------------------------------------------------------------
# task-035: parse_mr_changes — pure payload parser
# ---------------------------------------------------------------------------

_CHANGES_PAYLOAD = json.dumps(
    {
        "changes": [
            {
                "new_path": "src/auth.py",
                "old_path": "src/auth.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1 +1,2 @@\n+added\n context\n",
            },
            {
                "new_path": "package-lock.json",
                "old_path": "package-lock.json",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "+lockfile line\n",
            },
            {
                "new_path": "vendor/x.go",
                "old_path": "vendor/x.go",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "+vendored line\n",
            },
        ]
    }
)

_MR_REF = "group/subgroup/project!42"


def test_parse_mr_changes_code_only_additions():
    """Only code files contribute to additions; lockfiles and vendor are excluded."""
    add, delete, _ = parse_mr_changes(_CHANGES_PAYLOAD, _MR_REF)
    assert add == 1
    assert delete == 0


def test_parse_mr_changes_file_evidence_for_code_only():
    """Only the code file yields a kind='file' Evidence; lockfile and vendor do not."""
    _, _, file_ev = parse_mr_changes(_CHANGES_PAYLOAD, _MR_REF)
    assert len(file_ev) == 1
    assert file_ev[0].kind == "file"
    assert file_ev[0].ref == "src/auth.py"


def test_parse_mr_changes_file_evidence_detail_links_mr():
    """File Evidence detail is 'changed in <mr_ref>'."""
    _, _, file_ev = parse_mr_changes(_CHANGES_PAYLOAD, _MR_REF)
    assert file_ev[0].detail == f"changed in {_MR_REF}"


def test_parse_mr_changes_deleted_file_uses_old_path():
    """For a deleted file, ref is old_path (new_path would be /dev/null)."""
    payload = json.dumps(
        {
            "changes": [
                {
                    "new_path": "/dev/null",
                    "old_path": "src/gone.py",
                    "new_file": False,
                    "deleted_file": True,
                    "renamed_file": False,
                    "diff": "-removed line\n",
                }
            ]
        }
    )
    _, _, file_ev = parse_mr_changes(payload, _MR_REF)
    assert len(file_ev) == 1
    assert file_ev[0].ref == "src/gone.py"


def test_parse_mr_changes_accepts_bare_list():
    """Bare list payload (no 'changes' envelope) is accepted."""
    payload = json.dumps(
        [
            {
                "new_path": "main.py",
                "old_path": "main.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "+line\n",
            }
        ]
    )
    add, _, file_ev = parse_mr_changes(payload, _MR_REF)
    assert add == 1
    assert len(file_ev) == 1
    assert file_ev[0].ref == "main.py"


def test_parse_mr_changes_invalid_json_degrades():
    """Malformed JSON degrades to (0, 0, [])."""
    assert parse_mr_changes("not json", _MR_REF) == (0, 0, [])


def test_parse_mr_changes_is_pure():
    """Same payload → same result (pure function)."""
    r1 = parse_mr_changes(_CHANGES_PAYLOAD, _MR_REF)
    r2 = parse_mr_changes(_CHANGES_PAYLOAD, _MR_REF)
    assert r1 == r2


def test_parse_mr_changes_file_ref_is_bare_path():
    """File Evidence.ref is a bare path — no host, owner, or project prefix."""
    _, _, file_ev = parse_mr_changes(_CHANGES_PAYLOAD, _MR_REF)
    ref = file_ev[0].ref
    assert "gitlab.com" not in ref
    assert "group/subgroup/project" not in ref
    # It is just a relative file path
    assert ref == "src/auth.py"


# ---------------------------------------------------------------------------
# task-035: extract_merged_mrs + extract_authored_mrs — per-MR changes argv
# ---------------------------------------------------------------------------

_MR_LIST_WITH_PROJECT_ID = json.dumps(
    [
        {
            "iid": 10,
            "project_id": 999,
            "title": "Add feature A",
            "web_url": "https://gitlab.com/grp/proj/-/merge_requests/10",
            "references": {"full": "grp/proj!10"},
        },
        {
            "iid": 11,
            "project_id": 999,
            "title": "Fix bug B",
            "web_url": "https://gitlab.com/grp/proj/-/merge_requests/11",
            "references": {"full": "grp/proj!11"},
        },
    ]
)

_CHANGES_RESPONSE = json.dumps(
    {
        "changes": [
            {
                "new_path": "app/main.py",
                "old_path": "app/main.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "+new line\n",
            }
        ]
    }
)


def _make_enriching_runner(
    list_payload: str = _MR_LIST_WITH_PROJECT_ID,
    changes_payload: str = _CHANGES_RESPONSE,
) -> tuple:
    """Return (runner, recorded) where runner handles both mr list and api calls."""
    recorded: list[list[str]] = []

    def runner(args: list[str]) -> str:
        recorded.append(list(args))
        if args and args[0] == "api":
            return changes_payload
        return list_payload

    return runner, recorded


def test_extract_merged_mrs_calls_changes_per_mr():
    """extract_merged_mrs invokes runner with api …/changes argv for each MR."""
    runner, recorded = _make_enriching_runner()
    extract_merged_mrs(project="grp/proj", author="alice", runner=runner)

    # First call: mr list; subsequent calls: api projects/<id>/mr/<iid>/changes
    api_calls = [a for a in recorded if a and a[0] == "api"]
    assert len(api_calls) == 2
    assert api_calls[0] == ["api", "projects/999/merge_requests/10/changes"]
    assert api_calls[1] == ["api", "projects/999/merge_requests/11/changes"]


def test_extract_merged_mrs_changes_argv_no_shell():
    """api argv is a list with no shell=True token injection."""
    runner, recorded = _make_enriching_runner()
    extract_merged_mrs(project="grp/proj", author="alice", runner=runner)
    api_calls = [a for a in recorded if a and a[0] == "api"]
    for call in api_calls:
        # Each element must be a clean string — no semicolons or shell chars
        assert all(isinstance(t, str) for t in call)


def test_extract_merged_mrs_enriched_evidence_has_file_records():
    """After enrichment, both pr and file Evidence records are present."""
    runner, _ = _make_enriching_runner()
    ev = extract_merged_mrs(project="grp/proj", author="alice", runner=runner)
    kinds = [e.kind for e in ev]
    assert "pr" in kinds
    assert "file" in kinds


def test_extract_merged_mrs_pr_evidence_ends_with_change_size():
    """The kind='pr' Evidence detail ends with (+A/-D) from the real diff."""
    runner, _ = _make_enriching_runner()
    ev = extract_merged_mrs(project="grp/proj", author="alice", runner=runner)
    pr_ev = [e for e in ev if e.kind == "pr"]
    for e in pr_ev:
        # detail must end with (+N/-N) pattern
        assert e.detail.endswith(f"(+{e.additions}/-{e.deletions})")


def test_extract_authored_mrs_calls_changes_per_mr():
    """extract_authored_mrs invokes runner with api …/changes argv for each MR."""
    runner, recorded = _make_enriching_runner()
    extract_authored_mrs(author="alice", runner=runner)

    api_calls = [a for a in recorded if a and a[0] == "api"]
    assert len(api_calls) == 2
    assert api_calls[0] == ["api", "projects/999/merge_requests/10/changes"]
    assert api_calls[1] == ["api", "projects/999/merge_requests/11/changes"]


def test_extract_authored_mrs_enriched_evidence_has_file_records():
    """After enrichment, both pr and file Evidence records are present."""
    runner, _ = _make_enriching_runner()
    ev = extract_authored_mrs(author="alice", runner=runner)
    kinds = [e.kind for e in ev]
    assert "pr" in kinds
    assert "file" in kinds


# ---------------------------------------------------------------------------
# task-035: best-effort failure — one MR's changes call raises
# ---------------------------------------------------------------------------

_TWO_MR_LIST = json.dumps(
    [
        {
            "iid": 1,
            "project_id": 100,
            "title": "MR one",
            "web_url": "https://gitlab.com/g/p/-/merge_requests/1",
            "references": {"full": "g/p!1"},
        },
        {
            "iid": 2,
            "project_id": 100,
            "title": "MR two",
            "web_url": "https://gitlab.com/g/p/-/merge_requests/2",
            "references": {"full": "g/p!2"},
        },
    ]
)

_ONE_FILE_CHANGES = json.dumps(
    {
        "changes": [
            {
                "new_path": "src/ok.py",
                "old_path": "src/ok.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "+code line\n",
            }
        ]
    }
)


def test_best_effort_one_mr_failure_other_succeeds():
    """When one MR's changes call raises, that MR keeps 0/0 + no file evidence;
    the other MR still gets its file evidence."""

    def failing_runner(args: list[str]) -> str:
        if args[0] == "mr":
            return _TWO_MR_LIST
        # Fail for iid=1, succeed for iid=2
        if "merge_requests/1/" in args[1]:
            raise RuntimeError("glpat-AAAAAAAAAAAA: 401 Unauthorized")
        return _ONE_FILE_CHANGES

    ev = extract_merged_mrs(project="g/p", author="bob", runner=failing_runner)

    pr_ev = [e for e in ev if e.kind == "pr"]
    file_ev = [e for e in ev if e.kind == "file"]

    # Both MRs still present
    pr_refs = {e.ref for e in pr_ev}
    assert "g/p!1" in pr_refs
    assert "g/p!2" in pr_refs

    # MR 1 has 0/0 and no file evidence
    mr1 = next(e for e in pr_ev if e.ref == "g/p!1")
    assert mr1.additions == 0
    assert mr1.deletions == 0
    assert not any(e.ref == "src/ok.py" and "g/p!1" in e.detail for e in file_ev)

    # MR 2 has file evidence
    assert any(e.kind == "file" for e in ev)


def test_best_effort_failure_does_not_preserve_stale_list_stats():
    """When per-MR changes call fails, additions/deletions must be 0/0 — NOT the
    stale values from the MR list payload.  IR-001: the else-branch in
    _enrich_evidence_list must never fall back to the original ev."""
    stale_list = json.dumps(
        [
            {
                "iid": 5,
                "project_id": 777,
                "title": "Stale stats MR",
                "web_url": "https://gitlab.com/a/b/-/merge_requests/5",
                "references": {"full": "a/b!5"},
                "additions": 100,  # stale — must NOT appear in enriched output
                "deletions": 50,  # stale — must NOT appear in enriched output
            }
        ]
    )

    def failing_runner(args: list[str]) -> str:
        if args[0] == "mr":
            return stale_list
        raise RuntimeError("auth failed")

    ev = extract_merged_mrs(project="a/b", author="carol", runner=failing_runner)
    pr_ev = [e for e in ev if e.kind == "pr"]
    assert len(pr_ev) == 1
    mr = pr_ev[0]
    # Must use enrichment result (0/0), NOT the stale list-level values (100/50)
    assert mr.additions == 0, f"stale additions leaked: got {mr.additions}"
    assert mr.deletions == 0, f"stale deletions leaked: got {mr.deletions}"
    assert "(+0/-0)" in mr.detail


def test_best_effort_no_token_leak_in_evidence():
    """Token-shaped strings from a runner exception do NOT appear in Evidence."""
    token = "glpat-AAAAAAAAAAAA"

    def failing_runner(args: list[str]) -> str:
        if args[0] == "mr":
            return _TWO_MR_LIST
        raise RuntimeError(f"could not auth: {token}")

    ev = extract_merged_mrs(project="g/p", author="bob", runner=failing_runner)

    for e in ev:
        assert token not in (e.detail or "")
        assert token not in (e.ref or "")


def test_best_effort_no_token_leak_authored():
    """Same token-leak check on extract_authored_mrs path."""
    token = "glpat-BBBBBBBBBBBB"

    def failing_runner(args: list[str]) -> str:
        if args[0] == "mr":
            return _TWO_MR_LIST
        raise RuntimeError(f"auth error: {token}")

    ev = extract_authored_mrs(author="bob", runner=failing_runner)

    for e in ev:
        assert token not in (e.detail or "")
        assert token not in (e.ref or "")


# ---------------------------------------------------------------------------
# task-035: bare-path file ref — no project identity leakage
# ---------------------------------------------------------------------------


def test_file_evidence_ref_is_bare_path_not_project_qualified():
    """File Evidence.ref for a private GitLab project is a bare path.

    It does NOT contain the project's group/subgroup/project path or the
    gitlab.com host, so --mask-private masking of the MR ref does NOT need to
    mask the file ref to avoid leaking the project identity.
    """
    private_project = "secret-corp/internal/payroll-service"
    payload = json.dumps(
        {
            "changes": [
                {
                    "new_path": "src/payroll.py",
                    "old_path": "src/payroll.py",
                    "new_file": False,
                    "deleted_file": False,
                    "renamed_file": False,
                    "diff": "+salary calc\n",
                }
            ]
        }
    )
    mr_ref = f"{private_project}!7"
    _, _, file_ev = parse_mr_changes(payload, mr_ref)

    assert len(file_ev) == 1
    ref = file_ev[0].ref
    assert "gitlab.com" not in ref
    assert "secret-corp" not in ref
    assert "internal" not in ref
    assert "payroll-service" not in ref
    assert ref == "src/payroll.py"
