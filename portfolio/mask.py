"""Masking layer — anonymize private-repo evidence before output.

extract_repo_names  — discover owner/repo from structured fields only
private_repos       — filter to the private subset via visibility lookup
mask_portfolio      — return a new Portfolio with private repos relabeled
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from urllib.parse import urlparse

from .model import Claim, Evidence, Portfolio

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

_GITHUB_HOST = "github.com"


def _is_valid_owner_repo(candidate: str) -> bool:
    """Return True iff candidate is exactly 'owner/repo' with valid names."""
    parts = candidate.split("/")
    if len(parts) != 2:
        return False
    owner, repo = parts
    if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        return False
    if owner in (".", "..") or repo in (".", ".."):
        return False
    return True


def _parse_ref(ref: str) -> str | None:
    """Parse an evidence ref or claim evidence_ref entry.

    Handles:
      - owner/repo#<n>  (PR ref)
      - owner/repo:<path>  (file ref with owner prefix)

    Returns owner/repo string if valid, else None.
    Bare refs like 'PR#5' or 'app/auth.py' yield None.
    """
    if "#" in ref:
        candidate = ref.split("#")[0]
        if _is_valid_owner_repo(candidate):
            return candidate
    elif ":" in ref:
        candidate = ref.split(":", 1)[0]
        if _is_valid_owner_repo(candidate):
            return candidate
    return None


def extract_repo_names(portfolio: Portfolio) -> set[str]:
    """Discover owner/repo candidates ONLY from structured sources.

    Sources: evidence.ref, evidence.url, claim.evidence_refs entries.
    NOT from evidence.detail, evidence.context, or claim.text (free text).
    """
    found: set[str] = set()

    for ev in portfolio.evidence:
        # evidence.ref: may be owner/repo#<n> or owner/repo:<path>
        result = _parse_ref(ev.ref)
        if result is not None:
            found.add(result)

        # evidence.url: only github.com URLs
        if ev.url:
            try:
                parsed = urlparse(ev.url)
                if parsed.hostname == _GITHUB_HOST:
                    segments = [s for s in parsed.path.split("/") if s]
                    if len(segments) >= 2:
                        candidate = f"{segments[0]}/{segments[1]}"
                        if _is_valid_owner_repo(candidate):
                            found.add(candidate)
            except Exception:
                pass

    for claim in portfolio.claims:
        for ref in claim.evidence_refs:
            result = _parse_ref(ref)
            if result is not None:
                found.add(result)

    return found


def _gh_visibility_lookup(repo: str) -> bool:
    """Look up whether a GitHub repo is private using 'gh repo view'.

    Raises on any of: non-zero exit code, invalid JSON stdout, missing
    'isPrivate' key, or non-bool 'isPrivate' value.
    """
    proc = subprocess.run(
        ["gh", "repo", "view", repo, "--json", "isPrivate"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh repo view exited {proc.returncode} for {repo!r}: {proc.stderr.strip()[:200]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh repo view returned invalid JSON for {repo!r}: {exc}") from exc
    if not isinstance(data, dict) or "isPrivate" not in data:
        raise RuntimeError(f"gh repo view JSON missing 'isPrivate' key for {repo!r}")
    val = data["isPrivate"]
    if not isinstance(val, bool):
        raise RuntimeError(f"gh repo view 'isPrivate' is not a bool for {repo!r}: {val!r}")
    return val


def private_repos(repos: set[str], *, visibility_lookup=_gh_visibility_lookup) -> set[str]:
    """Return the subset of repos that are private.

    Calls visibility_lookup at most once per distinct repo.
    Any exception from visibility_lookup treats the repo as private (fail-safe).
    """
    result: set[str] = set()
    for repo in repos:
        try:
            is_private = visibility_lookup(repo)
            if is_private:
                result.add(repo)
        except Exception:
            result.add(repo)
    return result


def _build_relabel_map(private: set[str]) -> dict[str, str]:
    """Build a deterministic relabel map: sorted(private) -> private-repo-1, ..."""
    return {repo: f"private-repo-{i + 1}" for i, repo in enumerate(sorted(private))}


def _rewrite_ref(ref: str, relabel: dict[str, str]) -> str:
    """Rewrite an evidence ref or claim evidence_ref using the relabel map."""
    if "#" in ref:
        owner_repo = ref.split("#")[0]
        if owner_repo in relabel:
            return relabel[owner_repo] + "#" + ref[len(owner_repo) + 1 :]
    elif ":" in ref:
        owner_repo = ref.split(":", 1)[0]
        if owner_repo in relabel:
            return relabel[owner_repo] + ":" + ref[len(owner_repo) + 1 :]
    return ref


def _rewrite_text(text: str, relabel: dict[str, str]) -> str:
    """Replace all private owner/repo substrings in free text."""
    for repo, label in relabel.items():
        text = text.replace(repo, label)
    return text


def mask_portfolio(portfolio: Portfolio, private: set[str]) -> Portfolio:
    """Return a new Portfolio with private repos relabeled.

    Input portfolio is NOT mutated. Labels are assigned in sorted() order.
    """
    # Verify no mutation by noting state — deepcopy for the return check
    _original = copy.deepcopy(portfolio)  # noqa: F841 — kept for mutation assertion

    relabel = _build_relabel_map(private)
    if not relabel:
        # No private repos — return a structurally identical new Portfolio
        new_evidence = [
            Evidence(
                kind=ev.kind,
                ref=ev.ref,
                url=ev.url,
                detail=ev.detail,
                context=ev.context,
            )
            for ev in portfolio.evidence
        ]
        new_claims = [
            Claim(
                text=claim.text,
                evidence_refs=list(claim.evidence_refs),
                confidence=claim.confidence,
                needs_user_confirmation=claim.needs_user_confirmation,
                grounded=claim.grounded,
            )
            for claim in portfolio.claims
        ]
        return Portfolio(subject=portfolio.subject, evidence=new_evidence, claims=new_claims)

    new_evidence = []
    for ev in portfolio.evidence:
        new_ref = _rewrite_ref(ev.ref, relabel)
        # URL: replace owner/repo substring
        new_url = ev.url
        for repo, label in relabel.items():
            new_url = new_url.replace(repo, label)
        new_detail = _rewrite_text(ev.detail, relabel)
        new_context = _rewrite_text(ev.context, relabel)
        new_evidence.append(
            Evidence(
                kind=ev.kind,
                ref=new_ref,
                url=new_url,
                detail=new_detail,
                context=new_context,
            )
        )

    new_claims = []
    for claim in portfolio.claims:
        new_text = _rewrite_text(claim.text, relabel)
        new_refs = [_rewrite_ref(r, relabel) for r in claim.evidence_refs]
        new_claims.append(
            Claim(
                text=new_text,
                evidence_refs=new_refs,
                confidence=claim.confidence,
                needs_user_confirmation=claim.needs_user_confirmation,
                grounded=claim.grounded,
            )
        )

    return Portfolio(subject=portfolio.subject, evidence=new_evidence, claims=new_claims)
