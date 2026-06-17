"""PR-evidence parsing is pure (no live `gh`): feed it `gh pr list --json` shapes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.extract import extract_authored_prs, parse_authored_pr_evidence, parse_pr_evidence  # noqa: E402

_SAMPLE = json.dumps(
    [
        {
            "number": 128,
            "title": "Token rotation",
            "url": "https://github.com/o/r/pull/128",
            "mergedAt": "2026-01-01T00:00:00Z",
            "additions": 40,
            "deletions": 5,
            "files": [{"path": "app/auth.py"}, {"path": "tests/test_auth.py"}],
        },
        {
            "number": 130,
            "title": "Reuse auth helper",
            "url": "https://github.com/o/r/pull/130",
            "additions": 10,
            "deletions": 2,
            "files": [{"path": "app/auth.py"}],  # duplicate file across PRs
        },
    ]
)


def test_each_pr_becomes_pr_evidence():
    ev = parse_pr_evidence(_SAMPLE)
    pr_refs = {e.ref for e in ev if e.kind == "pr"}
    assert pr_refs == {"PR#128", "PR#130"}


def test_changed_files_become_file_evidence_deduped():
    ev = parse_pr_evidence(_SAMPLE)
    file_refs = [e.ref for e in ev if e.kind == "file"]
    assert "app/auth.py" in file_refs
    assert "tests/test_auth.py" in file_refs
    assert file_refs.count("app/auth.py") == 1  # deduped across PRs


def test_empty_input():
    assert parse_pr_evidence("[]") == []


def test_pr_detail_carries_size():
    ev = parse_pr_evidence(_SAMPLE)
    pr128 = next(e for e in ev if e.ref == "PR#128")
    assert "+40/-5" in pr128.detail


# ---------------------------------------------------------------------------
# parse_authored_pr_evidence — pure unit tests (no live `gh`)
# ---------------------------------------------------------------------------

_SEARCH_TWO_REPOS = json.dumps(
    [
        {
            "number": 1,
            "title": "First PR in repoA",
            "url": "https://github.com/owner1/repoA/pull/1",
            "repository": {"nameWithOwner": "owner1/repoA"},
        },
        {
            "number": 1,
            "title": "First PR in repoB",
            "url": "https://github.com/owner2/repoB/pull/1",
            "repository": {"nameWithOwner": "owner2/repoB"},
        },
    ]
)

_FILES_TWO_REPOS: dict = {
    "https://github.com/owner1/repoA/pull/1": [{"path": "cli.py"}],
    "https://github.com/owner2/repoB/pull/1": [{"path": "cli.py"}],
}


def test_authored_pr_ref_format_cross_repo():
    """One `kind='pr'` Evidence per `gh search prs` hit with ref formatted exactly
    as `<owner>/<repo>#<number>` — Done-when: cross-repo PR ref format."""
    ev = parse_authored_pr_evidence(_SEARCH_TWO_REPOS, _FILES_TWO_REPOS)
    pr_refs = {e.ref for e in ev if e.kind == "pr"}
    assert pr_refs == {"owner1/repoA#1", "owner2/repoB#1"}


def test_authored_file_ref_format_cross_repo():
    """One `kind='file'` Evidence per changed file with ref formatted exactly as
    `<owner>/<repo>:<path>` — Done-when: cross-repo file ref format."""
    ev = parse_authored_pr_evidence(_SEARCH_TWO_REPOS, _FILES_TWO_REPOS)
    file_refs = {e.ref for e in ev if e.kind == "file"}
    assert file_refs == {"owner1/repoA:cli.py", "owner2/repoB:cli.py"}


def test_authored_pr_ref_uniqueness_across_repos():
    """Two PRs with number==1 in different repos produce two distinct refs —
    Done-when: ref-uniqueness across repos for colliding PR numbers."""
    ev = parse_authored_pr_evidence(_SEARCH_TWO_REPOS, _FILES_TWO_REPOS)
    pr_refs = [e.ref for e in ev if e.kind == "pr"]
    # both distinct despite same number
    assert len(pr_refs) == 2
    assert "owner1/repoA#1" in pr_refs
    assert "owner2/repoB#1" in pr_refs


def test_authored_file_ref_uniqueness_across_repos():
    """Two PRs touching cli.py in different repos produce two distinct file refs —
    Done-when: ref-uniqueness across repos for colliding file paths."""
    ev = parse_authored_pr_evidence(_SEARCH_TWO_REPOS, _FILES_TWO_REPOS)
    file_refs = [e.ref for e in ev if e.kind == "file"]
    assert len(file_refs) == 2
    assert "owner1/repoA:cli.py" in file_refs
    assert "owner2/repoB:cli.py" in file_refs


def test_authored_missing_files_entry_emits_pr_no_files():
    """A PR whose file-enrichment entry is missing in files_by_pr still emits its
    PR Evidence and emits zero file Evidence for that PR — parser-level graceful
    degradation (Done-when: missing files_by_pr entry)."""
    ev = parse_authored_pr_evidence(_SEARCH_TWO_REPOS, {})  # no files at all
    pr_refs = {e.ref for e in ev if e.kind == "pr"}
    file_refs = list(e.ref for e in ev if e.kind == "file")
    assert pr_refs == {"owner1/repoA#1", "owner2/repoB#1"}
    assert file_refs == []


def test_authored_empty_files_entry_emits_pr_no_files():
    """A PR whose file-enrichment entry is empty in files_by_pr still emits its
    PR Evidence and emits zero file Evidence for that PR — parser-level graceful
    degradation (Done-when: empty files_by_pr entry)."""
    empty_files: dict = {
        "https://github.com/owner1/repoA/pull/1": [],
        "https://github.com/owner2/repoB/pull/1": [],
    }
    ev = parse_authored_pr_evidence(_SEARCH_TWO_REPOS, empty_files)
    pr_refs = {e.ref for e in ev if e.kind == "pr"}
    file_refs = list(e.ref for e in ev if e.kind == "file")
    assert pr_refs == {"owner1/repoA#1", "owner2/repoB#1"}
    assert file_refs == []


# ---------------------------------------------------------------------------
# extract_authored_prs — injected fake runner (no live `gh`)
# ---------------------------------------------------------------------------

# Fake search output with 3 PRs across 2 repos
_FAKE_SEARCH = json.dumps(
    [
        {
            "number": 10,
            "title": "Fix A",
            "url": "https://github.com/org/alpha/pull/10",
            "repository": {"nameWithOwner": "org/alpha"},
        },
        {
            "number": 20,
            "title": "Fix B",
            "url": "https://github.com/org/beta/pull/20",
            "repository": {"nameWithOwner": "org/beta"},
        },
        {
            "number": 30,
            "title": "Fix C",
            "url": "https://github.com/org/alpha/pull/30",
            "repository": {"nameWithOwner": "org/alpha"},
        },
    ]
)

_PR10_URL = "https://github.com/org/alpha/pull/10"
_PR20_URL = "https://github.com/org/beta/pull/20"
_PR30_URL = "https://github.com/org/alpha/pull/30"


def _make_runner(fail_url: str | None = None) -> tuple:
    """Return (runner, recorded_calls).

    The runner responds to `gh search prs ...` with _FAKE_SEARCH.
    For `gh pr view <url> --json files,...`, it returns a files payload
    unless the url matches `fail_url`, in which case it raises RuntimeError.
    `recorded_calls` accumulates every argv list the runner is called with.
    """
    recorded: list[list[str]] = []

    def runner(args: list[str]) -> str:
        recorded.append(list(args))
        if args[0] == "search":
            return _FAKE_SEARCH
        if args[0] == "pr" and args[1] == "view":
            url = args[2]
            if fail_url is not None and url == fail_url:
                raise RuntimeError(f"simulated failure for {url}")
            return json.dumps({"files": [{"path": "main.py"}]})
        raise RuntimeError(f"unexpected args: {args}")

    return runner, recorded


def test_extract_authored_prs_phase2_failure_graceful():
    """When phase-2 `pr view` raises for one PR, that PR's `kind='pr'` Evidence is
    still emitted, zero `kind='file'` Evidence for it, other PRs still enriched —
    Done-when: graceful degradation on a failed `pr view`."""
    runner, _ = _make_runner(fail_url=_PR20_URL)
    ev = extract_authored_prs(author="alice", runner=runner)

    pr_refs = {e.ref for e in ev if e.kind == "pr"}
    # All 3 PRs are present
    assert "org/alpha#10" in pr_refs
    assert "org/beta#20" in pr_refs
    assert "org/alpha#30" in pr_refs

    # No file Evidence for the failed PR
    file_refs = {e.ref for e in ev if e.kind == "file"}
    assert not any(r.startswith("org/beta:") for r in file_refs)

    # Other PRs have file Evidence
    assert "org/alpha:main.py" in file_refs or any(r.startswith("org/alpha:") for r in file_refs)


def test_extract_authored_prs_returns_successfully_on_phase2_failure():
    """extract_authored_prs does NOT propagate a phase-2 failure — Done-when:
    function returns successfully (no exception leaks out)."""
    runner, _ = _make_runner(fail_url=_PR10_URL)
    # must not raise
    ev = extract_authored_prs(author="alice", runner=runner)
    assert isinstance(ev, list)


def test_extract_authored_prs_bounded_by_limit():
    """When fake phase-1 returns more PRs than `limit`, no more than `limit` phase-2
    invocations are recorded — Done-when: limit bounds phase-2 calls."""
    runner, recorded = _make_runner()
    extract_authored_prs(author="alice", limit=2, runner=runner)
    # phase-1 call: 1; phase-2 calls: at most 2
    pr_view_calls = [c for c in recorded if c[0] == "pr" and c[1] == "view"]
    assert len(pr_view_calls) <= 2


def test_extract_authored_prs_author_as_separate_argv_token():
    """The `author` value reaches the fake `gh` seam ONLY as a separate argv token
    in a list[str] — never inlined into a single shell string.
    Done-when: no-shell-string-building hard rule."""
    runner, recorded = _make_runner()
    extract_authored_prs(author="alice", runner=runner)
    search_call = next(c for c in recorded if c[0] == "search")
    # "--author" and "alice" must be adjacent separate tokens, not "—-author=alice"
    # or any form where alice is baked into a single string with other content.
    assert "--author" in search_call
    author_idx = search_call.index("--author")
    assert search_call[author_idx + 1] == "alice"
