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

# ---------------------------------------------------------------------------
# Evidence denylist — pinned in code; a model NEVER contributes to this set.
# Same design principle as _EXT_TO_LANG in rating/profile.py.
#
# Single constant encoding all four rule classes (see _is_denied_path for semantics):
#   "dir_segments"       — rule (a): any "/"-separated segment must NOT exactly match
#   "exact_filenames"    — rule (b): final segment must NOT exactly match
#   "filename_suffix"    — rule (b): final segment must NOT end with this suffix
#   "segment_sequences"  — rules (c)+(d): no consecutive-segment sub-sequence may match;
#                          a length-1 tuple matches any single segment at ANY depth.
# ---------------------------------------------------------------------------
_EVIDENCE_DENYLIST: dict[str, object] = {
    # (a) Build-output / vendored-dependency / IDE-metadata directory names.
    #     Note: "build.gradle" ≠ "build" — a filename token is NOT a dir segment.
    "dir_segments": frozenset(
        {
            # Build output
            "target",
            "build",
            "dist",
            "out",
            "bin",
            ".next",
            "__pycache__",
            # Vendored dependencies
            "node_modules",
            "vendor",
            ".venv",
            # IDE / tooling metadata directory names
            ".settings",
            ".idea",
            ".vscode",
        }
    ),
    # (b) Generated IDE metadata filenames (final path segment — exact match).
    "exact_filenames": frozenset({".classpath", ".project", ".springBeans"}),
    # (b) IntelliJ module file suffix (final path segment — suffix match).
    "filename_suffix": ".iml",
    # (c) META-INF/maven — generated Maven manifest metadata at any nesting depth.
    # (d) m2e-wtp — Eclipse m2e web-tools-platform generated resources (single segment).
    #     Length-1 tuples are checked as "any single segment equals this value at ANY depth."
    "segment_sequences": (
        ("META-INF", "maven"),
        ("m2e-wtp",),
    ),
}


def _is_denied_path(path: str) -> bool:
    """Return True iff the given BARE file path should be excluded from Evidence(kind="file").

    Accepts a bare repository path (e.g. "src/App.jsx"). It does NOT parse or
    strip any "<owner>/<repo>:" prefix — each extraction site passes the path
    component it already has. A single-repo bare git path may legally contain a
    colon (e.g. "src/generated:target/file.py"), so the path is NOT colon-split.

    Committed deterministic rule (single rule, non-ambiguous):
      Split the path on "/". Deny iff ANY of these hold:
      (a) any segment exactly equals a denied directory segment name, at ANY depth;
      (b) the final segment exactly matches a denied metadata filename or ends with ".iml";
      (c) the segment sequence contains "META-INF" immediately followed by "maven", at
          any depth;
      (d) any segment equals "m2e-wtp", at any depth.

    Does NOT over-match on filenames: "src/components/target.ts" → KEPT ("target.ts" ≠
    "target"); root-level "build.gradle" → KEPT ("build.gradle" ≠ "build").
    "src/build/page.tsx" → DROPPED: the "build" dir segment matches at depth 1.

    All policy is read exclusively from _EVIDENCE_DENYLIST — that constant is the
    single source of truth; no rule is hard-coded in this function body.
    """
    segments = path.split("/")
    if not segments:
        return False

    final = segments[-1]

    _exact = _EVIDENCE_DENYLIST["exact_filenames"]
    _suffix = _EVIDENCE_DENYLIST["filename_suffix"]
    _dirs = _EVIDENCE_DENYLIST["dir_segments"]
    _seqs = _EVIDENCE_DENYLIST["segment_sequences"]

    # (b) exact metadata filename on the final segment
    if final in _exact:
        return True

    # (b) *.iml suffix on the final segment
    if final.endswith(_suffix):
        return True

    # (a) any segment exactly equals a denied directory segment name
    if any(seg in _dirs for seg in segments):
        return True

    # (c)+(d) consecutive-segment sequence rules (length-1 = any single segment)
    for seq in _seqs:
        n = len(seq)
        for i in range(len(segments) - n + 1):
            if tuple(segments[i : i + n]) == seq:
                return True

    return False


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
            if path and path not in seen_files and not _is_denied_path(path):
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
    dicts with a `path` key (as returned by `gh pr view --json files`).
    A missing or empty files entry for a PR is silently skipped (graceful
    degradation). Pure function — unit-testable without a live `gh`."""
    data = json.loads(search_json)
    evidence: list[Evidence] = []
    for pr in data:
        num = pr.get("number")
        url = pr.get("url", "")
        repo_info = pr.get("repository") or {}
        name_with_owner = repo_info.get("nameWithOwner", "")
        pr_ref = f"{name_with_owner}#{num}"
        evidence.append(
            Evidence(
                kind="pr",
                ref=pr_ref,
                url=url,
                detail=pr.get("title", ""),
            )
        )
        for f in files_by_pr.get(url) or []:
            path = f.get("path")
            if path and not _is_denied_path(path):
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
