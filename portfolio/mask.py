"""Masking layer — anonymize private-repo evidence before output.

extract_repo_names  — discover owner/repo from structured fields only
private_repos       — filter to the private subset via visibility lookup
mask_portfolio      — return a new Portfolio with private repos relabeled

Identity key format
-------------------
github.com repos are keyed as bare ``owner/repo`` (lowercase) for backward
compatibility.  Repos on any other host (GitHub Enterprise Server or any
other DNS host) are keyed as ``host/owner/repo`` (lowercase).

Discovery is host-agnostic: any hostname whose URL path contains a valid
``owner/repo`` is collected; whether masking succeeds at runtime is governed
by the visibility-lookup fail-safe and the ``assert_maskable`` guard.
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
# GHES 3-segment variants: host/owner/repo#<digits> and host/owner/repo:<path>
_GHES_PR_REF_RE = re.compile(r"^([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)#(\d+)$")
_GHES_FILE_REF_RE = re.compile(r"^([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+):(.+)$")
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
# Hosts whose repos use the bare 'owner/repo' key (backward compatibility).
# Non-github.com hosts use the 'host/owner/repo' key instead.
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


def _parse_ghes_ref(ref: str) -> str | None:
    """Parse a GHES-style host/owner/repo ref, returning 'host/owner/repo' (lowercase).

    Handles:
      - host/owner/repo#<n>  (GHES PR ref)
      - host/owner/repo:<path>  (GHES file ref)

    Returns 'host/owner/repo' lowercase string if valid, else None.
    """
    m = _GHES_PR_REF_RE.match(ref)
    if not m:
        m = _GHES_FILE_REF_RE.match(ref)
    if not m:
        return None
    host, owner, repo = m.group(1), m.group(2), m.group(3)
    owner_repo = f"{owner}/{repo}"
    if _is_valid_owner_repo(owner_repo):
        return f"{host}/{owner_repo}".lower()
    return None


def extract_repo_names(portfolio: Portfolio) -> set[str]:
    """Discover repo identities ONLY from structured sources.

    Key format (see module docstring):
    - github.com repos → bare 'owner/repo' (lowercase)
    - Any other host  → 'host/owner/repo' (lowercase)

    Sources: evidence.ref, evidence.url, claim.evidence_refs entries.
    NOT from evidence.detail, evidence.context, or claim.text (free text).

    Discovery is host-agnostic for URLs: any hostname whose path contains a
    valid owner/repo pair is collected.  For refs, both the standard two-segment
    github.com form (owner/repo#n) and the three-segment GHES form
    (host/owner/repo#n) are recognised.  Whether the resulting key can be
    actually masked at runtime is decided by the visibility-lookup fail-safe
    and the assert_maskable guard — not here.
    """
    found: set[str] = set()

    for ev in portfolio.evidence:
        # evidence.ref: may be owner/repo#<n> or owner/repo:<path> (2-segment)
        # or host/owner/repo#<n> / host/owner/repo:<path> (3-segment GHES form)
        result = _parse_ref(ev.ref)
        if result is not None:
            found.add(result.lower())
        else:
            ghes_result = _parse_ghes_ref(ev.ref)
            if ghes_result is not None:
                found.add(ghes_result)

        # evidence.url: collect from any host (host-agnostic)
        if ev.url:
            try:
                parsed = urlparse(ev.url)
                host = parsed.hostname
                if host:
                    segments = [s for s in parsed.path.split("/") if s]
                    if len(segments) >= 2:
                        candidate = f"{segments[0]}/{segments[1]}"
                        if _is_valid_owner_repo(candidate):
                            if host in _MASKABLE_HOSTS:
                                found.add(candidate.lower())
                            else:
                                found.add(f"{host}/{candidate}".lower())
            except Exception:
                pass

    for claim in portfolio.claims:
        for ref in claim.evidence_refs:
            result = _parse_ref(ref)
            if result is not None:
                found.add(result.lower())
            else:
                ghes_result = _parse_ghes_ref(ref)
                if ghes_result is not None:
                    found.add(ghes_result)

    return found


def _ref_host(ref: str) -> str | None:
    """Return the host label if ``ref`` encodes a GHES-style ``host/owner/repo…``
    reference, else ``None``.

    A GHES ref has the form ``host/owner/repo#<n>`` or ``host/owner/repo:<path>``
    — three or more slash-separated segments before the ``#`` / ``:`` separator.
    A github.com-origin ref has the form ``owner/repo#<n>`` or
    ``owner/repo:<path>`` — exactly two segments; those return ``None``.
    Single-segment bare refs (e.g. ``PR#5``) also return ``None``.

    This uses the same segment-counting convention the rest of the masking layer
    uses for ref parsing (``_parse_ref`` / ``_PR_REF_RE`` / ``_FILE_REF_RE``):
    a two-segment prefix is always ``owner/repo``; a three-or-more-segment prefix
    carries a leading host label.
    """
    for sep in ("#", ":"):
        if sep in ref:
            prefix = ref.split(sep, 1)[0]
            parts = [p for p in prefix.split("/") if p]
            if len(parts) >= 3:
                return parts[0]  # first segment is the host label
            return None  # two-segment owner/repo or bare single-segment ref
    return None  # no # or : separator — not a structured repo ref


def assert_maskable(portfolio: Portfolio) -> None:
    """Fail closed when --mask-private cannot guarantee masking for the given evidence.

    Refuses ONLY when an evidence identity is *malformed* — i.e. the masking-layer
    discovery path cannot decompose it into a ``(host, owner, repo)`` triple at all:

    - ``ev.url`` is non-empty but ``urlparse(ev.url).hostname`` raises ``ValueError``
      or yields no host (empty / None).
    - ``ev.url`` hostname parses but the URL path has no recognizable ``owner/repo``
      segment (fewer than two non-empty path components, or those components fail
      ``_is_valid_owner_repo``).
    - ``ev.ref`` has a host prefix (three-or-more-segment form before ``#`` / ``:``)
      that does NOT decompose into a valid ``host/owner/repo`` via ``_parse_ghes_ref``
      (e.g. invalid name characters, path-like extension on the repo segment).

    Well-formed identities are ACCEPTED:

    - A URL whose hostname parses and whose path yields a valid ``owner/repo`` is
      accepted regardless of host (github.com OR any GHES / other DNS host).
    - A ref that ``_parse_ghes_ref`` successfully decomposes into ``host/owner/repo``
      is accepted; bare two-segment ``owner/repo`` refs (``_ref_host`` returns None)
      are also accepted.

    Visibility-lookup failures (non-zero exit, malformed JSON, unreachable host) are
    NOT a refusal — that is the ``private_repos`` fail-safe's job, which treats lookup
    errors as PRIVATE (mask), never as refusal. Only malformed identities trip this guard.

    Only repo-artifact evidence (PRs, files, commits, …) is checked. ``article``
    evidence (``--source-type web``) is public content with no repo to mask and is
    exempt from this check.
    """
    for ev in portfolio.evidence:
        if ev.kind == "article":
            continue  # web article URL is public content, not a maskable repo

        # Check ev.url: refuse if malformed, accept if well-formed (any host).
        if ev.url:
            try:
                parsed = urlparse(ev.url)
                host = parsed.hostname
            except ValueError:
                host = None
            if not host:
                raise MaskingError(
                    f"--mask-private: evidence URL {ev.url!r} has no parseable hostname; "
                    f"cannot determine repo identity. Re-run without --mask-private."
                )
            # Host is valid; now verify the path yields a recognizable owner/repo.
            segments = [s for s in parsed.path.split("/") if s]
            if len(segments) < 2 or not _is_valid_owner_repo(f"{segments[0]}/{segments[1]}"):
                raise MaskingError(
                    f"--mask-private: evidence URL {ev.url!r} path does not contain a "
                    f"recognizable owner/repo; cannot guarantee masking. "
                    f"Re-run without --mask-private."
                )
            # Well-formed URL (any host — github.com or GHES): accepted.

        # Check ev.ref for a malformed GHES-style host prefix.
        # A two-segment bare ref (owner/repo#n) has ref_host=None and is always fine.
        # A three-segment ref (host/owner/repo#n) must decompose via _parse_ghes_ref;
        # if it does not (invalid characters, path-like extension), refuse it.
        ref_host = _ref_host(ev.ref)
        if ref_host is not None and _parse_ghes_ref(ev.ref) is None:
            raise MaskingError(
                f"--mask-private: evidence ref {ev.ref!r} has host prefix {ref_host!r} "
                f"but cannot be decomposed into a valid host/owner/repo. "
                f"Re-run without --mask-private."
            )


def _gh_visibility_lookup(repo: str) -> bool:
    """Look up whether a repo is private using 'gh repo view'.

    ``repo`` is either a bare 'owner/repo' string (for github.com) or a
    'host/owner/repo' string (for GitHub Enterprise Server / any other host).
    The gh CLI accepts both forms natively — host-prefixed for GHES repos.

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
    """Build a deterministic relabel map: sorted(private) -> private-repo-1, ...

    Keys may be bare 'owner/repo' (github.com) or 'host/owner/repo' (GHES).
    Both are lowercase strings; sorted() gives lexicographic order across hosts.

    For GHES keys ('host/owner/repo'), a bare 'owner/repo' alias is also added
    so that free text containing only the bare owner/repo substring is also
    scrubbed (in addition to the full host/owner/repo pattern).  The bare alias
    is only added when the bare key is not already covered by a github.com key of
    the same name (github.com key takes precedence in that case).
    """
    relabel = {repo: f"private-repo-{i + 1}" for i, repo in enumerate(sorted(private))}
    extra: dict[str, str] = {}
    for key, label in relabel.items():
        parts = key.split("/")
        if len(parts) == 3:  # host/owner/repo (GHES)
            bare = f"{parts[1]}/{parts[2]}"
            if bare not in relabel:
                extra[bare] = label
    relabel.update(extra)
    return relabel


def _rewrite_ref(ref: str, relabel: dict[str, str]) -> str:
    """Rewrite an evidence ref or claim evidence_ref using the relabel map.

    Handles both github.com refs (owner/repo#n, owner/repo:path) and GHES refs
    (host/owner/repo#n, host/owner/repo:path).  Lookup is case-insensitive
    because all keys in relabel are lowercase.
    """
    if "#" in ref:
        prefix = ref.split("#")[0]
        key = prefix.lower()
        if key in relabel:
            return relabel[key] + "#" + ref[len(prefix) + 1 :]
    elif ":" in ref:
        prefix = ref.split(":", 1)[0]
        key = prefix.lower()
        if key in relabel:
            return relabel[key] + ":" + ref[len(prefix) + 1 :]
    return ref


def _rewrite_text(text: str, relabel: dict[str, str]) -> str:
    """Replace all private owner/repo substrings in free text (case-insensitive).

    Longest names first to avoid partial-name collision (e.g. org/repo-tools
    must not be mis-replaced when org/repo is a shorter private name).
    Uses case-insensitive matching so mixed-case occurrences are also replaced.
    """
    for repo in sorted(relabel, key=len, reverse=True):
        text = re.sub(re.escape(repo), relabel[repo], text, flags=re.IGNORECASE)
    return text


def mask_portfolio(portfolio: Portfolio, private: set[str]) -> Portfolio:
    """Return a new Portfolio with private repos relabeled.

    Input portfolio is NOT mutated. Labels are assigned in sorted() order.
    Handles both github.com repos (bare 'owner/repo' keys) and GHES repos
    ('host/owner/repo' keys) transparently.
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
        # URL: replace owner/repo or host/owner/repo substring — longest names
        # first (collision-safe), case-insensitive (hosts and repo names are
        # case-insensitive on GitHub and GitHub Enterprise Server).
        new_url = ev.url
        if new_url:
            for repo in sorted(relabel, key=len, reverse=True):
                new_url = re.sub(re.escape(repo), relabel[repo], new_url, flags=re.IGNORECASE)
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
