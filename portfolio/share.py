"""Provider-agnostic share seam for publishing Markdown artifacts to a URL.

Exports:
  ShareResult    — dataclass carrying the published .url
  ShareBundle    — dataclass carrying the full publish output (url, links, badge, md)
  ShareError     — exception raised when Sharer.publish fails inside publish_share
  Sharer         — abstract base (protocol) for publish(markdown, *, title, public)
  GistSharer     — GistSharer.publish() shells `gh gist create` (injectable runner)
  share_links()  — returns pre-filled LinkedIn and X intent URLs (URL-encoded)
  gist_raw_url() — maps a gist URL + filename to the raw CDN URL
  publish_share()— end-to-end helper: footer + mask + publish + return ShareBundle
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import i18n as _i18n
from .mask import _rewrite_text


@dataclass
class ShareResult:
    url: str


class ShareError(Exception):
    """Raised by publish_share when the underlying Sharer.publish fails.

    The exception message never contains gh stderr, token text, or raw argv —
    the caller is responsible for emitting exactly one clean stderr line.
    """


@dataclass
class ShareBundle:
    """The complete output of a successful publish_share call.

    Attributes:
      shared_md  — the footer-bearing (and optionally masked) Markdown published.
      url        — the gist URL returned by the Sharer.
      linkedin   — pre-filled LinkedIn share intent URL.
      x          — pre-filled X (Twitter) share intent URL.
      badge      — README badge snippet (``![…](raw_url)``), or None when no card.
    """

    shared_md: str
    url: str
    linkedin: str
    x: str
    badge: str | None


class Sharer:
    """Abstract seam. Subclasses override publish()."""

    def publish(
        self,
        markdown: str,
        *,
        title: str,
        public: bool,
        extra_files: dict[str, str] | None = None,
    ) -> ShareResult:
        raise NotImplementedError


def _default_gh_runner(argv: list[str], stdin_bytes: bytes | None = None) -> str:
    """Real gh runner: shells `gh` as an argv list (no shell=True).

    Returns the combined stdout string. Raises RuntimeError on non-zero exit.
    """
    kwargs: dict = dict(
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if stdin_bytes is not None:
        kwargs["input"] = stdin_bytes.decode("utf-8", errors="replace")
    proc = subprocess.run(argv, **kwargs)
    if proc.returncode != 0:
        raise RuntimeError(f"gh exited {proc.returncode}")
    return proc.stdout


def _parse_gist_url(stdout: str) -> str:
    """Return the last URL-looking non-empty line from gh gist create stdout."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("https://"):
            return line
    raise RuntimeError("could not find gist URL in gh output")


class GistSharer(Sharer):
    """Publishes Markdown to a GitHub Gist via `gh gist create` (new) or the Gists
    PATCH API `gh api --method PATCH /gists/<id>` (update in place).

    The `gh` runner is injectable — tests pass a fake so no live gh is called.

    Constructor args:
      gh_runner: callable(argv: list[str], stdin_bytes: bytes | None) -> str
        Defaults to _default_gh_runner (real subprocess).

    publish() is find-or-update: it first lists the authenticated user's gists
    (via `gh api /gists?per_page=100`) to look for an existing gist whose files
    include `{title}.md`. If found, the existing gist is updated in place via
    the Gists PATCH API `gh api --method PATCH /gists/<id>` (same id → same URL →
    stable raw-SVG badge URL). If no
    match is found, a new gist is created as before. If the list call itself
    fails, publish falls back to create (best-effort lookup only — lookup failures
    do not abort the share). Create and edit failures are NOT swallowed; they
    propagate so publish_share can wrap them in ShareError.

    Visibility note: `--share-public` controls create. On update, visibility is
    NOT changed — gh cannot flip secret↔public on edit. Visibility is fixed at
    first creation.
    """

    def __init__(self, gh_runner=None):
        self._gh_runner = gh_runner if gh_runner is not None else _default_gh_runner

    def _find_existing_gist(self, title: str) -> tuple[str, str] | tuple[None, None]:
        """List the authenticated user's own gists and return (id, html_url) for a
        gist whose files include ``{title}.md``, or (None, None) if not found.

        Uses ``gh api /gists?per_page=100`` (no --user / -u flag — own gists only).
        Returns (None, None) on any error so callers can fall back to create.
        """
        list_argv = ["gh", "api", "/gists?per_page=100"]
        try:
            list_stdout = self._gh_runner(list_argv, None)
        except Exception:
            return None, None  # list call failed; caller falls back to create

        try:
            gists = json.loads(list_stdout)
        except (ValueError, TypeError):
            return None, None  # non-JSON response; treat as no match

        if not isinstance(gists, list):
            return None, None

        target_filename = f"{title}.md"
        for gist in gists:
            try:
                if target_filename in gist.get("files", {}):
                    return gist["id"], gist["html_url"]
            except (TypeError, KeyError):
                continue
        return None, None

    def publish(
        self,
        markdown: str,
        *,
        title: str,
        public: bool,
        extra_files: dict[str, str] | None = None,
    ) -> ShareResult:
        """Find-or-update a GitHub Gist for ``{title}.md``.

        First looks for an existing gist owned by the authenticated user whose
        files include ``{title}.md`` (via ``gh api /gists?per_page=100``). When
        found, updates it in place via the Gists PATCH API (`gh api --method PATCH
        /gists/<id>`) — same id, same URL. When no
        match is found, creates a new gist via ``gh gist create``.

        If the look-up call itself fails, falls back to create (best-effort).
        Create and edit failures propagate so publish_share wraps them as
        ShareError (task-029 contract unchanged).

        When extra_files is None (default), markdown is passed via stdin (no temp
        file, no shell=True, no f-string interpolation into the command).

        When extra_files is a dict, all files (primary markdown + every extra_files
        entry) are written into a tempfile.TemporaryDirectory() (auto-cleaned) and
        passed as argv file paths (no shell=True, no stdin).
        """
        # Step 1: find an existing gist to update (best-effort).
        gist_id, gist_url = self._find_existing_gist(title)

        if gist_id is not None:
            # EDIT path — update the existing gist in place (stable id / URL). Use the
            # Gists PATCH API so ALL files (the `.md` and, when present, the `.svg`
            # card) are replaced in ONE atomic call. `gh gist edit` replaces only a
            # single file per invocation (`--filename <name> <local>`) and `--add`
            # merely appends, so it cannot reliably update both files. The JSON body
            # is passed on stdin via `--input -` (argv list, no shell=True, no
            # interpolation of the file contents into the command).
            files_payload: dict[str, dict[str, str]] = {f"{title}.md": {"content": markdown}}
            if extra_files:
                for filename, content in extra_files.items():
                    files_payload[filename] = {"content": content}
            body = json.dumps({"files": files_payload}).encode("utf-8")
            argv = ["gh", "api", "--method", "PATCH", f"/gists/{gist_id}", "--input", "-"]
            self._gh_runner(argv, body)
            return ShareResult(url=gist_url)

        # CREATE path — no existing gist found (or look-up failed).
        if extra_files is None:
            argv = ["gh", "gist", "create", "--filename", f"{title}.md", "-"]
            if public:
                argv.append("--public")
            stdin_bytes = markdown.encode("utf-8")
            stdout = self._gh_runner(argv, stdin_bytes)
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmppath = Path(tmpdir)
                # Write primary markdown — sanitize title to a plain filename
                # component so path-separator characters cannot escape the tmpdir.
                safe_title = Path(title).name or "rating"
                md_path = tmppath / f"{safe_title}.md"
                md_path.write_text(markdown, encoding="utf-8")
                file_paths = [str(md_path)]
                # Write each supplemental file — sanitize each key to its basename
                # so absolute paths / traversal sequences (../…) cannot escape the
                # TemporaryDirectory before gh is invoked.
                for filename, content in extra_files.items():
                    safe_name = Path(filename).name
                    if not safe_name:
                        raise ValueError(f"invalid extra_files key: {filename!r}")
                    extra_path = tmppath / safe_name
                    extra_path.write_text(content, encoding="utf-8")
                    file_paths.append(str(extra_path))
                argv = ["gh", "gist", "create"] + file_paths
                if public:
                    argv.append("--public")
                stdout = self._gh_runner(argv, None)
        url = _parse_gist_url(stdout)
        return ShareResult(url=url)


def gist_raw_url(gist_url: str, filename: str) -> str:
    """Derive the raw file URL from a gist page URL and a filename.

    Maps ``https://gist.github.com/<user>/<id>`` (with or without a trailing
    slash) to ``https://gist.githubusercontent.com/<user>/<id>/raw/<filename>``.
    Pure string transform — deterministic, no network call.
    """
    base = gist_url.rstrip("/")
    raw_base = base.replace("https://gist.github.com/", "https://gist.githubusercontent.com/", 1)
    return f"{raw_base}/raw/{filename}"


def share_links(url: str, summary: str) -> dict[str, str]:
    """Return pre-filled LinkedIn and X (Twitter) intent URLs.

    Both `url` and `summary` are percent-encoded via urllib.parse.quote so
    special characters (spaces, &, ?, non-ASCII, …) are safe in the query string.

    Returns:
      {"linkedin": "...", "x": "..."}
    """
    enc_url = urllib.parse.quote(url, safe="")
    enc_summary = urllib.parse.quote(summary, safe="")
    linkedin = f"https://www.linkedin.com/sharing/share-offsite/?url={enc_url}&summary={enc_summary}"
    x = f"https://twitter.com/intent/tweet?url={enc_url}&text={enc_summary}"
    return {"linkedin": linkedin, "x": x}


def publish_share(
    report_md: str,
    *,
    subject: str,
    lang: str,
    public: bool,
    effective_mask: bool,
    relabel: dict[str, str],
    sharer: "Sharer",
    card_svg: str | None = None,
    summary: str = "My grounded portfolio",
) -> ShareBundle:
    """Append provenance footer, optionally mask, publish, and return a ShareBundle.

    Args:
      report_md      — the rendered Markdown report (WITHOUT the footer yet).
      subject        — string used to derive the gist filename (e.g. "rating-alice").
      lang           — i18n language code; selects the provenance footer string.
      public         — whether the Gist should be public (True) or secret (False).
      effective_mask — when True AND relabel is non-empty, body / title / svg are
                       scrubbed via ``portfolio.mask._rewrite_text`` (case-insensitive,
                       longest-first collision-safe).
      relabel        — the mask relabel map from ``resolve_and_optionally_mask``.
      sharer         — injectable Sharer instance (GistSharer() when omitted by CLIs).
      card_svg       — when supplied, included as ``{title}.svg`` in extra_files and
                       the returned bundle carries a README badge snippet.

    Returns:
      ShareBundle with shared_md, url, linkedin, x, badge (None if no card).

    Raises:
      ShareError when sharer.publish raises; does NOT write to stdout or stderr.
    """

    def _scrub(s: str) -> str:
        return _rewrite_text(s, relabel) if (effective_mask and relabel) else s

    # 1. Append provenance footer.
    footer = _i18n.LANGS[lang]["share_provenance_footer"]
    shared_md = report_md + "\n\n" + footer + "\n"

    # 2. Scrub body so no raw private repo name can reach the gist.
    shared_md = _scrub(shared_md)

    # 3. Derive a filename-safe gist title from subject.
    title = re.sub(r"[^A-Za-z0-9._-]+", "-", _scrub(subject)).strip("-") or "portfolio"

    # 4. Prepare the SVG card (if supplied) and build extra_files.
    extra_files: dict[str, str] | None = None
    svg_filename: str | None = None
    if card_svg is not None:
        scrubbed_svg = _scrub(card_svg)
        svg_filename = f"{title}.svg"
        extra_files = {svg_filename: scrubbed_svg}

    # 5. Publish — on any exception raise ShareError (no print here).
    try:
        share_result = sharer.publish(shared_md, title=title, public=public, extra_files=extra_files)
    except Exception as exc:
        raise ShareError("could not publish to Gist") from exc

    # 6. Build social share links.
    links = share_links(share_result.url, f"{summary}: {share_result.url}")

    # 7. Build README badge snippet if a card was published.
    badge: str | None = None
    if svg_filename is not None:
        raw_url = gist_raw_url(share_result.url, svg_filename)
        badge = f"![Capability rating]({raw_url})"

    return ShareBundle(
        shared_md=shared_md,
        url=share_result.url,
        linkedin=links["linkedin"],
        x=links["x"],
        badge=badge,
    )
