"""Deterministic evidence extraction via the `gh` CLI.

This is the *ground truth* layer: it pulls a developer's real merged PRs (and
their changed files) and turns them into Evidence records. A model never adds to
this set — it may only write narrative that cites refs produced here. All calls
are argv lists (no shell), mirroring the harness trust model.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from .model import Evidence

_PR_FIELDS = "number,title,url,mergedAt,files,additions,deletions"
_SEARCH_FIELDS = "number,title,url,repository"

# Files excluded from a PR's counted change size. The point of the change-scale
# metric is to reflect real coding effort, so config/data/markup/docs (mirrors
# rating's stack-diversity exclusion) plus generated/vendored/lockfiles are
# dropped — a reformat or a regenerated lockfile would otherwise inflate the
# count by thousands of lines. Path-based (extraction's domain); kept separate
# from rating.profile's language-name exclusion by design (different layers).
_NON_CODE_EXTS = frozenset({".yaml", ".yml", ".json", ".md", ".html", ".css"})
_LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "cargo.lock",
        "go.sum",
        "gemfile.lock",
        "composer.lock",
    }
)
_GENERATED_DIR_SEGMENTS = frozenset({"vendor", "node_modules", "dist", "build"})


def _counts_toward_change_size(path: str) -> bool:
    """True if a changed file's lines should count toward a PR's change size.

    Excludes config/data/markup/doc files, lockfiles, minified/generated output,
    and vendored/build directories — none reflect coding effort and all inflate
    line counts. Comparison is case-insensitive."""
    if not path:
        return False
    p = path.lower()
    segments = p.split("/")
    name = segments[-1]
    if name in _LOCKFILE_NAMES:
        return False
    if any(seg in _GENERATED_DIR_SEGMENTS for seg in segments[:-1]):
        return False
    if name.endswith((".min.js", ".min.css", ".pb.go")) or "_pb2." in name or ".generated." in name:
        return False
    ext = "" if "." not in name else "." + name.rsplit(".", 1)[-1]
    return ext not in _NON_CODE_EXTS


def _change_size(files: list[dict]) -> tuple[int, int]:
    """Sum (additions, deletions) over a PR's changed files, counting code files
    only. Per-file line numbers come from `gh`'s `files` field; a file missing
    them contributes 0 (graceful degradation, never a crash)."""
    additions = sum(int(f.get("additions") or 0) for f in files if _counts_toward_change_size(f.get("path", "")))
    deletions = sum(int(f.get("deletions") or 0) for f in files if _counts_toward_change_size(f.get("path", "")))
    return additions, deletions


def _run_gh(args: list[str]) -> str:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
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
        files = pr.get("files") or []
        # Stored line counts are CODE-file only (for the change-scale metric);
        # the human `detail` keeps gh's raw PR-level totals for display.
        additions, deletions = _change_size(files)
        evidence.append(
            Evidence(
                kind="pr",
                ref=f"PR#{num}",
                url=pr.get("url", ""),
                detail=f"{pr.get('title', '')} (+{pr.get('additions', 0)}/-{pr.get('deletions', 0)})",
                additions=additions,
                deletions=deletions,
            )
        )
        for f in files:
            path = f.get("path")
            if path and path not in seen_files:
                seen_files.add(path)
                evidence.append(Evidence(kind="file", ref=path, detail=f"changed in PR#{num}"))
    return evidence


def extract_merged_prs(repo: str, author: str, limit: int = 100) -> list[Evidence]:
    """Merged PRs authored by `author` in `owner/repo`, as Evidence. Hits the
    network via `gh`; the parsing is delegated to the pure `parse_pr_evidence`."""
    out = _run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--author",
            author,
            "--state",
            "merged",
            "--limit",
            str(limit),
            "--json",
            _PR_FIELDS,
        ]
    )
    return parse_pr_evidence(out)


def parse_authored_pr_evidence(
    search_json: str,
    files_by_pr: dict[str, list[dict]],
) -> list[Evidence]:
    """Turn `gh search prs --json number,title,url,repository` output and a
    per-PR files mapping into Evidence records: one `kind="pr"` per hit (ref
    `<owner>/<repo>#<number>`) plus one `kind="file"` per changed file (ref
    `<owner>/<repo>:<path>`).

    `files_by_pr` keys are the PR URL strings; the value is a list of file
    dicts with a `path` key (and optional `additions`/`deletions`, as returned by
    `gh pr view --json files`). A missing or empty files entry for a PR is
    silently skipped (graceful degradation) and yields 0 change size. Pure
    function — unit-testable without a live `gh`."""
    data = json.loads(search_json)
    evidence: list[Evidence] = []
    for pr in data:
        num = pr.get("number")
        url = pr.get("url", "")
        repo_info = pr.get("repository") or {}
        name_with_owner = repo_info.get("nameWithOwner", "")
        pr_ref = f"{name_with_owner}#{num}"
        files = files_by_pr.get(url) or []
        additions, deletions = _change_size(files)
        evidence.append(
            Evidence(
                kind="pr",
                ref=pr_ref,
                url=url,
                detail=pr.get("title", ""),
                additions=additions,
                deletions=deletions,
            )
        )
        for f in files:
            path = f.get("path")
            if path:
                file_ref = f"{name_with_owner}:{path}"
                evidence.append(Evidence(kind="file", ref=file_ref, detail=f"changed in {pr_ref}"))
    return evidence


def extract_authored_prs(
    author: str,
    limit: int = 100,
    runner: Callable[[list[str]], str] = _run_gh,
) -> list[Evidence]:
    """Author-wide merged PRs across all repos the `gh` token can see.

    Phase 1: `gh search prs --author <author> --merged` — one PR per hit.
    Phase 2: per-PR `gh pr view <url> --json files,additions,deletions` — file
             enrichment. A failed/empty view for one PR does NOT abort the run:
             that PR's Evidence is kept, its files are skipped, and extraction
             continues. Bounded by `limit`.

    `runner` is an injectable seam (default `_run_gh`) for testing without a
    live `gh`: it receives an argv list and returns the stdout string, or raises
    on failure."""
    # Phase 1 — search
    search_out = runner(
        [
            "search",
            "prs",
            "--author",
            author,
            "--merged",
            "--json",
            _SEARCH_FIELDS,
            "--limit",
            str(limit),
        ]
    )
    search_data = json.loads(search_out)

    # Phase 2 — per-PR file enrichment (graceful degradation on failure)
    files_by_pr: dict[str, list[dict]] = {}
    for pr in search_data[:limit]:
        url = pr.get("url", "")
        if not url:
            continue
        try:
            view_out = runner(["pr", "view", url, "--json", "files,additions,deletions"])
            view_data = json.loads(view_out)
            files_by_pr[url] = view_data.get("files") or []
        except Exception:
            # Graceful degradation: keep the PR Evidence, emit no file Evidence
            files_by_pr[url] = []

    return parse_authored_pr_evidence(search_out, files_by_pr)
