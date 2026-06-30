"""Deterministic evidence extraction via the Bitbucket Cloud REST API 2.0.

Extracts a developer's merged Pull Requests from Bitbucket Cloud and turns them
into Evidence records. The HTTP fetcher is injectable so tests can substitute
fake JSON without a live network or credentials.

Ref format
----------
``bitbucket.org/<workspace>/<repo>#<id>``

Always host-qualified (unlike github.com bare ``owner/repo`` refs) so the
masking layer's ``_parse_ghes_ref`` / ``_ref_host`` discovery path picks it up
without modification. The ref round-trips through ``_parse_ghes_ref`` in
``portfolio/mask.py``: the three-segment ``host/owner/repo`` form is matched by
``_GHES_PR_REF_RE``.

Example: ``bitbucket.org/acme/myrepo#7``.

Auth env vars
-------------
Bearer auth (API token — recommended):
  BITBUCKET_TOKEN — Atlassian API token

Basic auth (app password — legacy):
  BITBUCKET_USERNAME  — Atlassian account username
  BITBUCKET_APP_PASSWORD — Bitbucket app password with PR-read scope

When ``BITBUCKET_TOKEN`` is set it takes precedence over Basic credentials.
When neither is set, ``extract_merged_prs_bitbucket`` raises a clean
``RuntimeError`` naming the env vars to set.

API field-name caveat
---------------------
Field names (``values``, ``next``, ``links.html.href``, ``links.diffstat.href``,
``lines_added``, ``lines_removed``, ``old.path``, ``new.path``) were inferred
from the Bitbucket Cloud REST API 2.0 documentation. Verify them against a real
Bitbucket Cloud account before relying on live output.

Limitations (v1)
----------------
- Bitbucket Cloud only (not Bitbucket Server / Data Center).
- Diffstat pagination limited to a sane per-PR bound; very large PRs may
  silently truncate the changed-file list.
- Binary files have no line stats and contribute 0 additions/deletions.
- Sequential paging only (no concurrent fetches).
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

from .extract import _counts_toward_change_size
from .model import Evidence

_API_HOST = "api.bitbucket.org"
_BB_HOST = "bitbucket.org"
_TIMEOUT = 30  # seconds
_DIFFSTAT_PAGE_LIMIT = 20  # max diffstat pages per PR

# Bitbucket usernames are letters/digits/`.`/`_`/`-`. Anything else (quotes, spaces,
# operators) could inject into the Bitbucket query language, so it is rejected before
# the `q` string is built.
_BITBUCKET_AUTHOR_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_bitbucket_author(author: str) -> None:
    """Raise ValueError if ``author`` is not a safe Bitbucket username.

    Prevents Bitbucket query-language injection via ``author.username="<author>"``:
    URL-encoding only protects HTTP transport, but Bitbucket decodes and then
    evaluates the ``q`` expression, so the value must contain no quotes/operators.
    """
    if not isinstance(author, str) or not _BITBUCKET_AUTHOR_RE.match(author):
        raise ValueError(
            f"invalid Bitbucket author {author!r}: only letters, digits, '.', '_', and '-' "
            "are allowed (a quote or operator could inject into the Bitbucket query)."
        )


def _safe_int(val: object) -> int:
    """Convert *val* to int, returning 0 on ``None`` or any non-numeric type.

    The Bitbucket diffstat API may return ``null`` for binary files or an
    unexpected scalar type on schema drift.  ``int(val) or 0`` raises on a
    non-numeric string like ``"n/a"``; this helper treats all such values as 0
    so ``parse_bitbucket_diffstat`` degrades gracefully instead of raising.
    """
    if val is None:
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _get_auth() -> tuple[str, str] | str | None:
    """Read Bitbucket credentials from environment variables.

    Priority: ``BITBUCKET_TOKEN`` (Bearer) > ``BITBUCKET_USERNAME`` +
    ``BITBUCKET_APP_PASSWORD`` (Basic).

    Returns a bearer token string, a ``(username, app_password)`` tuple, or
    ``None`` if no credentials are configured.
    """
    token = os.environ.get("BITBUCKET_TOKEN")
    if token:
        return token
    username = os.environ.get("BITBUCKET_USERNAME")
    app_password = os.environ.get("BITBUCKET_APP_PASSWORD")
    if username and app_password:
        return (username, app_password)
    return None


def _build_auth_header(auth: tuple[str, str] | str) -> str:
    """Build an ``Authorization`` header value from credentials."""
    if isinstance(auth, str):
        return f"Bearer {auth}"
    creds = f"{auth[0]}:{auth[1]}"
    encoded = base64.b64encode(creds.encode()).decode()
    return f"Basic {encoded}"


def fetch_json(url: str, *, auth: tuple[str, str] | str) -> dict:
    """Fetch a URL via GET and return the parsed JSON response.

    Uses stdlib ``urllib.request`` only — no new pip dependency.

    Parameters
    ----------
    url:
        The URL to fetch.
    auth:
        Credentials: a bearer token ``str`` (``BITBUCKET_TOKEN``), or a
        ``(username, app_password)`` tuple (``BITBUCKET_USERNAME`` +
        ``BITBUCKET_APP_PASSWORD``).

    Raises
    ------
    RuntimeError
        On any HTTP error, transport failure, or unparseable JSON response.
        The error message names the problem but never includes credential bytes.
    """
    auth_header = _build_auth_header(auth)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Bitbucket API HTTP {exc.code} for {url!r}") from None
    except (urllib.error.URLError, OSError, socket.timeout, ssl.SSLError):
        raise RuntimeError(f"Bitbucket API request failed for {url!r}: transport error") from None
    except Exception:
        raise RuntimeError(f"Bitbucket API request failed for {url!r}") from None

    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"Bitbucket API returned invalid JSON from {url!r}") from None


def _safe_api_host(url: str) -> bool:
    """Return True iff ``url`` is an ``https://api.bitbucket.org`` URL (SSRF + creds guard).

    Both the scheme AND host are checked: an API-supplied pagination URL using
    ``http://api.bitbucket.org`` would otherwise send the Authorization header over
    plaintext, leaking credentials (codex IR-001).
    """
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname == _API_HOST
    except Exception:
        return False


def parse_bitbucket_pr_list(
    json_dict: dict,
    host: str,
    workspace: str,
    repo: str,
) -> list[Evidence]:
    """Parse a Bitbucket PR list page into Evidence records.

    ``json_dict`` is the parsed JSON from a PR list API response::

        {
            "values": [
                {
                    "id": 7,
                    "title": "Fix login bug",
                    "links": {"html": {"href": "https://bitbucket.org/..."}},
                }
            ],
            "next": "https://api.bitbucket.org/..."  (optional)
        }

    Returns one ``kind="pr"`` Evidence per entry.  The ``detail`` field is set
    to the PR title only (no ``(+A/-D)`` yet — enriched by the caller after
    fetching the diffstat).  ``additions`` and ``deletions`` are 0 placeholders.

    Pure function — no ``urllib`` calls inside; unit-testable with canned JSON.
    """
    evidence: list[Evidence] = []
    values = json_dict.get("values") or []
    for pr in values:
        if not isinstance(pr, dict):
            continue
        pr_id = pr.get("id")
        if pr_id is None:
            continue
        title = pr.get("title", "")
        links = pr.get("links") or {}
        html_link = (links.get("html") or {}) if isinstance(links, dict) else {}
        url = html_link.get("href", "") if isinstance(html_link, dict) else ""
        ref = f"{host}/{workspace}/{repo}#{pr_id}"
        evidence.append(
            Evidence(
                kind="pr",
                ref=ref,
                url=url,
                detail=title,
                additions=0,
                deletions=0,
            )
        )
    return evidence


def parse_bitbucket_diffstat(
    json_dict: dict,
    pr_ref: str,
) -> tuple[int, int, list[Evidence]]:
    """Parse a Bitbucket PR diffstat response into code-only line counts and file evidence.

    ``json_dict`` is the parsed JSON from a diffstat API response::

        {
            "values": [
                {
                    "status": "modified",
                    "lines_added": 10,
                    "lines_removed": 3,
                    "new": {"path": "src/main.py"},
                    "old": {"path": "src/main.py"},
                }
            ],
            "next": "..."  (optional)
        }

    Returns ``(additions, deletions, file_evidence)`` where:

    - ``additions``/``deletions`` are code-only sums (reuses
      ``_counts_toward_change_size`` from ``extract.py`` — not reimplemented).
    - ``file_evidence`` is one ``kind="file"`` Evidence per changed code file.
      ``ref`` is ``new.path`` for additions/modifications, ``old.path`` for
      deletions; ``detail`` is ``"changed in <pr_ref>"``.

    Pure function — no ``urllib`` calls inside; unit-testable with canned JSON.
    Degrades gracefully to ``(0, 0, [])`` on any unexpected schema.
    """
    total_add = 0
    total_del = 0
    file_evidence: list[Evidence] = []

    values = json_dict.get("values") or []
    for entry in values:
        if not isinstance(entry, dict):
            continue

        status = entry.get("status", "")
        new_obj = entry.get("new")
        old_obj = entry.get("old")
        new_path = new_obj.get("path", "") if isinstance(new_obj, dict) else ""
        old_path = old_obj.get("path", "") if isinstance(old_obj, dict) else ""

        # Use old_path for removals (new is absent/null for deleted files)
        file_path = old_path if (status == "removed" or not new_path) else new_path

        if not file_path or not _counts_toward_change_size(file_path):
            continue

        lines_added = _safe_int(entry.get("lines_added"))
        lines_removed = _safe_int(entry.get("lines_removed"))
        total_add += lines_added
        total_del += lines_removed

        file_evidence.append(
            Evidence(
                kind="file",
                ref=file_path,
                detail=f"changed in {pr_ref}",
            )
        )

    return total_add, total_del, file_evidence


def extract_merged_prs_bitbucket(
    workspace: str,
    repo: str,
    author: str,
    limit: int = 100,
    *,
    fetcher=fetch_json,
) -> list[Evidence]:
    """Extract merged PRs authored by ``author`` from ``workspace/repo`` on Bitbucket Cloud.

    Pages through the Bitbucket Cloud REST API 2.0 PR list endpoint, following
    ``next`` URLs until the list is exhausted or ``limit`` PRs have been
    collected.

    Reads credentials from environment variables (``BITBUCKET_TOKEN`` or
    ``BITBUCKET_USERNAME`` + ``BITBUCKET_APP_PASSWORD``).  Raises a clean
    ``RuntimeError`` naming the env vars if none are configured.

    For each merged PR emits:

    - One ``kind="pr"`` Evidence with code-only additions/deletions and
      ``ref = "bitbucket.org/<workspace>/<repo>#<id>"``.
    - One ``kind="file"`` Evidence per changed code file (bare path, no prefix).

    Best-effort diffstat: if a single PR's diffstat fetch fails for any reason,
    that PR's Evidence keeps ``additions=0 / deletions=0`` with no file
    evidence; sibling PRs are unaffected; no credential or response bytes appear
    in any returned field.

    Pagination SSRF guard: ``next`` URLs whose host is not ``api.bitbucket.org``
    are silently refused (not fetched).

    ``fetcher`` is injectable for testing; it receives ``(url, *, auth=auth)``
    and must return a parsed JSON dict.
    """
    auth = _get_auth()
    if auth is None:
        raise RuntimeError(
            "Bitbucket credentials not found. Set one of:\n"
            "  BITBUCKET_TOKEN=<api-token>   (recommended)\n"
            "  BITBUCKET_USERNAME=<user> + BITBUCKET_APP_PASSWORD=<app-password>"
        )

    # Validate the author against a narrow allowlist BEFORE it is placed in the
    # Bitbucket query language. URL-encoding alone is not enough: Bitbucket decodes
    # the `q` parameter and then evaluates it, so a quote/operator in `author` (e.g.
    # `alice" OR state="OPEN`) would be query-language injection. Reject anything
    # outside Bitbucket's username charset (codex IR-001 / injection).
    validate_bitbucket_author(author)

    host = _BB_HOST
    # URL-encode the query value so the request target is valid; combined with the
    # allowlist above, the interpolated author is both transport- and BBQL-safe.
    query = urlencode({"q": f'state="MERGED" AND author.username="{author}"'})
    base_url = f"https://{_API_HOST}/2.0/repositories/{workspace}/{repo}/pullrequests?{query}"

    collected: list[Evidence] = []
    pr_count = 0
    next_url: str | None = base_url

    while next_url is not None and pr_count < limit:
        if not _safe_api_host(next_url):
            break  # SSRF guard: refuse non-api.bitbucket.org page URLs

        # The primary PR-list request is NOT best-effort: an auth/transport failure
        # (e.g. a 401) must surface as a clean RuntimeError from fetch_json, not be
        # swallowed into an empty portfolio (IR-004). Only per-PR diffstat below is
        # best-effort.
        page = fetcher(next_url, auth=auth)

        pr_list_ev = parse_bitbucket_pr_list(page, host, workspace, repo)

        for pr_ev in pr_list_ev:
            if pr_count >= limit:
                break

            pr_id = pr_ev.ref.rsplit("#", 1)[-1]
            diffstat_url = f"https://{_API_HOST}/2.0/repositories/{workspace}/{repo}/pullrequests/{pr_id}/diffstat"

            # Best-effort per-PR diffstat enrichment
            add, delete, file_ev = 0, 0, []
            next_diffstat: str | None = diffstat_url
            pages_fetched = 0

            while next_diffstat is not None and pages_fetched < _DIFFSTAT_PAGE_LIMIT:
                if not _safe_api_host(next_diffstat):
                    # Non-api.bitbucket.org diffstat URL — treat as failure
                    add, delete, file_ev = 0, 0, []
                    break
                try:
                    ds_page = fetcher(next_diffstat, auth=auth)
                    p_add, p_del, p_files = parse_bitbucket_diffstat(ds_page, pr_ev.ref)
                    add += p_add
                    delete += p_del
                    file_ev.extend(p_files)
                    pages_fetched += 1
                    next_diffstat_raw = ds_page.get("next")
                    if next_diffstat_raw and not _safe_api_host(next_diffstat_raw):
                        break  # SSRF guard on diffstat next URL
                    next_diffstat = next_diffstat_raw
                except Exception:
                    add, delete, file_ev = 0, 0, []
                    break

            enriched = Evidence(
                kind="pr",
                ref=pr_ev.ref,
                url=pr_ev.url,
                detail=f"{pr_ev.detail} (+{add}/-{delete})",
                additions=add,
                deletions=delete,
            )
            collected.append(enriched)
            collected.extend(file_ev)
            pr_count += 1

        next_url = page.get("next")
        if next_url and not _safe_api_host(next_url):
            break

    return collected
