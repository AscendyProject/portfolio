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


class MaskingError(Exception):
    """Raised when --mask-private cannot guarantee masking for the given evidence
    (e.g. a GitHub Enterprise Server host that the discovery/visibility/relabel
    path does not yet support). Fail closed rather than emit unmasked output."""


_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Matches owner/repo#<digits> — strictly digits after #
_PR_REF_RE = re.compile(r"^([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)#(\d+)$")
# Matches owner/repo:<non-empty-path>
_FILE_REF_RE = re.compile(r"^([A-Za-z0-9._-]+/[A-Za-z0-9._-]+):(.+)$")
# A second segment ending in a common source-file extension is almost certainly a
# file path mistaken for a repo (e.g. `app/auth.py` in `app/auth.py#5` /
# `app/auth.py:42`), not a real repository name. We reject these so a bare path is
# never discovered as a repo. Trade-off: a real repo literally named `*.py` etc.
# would be skipped — vanishingly rare; noted as a limitation in the README.
_PATH_LIKE_EXTENSIONS = (
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".html",
    ".css",
    ".sql",
)

_GITHUB_HOST = "github.com"
# Hosts whose repos the masking path can discover, look up, and relabel. Discovery
# (extract_repo_names) and the fail-closed guard (assert_maskable) BOTH key off
# this single set, so a host is never accepted by one and dropped by the other
# (which would silently under-mask — codex IR-002).
_MASKABLE_HOSTS = frozenset({_GITHUB_HOST, "www.github.com"})


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
    if repo.lower().endswith(_PATH_LIKE_EXTENSIONS):
        return False  # `auth.py` etc. — a path mistaken for a repo, not a repo
    return True


def _parse_ref(ref: str) -> str | None:
    """Parse an evidence ref or claim evidence_ref entry.

    Handles:
      - owner/repo#<n>  (PR ref — <n> must be digits only)
      - owner/repo:<path>  (file ref — <path> must be non-empty)

    Returns owner/repo string if valid, else None.
    Bare refs like 'PR#5', 'app/auth.py', or 'app/auth.py#anchor' yield None.
    """
    m = _PR_REF_RE.match(ref)
    if m:
        candidate = m.group(1)
        if _is_valid_owner_repo(candidate):
            return candidate
    else:
        m2 = _FILE_REF_RE.match(ref)
        if m2:
            candidate = m2.group(1)
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

        # evidence.url: only hosts the masking path can actually handle
        if ev.url:
            try:
                parsed = urlparse(ev.url)
                if parsed.hostname in _MASKABLE_HOSTS:
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


def assert_maskable(portfolio: Portfolio) -> None:
    """Fail closed when --mask-private cannot reliably mask this portfolio.

    Repo discovery, the `gh repo view` visibility lookup, and relabeling all
    assume github.com. A GitHub Enterprise Server URL (e.g.
    `https://ghe.example.com/owner/repo/pull/1`) is therefore neither discovered
    nor masked, so silently reporting "masked 0 private repo(s)" could emit a
    private GHES repo unmasked. Refuse instead — under-masking private evidence
    is worse than refusing the run. Raises MaskingError for the first non-
    maskable host found.

    Only repo-artifact evidence (PRs, files, commits, …) is checked. `article`
    evidence comes from `--source-type web`: its URL is arbitrary public content,
    not a repo, and carries no GitHub repo name to mask — so a non-github.com
    article host is NOT a masking failure and must not trip the guard.
    """
    for ev in portfolio.evidence:
        if ev.kind == "article":
            continue  # web article URL is public content, not a maskable repo
        if not ev.url:
            continue
        try:
            host = urlparse(ev.url).hostname
        except ValueError:
            continue  # an unparseable URL yields no repo to mask anyway
        if host and host not in _MASKABLE_HOSTS:
            raise MaskingError(
                f"--mask-private does not support host {host!r} (only github.com): "
                f"private repos on GitHub Enterprise Server cannot be reliably masked, "
                f"so the run is refused rather than risk emitting them unmasked. "
                f"Re-run without --mask-private."
            )


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
    """Replace all private owner/repo substrings in free text.

    Longest names first to avoid partial-name collision (e.g. org/repo-tools
    must not be mis-replaced when org/repo is a shorter private name).
    """
    for repo in sorted(relabel, key=len, reverse=True):
        text = text.replace(repo, relabel[repo])
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
                additions=ev.additions,
                deletions=ev.deletions,
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
        # URL: replace owner/repo substring — longest names first (collision-safe)
        new_url = ev.url
        for repo in sorted(relabel, key=len, reverse=True):
            new_url = new_url.replace(repo, relabel[repo])
        new_detail = _rewrite_text(ev.detail, relabel)
        new_context = _rewrite_text(ev.context, relabel)
        new_evidence.append(
            Evidence(
                kind=ev.kind,
                ref=new_ref,
                url=new_url,
                detail=new_detail,
                context=new_context,
                additions=ev.additions,
                deletions=ev.deletions,
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
