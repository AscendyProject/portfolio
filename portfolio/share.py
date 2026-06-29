"""Provider-agnostic share seam for publishing Markdown artifacts to a URL.

Exports:
  ShareResult   — dataclass carrying the published .url
  Sharer        — abstract base (protocol) for publish(markdown, *, title, public)
  GistSharer    — GistSharer.publish() shells `gh gist create` (injectable runner)
  share_links() — returns pre-filled LinkedIn and X intent URLs (URL-encoded)
"""

from __future__ import annotations

import subprocess
import urllib.parse
from dataclasses import dataclass


@dataclass
class ShareResult:
    url: str


class Sharer:
    """Abstract seam. Subclasses override publish()."""

    def publish(self, markdown: str, *, title: str, public: bool) -> ShareResult:
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
    """Publishes Markdown to a GitHub Gist via `gh gist create`.

    The `gh` runner is injectable — tests pass a fake so no live gh is called.

    Constructor args:
      gh_runner: callable(argv: list[str], stdin_bytes: bytes | None) -> str
        Defaults to _default_gh_runner (real subprocess).
    """

    def __init__(self, gh_runner=None):
        self._gh_runner = gh_runner if gh_runner is not None else _default_gh_runner

    def publish(self, markdown: str, *, title: str, public: bool) -> ShareResult:
        """Create a GitHub Gist from markdown via stdin.

        Markdown is passed via stdin (no temp file, no shell=True,
        no f-string interpolation of the markdown into the command).
        """
        argv = ["gh", "gist", "create", "--filename", f"{title}.md", "-"]
        if public:
            argv.append("--public")
        stdin_bytes = markdown.encode("utf-8")
        stdout = self._gh_runner(argv, stdin_bytes)
        url = _parse_gist_url(stdout)
        return ShareResult(url=url)


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
