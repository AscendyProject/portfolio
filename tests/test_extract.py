"""PR-evidence parsing is pure (no live `gh`): feed it `gh pr list --json` shapes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.extract import parse_pr_evidence  # noqa: E402

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
