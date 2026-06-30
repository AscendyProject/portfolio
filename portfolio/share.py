"""Provider-agnostic share seam for publishing Markdown artifacts to a URL.

Exports:
  ShareResult   — dataclass carrying the published .url
  Sharer        — abstract base (protocol) for publish(markdown, *, title, public)
  GistSharer    — GistSharer.publish() shells `gh gist create` (injectable runner)
  share_links() — returns pre-filled LinkedIn and X intent URLs (URL-encoded)
"""

from __future__ import annotations

import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ShareResult:
    url: str


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
    """Publishes Markdown to a GitHub Gist via `gh gist create`.

    The `gh` runner is injectable — tests pass a fake so no live gh is called.

    Constructor args:
      gh_runner: callable(argv: list[str], stdin_bytes: bytes | None) -> str
        Defaults to _default_gh_runner (real subprocess).
    """

    def __init__(self, gh_runner=None):
        self._gh_runner = gh_runner if gh_runner is not None else _default_gh_runner

    def publish(
        self,
        markdown: str,
        *,
        title: str,
        public: bool,
        extra_files: dict[str, str] | None = None,
    ) -> ShareResult:
        """Create a GitHub Gist.

        When extra_files is None (default), markdown is passed via stdin
        (byte-identical to the pre-extra_files behavior — no temp file,
        no shell=True, no f-string interpolation into the command).

        When extra_files is a dict, all files (primary markdown + every
        extra_files entry) are written into a tempfile.TemporaryDirectory()
        (auto-cleaned) and passed as argv file paths (no shell=True, no stdin).
        """
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
