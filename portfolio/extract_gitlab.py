"""Deterministic evidence extraction via the ``glab`` CLI.

Extracts a developer's merged Merge Requests from GitLab and turns them into
Evidence records. Mirrors the design of ``extract.py`` (``_run_gh`` /
``extract_merged_prs`` / ``parse_pr_evidence``) so tests can inject a fake
runner and run without a live ``glab`` binary.

Ref format
----------
``<owner>/<project-path>!<iid>``

- For gitlab.com sources, ``<owner>/<project-path>`` is the bare namespace path
  returned by ``parse_gitlab_source`` (e.g. ``group/subgroup/project!42``).
- For self-managed GitLab sources, it is host-qualified:
  ``<host>/<owner>/<project-path>!<iid>``
  (e.g. ``gitlab.corp.io/group/subgroup/project!5``).

The ``!<iid>`` suffix follows GitLab's conventional MR notation and is stable
within the project for the lifetime of the MR.  The ref is constructed from
``references.full`` in the ``glab mr list`` JSON when available; otherwise it
falls back to ``<project>!<iid>`` using the project spec the extractor was
called with.

``glab`` commands
-----------------
Project-scoped (``gitlab`` source type)::

    glab mr list --repo <project-spec> --author <author> --merged \
        --output json --limit <limit>

Author-wide (``gitlab-author`` source type)::

    glab mr list --author <author> --merged --output json --limit <limit>

Per-MR changes (best-effort, requires authenticated ``glab``)::

    glab api projects/<project_id>/merge_requests/<iid>/changes

``<project-spec>`` is whatever ``parse_gitlab_source`` returns — bare
``namespace/project`` for gitlab.com, ``host/namespace/project`` for
self-managed GitLab (the form ``glab --repo`` accepts).

All subprocess calls use ``shell=False`` (argv list) and accept an injectable
``runner`` so tests can substitute a fake without a real ``glab`` binary.
Additions/deletions are taken from the per-MR changes payload when the
enrichment succeeds; otherwise they default to 0 (graceful degradation, never
a crash).  The per-MR enrichment is an N+1 call (one extra ``glab api`` call
per merged MR) — bounded by the same ``limit`` as the MR list.  Pagination of
the ``changes`` response is NOT implemented in v1; very large MRs may silently
truncate the changed-file list.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable

from .extract import _counts_toward_change_size
from .model import Evidence

# Redacts GitLab-format tokens (glpat-..., gloas-..., glcbt-..., etc.) from
# error text before it is surfaced in RuntimeError messages or logs.
_TOKEN_RE = re.compile(r"gl[a-z]+-[A-Za-z0-9_-]{10,}")


def _sanitize_stderr(text: str) -> str:
    """Redact token-shaped values from glab stderr before including in errors."""
    return _TOKEN_RE.sub("[REDACTED]", text)


def _run_glab(args: list[str]) -> str:
    """Run ``glab`` with the given argv list and return stdout.

    Raises ``RuntimeError`` on non-zero exit (stderr is truncated to 500 chars
    and token-shaped values are redacted before inclusion — no token reaches the
    error message).  Lets ``FileNotFoundError`` propagate so callers can surface
    a clean "glab not installed" message.
    """
    proc = subprocess.run(
        ["glab", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        sanitized = _sanitize_stderr(proc.stderr.strip()[:500])
        raise RuntimeError(f"glab {' '.join(args[:3])} failed (rc={proc.returncode}): {sanitized}")
    return proc.stdout


def _count_diff_lines(diff_text: str) -> tuple[int, int]:
    """Count added/deleted lines in a single file's unified diff text.

    Counts only lines whose first character is ``+`` or ``-`` AND which are
    NOT file-header lines (``+++``/``---``), hunk headers (``@@``), context
    lines, or the ``\\ No newline at end of file`` marker.

    Pure function — no I/O.
    """
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if not line:
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("\\ "):
            continue
        if line[0] == "+":
            additions += 1
        elif line[0] == "-":
            deletions += 1
    return additions, deletions


def parse_mr_changes(
    changes_json: str,
    mr_ref: str,
) -> tuple[int, int, list[Evidence]]:
    """Parse a ``glab api …/merge_requests/<iid>/changes`` response.

    Accepts both the envelope form ``{"changes": [...]}`` and a bare list.
    Each entry must have ``new_path``, ``old_path``, ``diff``, and optionally
    ``new_file``, ``deleted_file``, ``renamed_file`` boolean fields.

    Applies the same code-only filter as the GitHub path
    (``_counts_toward_change_size`` from ``extract.py``) — lockfiles, vendored
    directories, and non-code extensions are excluded.

    Returns ``(additions, deletions, file_evidence)`` where:
    - ``additions`` / ``deletions`` are the code-only sums across all changed files.
    - ``file_evidence`` is one ``Evidence(kind="file", ref=<bare path>,
      detail="changed in <mr_ref>")`` per changed CODE file.  The ``ref`` is
      ``new_path`` for additions/modifications and ``old_path`` for deletions —
      a bare file path with NO host, owner, or project prefix.

    Pure function — no I/O, no subprocess calls.  Degrades to ``(0, 0, [])``
    if the payload cannot be parsed.
    """
    try:
        data = json.loads(changes_json)
    except (json.JSONDecodeError, ValueError):
        return 0, 0, []

    if isinstance(data, dict):
        changes = data.get("changes", [])
    elif isinstance(data, list):
        changes = data
    else:
        return 0, 0, []

    total_add = 0
    total_del = 0
    file_evidence: list[Evidence] = []

    for change in changes:
        if not isinstance(change, dict):
            continue
        new_path = change.get("new_path") or ""
        old_path = change.get("old_path") or ""
        deleted = change.get("deleted_file", False)

        # Use old_path as the ref for deleted files (new_path is /dev/null)
        file_path = old_path if deleted else (new_path or old_path)

        if not _counts_toward_change_size(file_path):
            continue

        diff_text = change.get("diff") or ""
        add, delete = _count_diff_lines(diff_text)
        total_add += add
        total_del += delete

        file_evidence.append(
            Evidence(
                kind="file",
                ref=file_path,
                detail=f"changed in {mr_ref}",
            )
        )

    return total_add, total_del, file_evidence


def _enrich_mr_with_changes(
    mr: dict,
    mr_ref: str,
    runner: "Callable[[list[str]], str]",
) -> tuple[int, int, list[Evidence]]:
    """Fetch and parse per-MR changes via the injectable runner.

    Best-effort: any exception (auth, transport, parse, missing project_id)
    silently degrades to ``(0, 0, [])``.  Tokens and raw stderr never appear
    in the return value or in any log — all exceptions are swallowed.
    """
    try:
        project_id = mr.get("project_id")
        iid = mr.get("iid")
        if project_id is None or iid is None:
            return 0, 0, []
        out = runner(["api", f"projects/{project_id}/merge_requests/{iid}/changes"])
        return parse_mr_changes(out, mr_ref)
    except Exception:  # noqa: BLE001  — best-effort; must not propagate
        return 0, 0, []


def parse_gitlab_mr_evidence(mr_json: str, project: str = "") -> list[Evidence]:
    """Convert ``glab mr list --output json`` output into Evidence records.

    One ``kind="pr"`` Evidence per MR entry in the payload.

    Ref format: ``<owner>/<project-path>!<iid>`` — see module docstring.
    The ref is taken from ``references.full`` in the payload when present;
    otherwise it is constructed as ``<project>!<iid>`` (``project`` parameter
    as fallback), or ``!<iid>`` if neither is available.

    ``additions`` and ``deletions`` are taken from the payload as integers when
    present; missing or null values produce 0 (graceful degradation, not crash).

    Pure function — unit-testable without a live ``glab``.
    """
    data = json.loads(mr_json)
    evidence: list[Evidence] = []
    for mr in data:
        iid = mr.get("iid")
        references = mr.get("references") or {}
        full_ref = references.get("full")
        if full_ref:
            ref = full_ref  # e.g. "group/subgroup/project!42"
        elif project and iid is not None:
            ref = f"{project}!{iid}"
        else:
            ref = f"!{iid}"

        url = mr.get("web_url", "")
        additions = int(mr.get("additions") or 0)
        deletions = int(mr.get("deletions") or 0)
        title = mr.get("title", "")
        detail = f"{title} (+{additions}/-{deletions})"

        evidence.append(
            Evidence(
                kind="pr",
                ref=ref,
                url=url,
                detail=detail,
                additions=additions,
                deletions=deletions,
            )
        )
    return evidence


def extract_merged_mrs(
    project: str,
    author: str,
    limit: int = 100,
    runner: Callable[[list[str]], str] = _run_glab,
) -> list[Evidence]:
    """Project-scoped merged MRs authored by ``author``, as Evidence.

    Shells ``glab mr list --repo <project> --author <author> --merged
    --output json --limit <limit>`` (argv list, no ``shell=True``).

    ``project`` must be the spec returned by ``parse_gitlab_source``:
    bare ``namespace/project`` for gitlab.com, ``host/namespace/project``
    for self-managed GitLab.  ``runner`` is injectable for testing (default
    ``_run_glab``); it receives an argv list and returns the stdout string.

    Raises ``RuntimeError`` (with a message that names ``glab``) on any of:
    ``glab`` binary not found, non-zero exit code.
    """
    try:
        out = runner(
            [
                "mr",
                "list",
                "--repo",
                project,
                "--author",
                author,
                "--merged",
                "--output",
                "json",
                "--limit",
                str(limit),
            ]
        )
    except FileNotFoundError:
        raise RuntimeError(
            "glab is not installed or not on PATH. "
            "Install it from https://gitlab.com/gitlab-org/cli and authenticate "
            "with: glab auth login"
        )
    mr_evidence = parse_gitlab_mr_evidence(out, project)
    return _enrich_evidence_list(json.loads(out), mr_evidence, runner)


def _enrich_evidence_list(
    mr_list: list[dict],
    mr_evidence: list[Evidence],
    runner: Callable[[list[str]], str],
) -> list[Evidence]:
    """Enrich each ``kind="pr"`` Evidence with per-MR changes (best-effort).

    For each MR, fetches ``glab api projects/<id>/merge_requests/<iid>/changes``
    through the injectable runner.  The ``kind="pr"`` Evidence is always replaced
    with one that carries the enrichment result: code-only additions/deletions and
    ``detail`` ending with ``(+A/-D)``.  Per-file ``kind="file"`` Evidence records
    are appended on success.  Any failure (including missing ``project_id``) silently
    degrades that MR to ``0/0`` with no file evidence; the list-level additions/
    deletions from ``glab mr list`` are never used — stale stats must not leak.
    Other MRs are unaffected.
    """
    result: list[Evidence] = []
    for mr, ev in zip(mr_list, mr_evidence):
        add, delete, file_ev = _enrich_mr_with_changes(mr, ev.ref, runner)
        # Always create enriched Evidence from the enrichment result (never fall
        # back to the original ev, which may carry stale MR-list additions/deletions).
        title = mr.get("title", "")
        enriched = Evidence(
            kind="pr",
            ref=ev.ref,
            url=ev.url,
            detail=f"{title} (+{add}/-{delete})",
            additions=add,
            deletions=delete,
        )
        result.append(enriched)
        result.extend(file_ev)
    return result


def extract_authored_mrs(
    author: str,
    limit: int = 100,
    runner: Callable[[list[str]], str] = _run_glab,
) -> list[Evidence]:
    """Author-wide merged MRs across all projects the ``glab`` token can see.

    Shells ``glab mr list --author <author> --merged --output json
    --limit <limit>`` (argv list, no ``shell=True``).  ``runner`` is injectable
    for testing (default ``_run_glab``).

    Raises ``RuntimeError`` (with a message that names ``glab``) on any of:
    ``glab`` binary not found, non-zero exit code.
    """
    try:
        out = runner(
            [
                "mr",
                "list",
                "--author",
                author,
                "--merged",
                "--output",
                "json",
                "--limit",
                str(limit),
            ]
        )
    except FileNotFoundError:
        raise RuntimeError(
            "glab is not installed or not on PATH. "
            "Install it from https://gitlab.com/gitlab-org/cli and authenticate "
            "with: glab auth login"
        )
    mr_evidence = parse_gitlab_mr_evidence(out)
    return _enrich_evidence_list(json.loads(out), mr_evidence, runner)
