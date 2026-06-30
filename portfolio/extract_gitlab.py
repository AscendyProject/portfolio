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

``<project-spec>`` is whatever ``parse_gitlab_source`` returns — bare
``namespace/project`` for gitlab.com, ``host/namespace/project`` for
self-managed GitLab (the form ``glab --repo`` accepts).

All subprocess calls use ``shell=False`` (argv list) and accept an injectable
``runner`` so tests can substitute a fake without a real ``glab`` binary.
Additions/deletions are taken from the JSON payload when present; otherwise
they default to 0 (graceful degradation, never a crash).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable

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
    return parse_gitlab_mr_evidence(out, project)


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
    return parse_gitlab_mr_evidence(out)
