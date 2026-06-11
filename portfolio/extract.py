"""Deterministic evidence extraction via the `gh` CLI.

This is the *ground truth* layer: it pulls a developer's real merged PRs (and
their changed files) and turns them into Evidence records. A model never adds to
this set — it may only write narrative that cites refs produced here. All calls
are argv lists (no shell), mirroring the harness trust model.
"""

from __future__ import annotations

import json
import subprocess

from .model import Evidence

_PR_FIELDS = "number,title,url,mergedAt,files,additions,deletions"


def _run_gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}")
    return proc.stdout


def parse_pr_evidence(pr_json: str) -> list[Evidence]:
    """Turn `gh pr list --json <_PR_FIELDS>` output into Evidence records: one per
    PR (ref `PR#<n>`) plus one per changed file (ref = path). Pure function —
    unit-testable without a live `gh`."""
    data = json.loads(pr_json)
    evidence: list[Evidence] = []
    seen_files: set[str] = set()
    for pr in data:
        num = pr.get("number")
        evidence.append(
            Evidence(
                kind="pr",
                ref=f"PR#{num}",
                url=pr.get("url", ""),
                detail=f"{pr.get('title', '')} (+{pr.get('additions', 0)}/-{pr.get('deletions', 0)})",
            )
        )
        for f in pr.get("files") or []:
            path = f.get("path")
            if path and path not in seen_files:
                seen_files.add(path)
                evidence.append(Evidence(kind="file", ref=path, detail=f"changed in PR#{num}"))
    return evidence


def extract_merged_prs(repo: str, author: str, limit: int = 100) -> list[Evidence]:
    """Merged PRs authored by `author` in `owner/repo`, as Evidence. Hits the
    network via `gh`; the parsing is delegated to the pure `parse_pr_evidence`."""
    out = _run_gh(
        ["pr", "list", "--repo", repo, "--author", author, "--state", "merged",
         "--limit", str(limit), "--json", _PR_FIELDS]
    )
    return parse_pr_evidence(out)
