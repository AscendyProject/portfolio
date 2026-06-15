"""CLI entrypoint: wire the pipeline (extract -> narrate -> ground) to the
Markdown renderer for a GitHub source.

`python -m portfolio --source-type github --source <github-url> --author <handle>`
runs the full pipeline and prints the grounded portfolio as Markdown to stdout
(or to `--out <file>`), with a one-line grounding summary on stderr.

A `--source-type` switch reserves two branches: `github` (implemented) and
`others` (recognized but not supported yet — the seam for later blog/web
crawling and the `/portfolio` slash command). The model call (`runner`) and the
`gh` extraction (`extractor`) are injectable so the CLI is unit-testable without
a live `gh` or `claude`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from portfolio.extract import extract_merged_prs
from portfolio.narrative import run_claude
from portfolio.pipeline import build_from_evidence
from portfolio.render import render_markdown

_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
# owner/repo segments must be clean GitHub names. This rejects %-encoding (e.g.
# %2F), whitespace, and any other character that would otherwise reach
# `gh --repo` as garbage instead of being refused up front.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def parse_github_source(url: str) -> str:
    """Parse a GitHub repo URL into the `owner/repo` string the extractor needs.

    Accepts `http(s)://github.com/<owner>/<repo>` with an optional trailing slash
    or `.git` suffix. Anything that is not a clean GitHub `owner/repo` (wrong
    host, missing repo, extra/empty path segments, query/fragment, ssh form, no
    scheme, or names with characters outside `[A-Za-z0-9._-]`) raises
    ValueError — reject rather than guess, so no garbage reaches `gh`.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"expected an http(s) URL, got {url!r}")
    if parsed.netloc.lower() not in _GITHUB_HOSTS:
        raise ValueError(f"not a github.com URL: {url!r}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"unexpected query/fragment in {url!r}")
    # Expect the path to be exactly /<owner>/<repo> (one optional trailing slash).
    # Split WITHOUT dropping empties so `/owner//repo` is rejected, not collapsed.
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    segments = path.split("/")
    if len(segments) != 3 or segments[0] != "":
        raise ValueError(f"expected exactly github.com/<owner>/<repo>, got {url!r}")
    owner, repo = segments[1], segments[2]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        raise ValueError(f"invalid owner/repo name in {url!r}")
    if owner in (".", "..") or repo in (".", ".."):  # dot segments are never real names
        raise ValueError(f"invalid owner/repo name in {url!r}")
    return f"{owner}/{repo}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m portfolio",
        description="Render a grounded portfolio from a developer's real work.",
    )
    parser.add_argument("--source-type", required=True, choices=["github", "others"])
    parser.add_argument("--source", help="GitHub repo URL, e.g. https://github.com/owner/repo")
    parser.add_argument("--author", help="GitHub handle whose merged PRs are the evidence")
    parser.add_argument("--max-claims", type=int, default=12, help="max claims to draft (default: 12)")
    parser.add_argument("--out", help="write Markdown to this file instead of stdout")
    return parser


def run(argv: list[str], *, extractor=extract_merged_prs, runner=run_claude) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` and `runner` are injectable seams: the defaults hit live `gh` /
    `claude`, but tests pass fakes so no live service is required.
    """
    args = _build_parser().parse_args(argv)

    if args.source_type == "others":
        print("source type 'others' is not supported yet", file=sys.stderr)
        return 2

    # github
    if not args.source or not args.author:
        print("--source and --author are required for --source-type github", file=sys.stderr)
        return 2
    try:
        repo = parse_github_source(args.source)
    except ValueError as exc:
        print(f"invalid GitHub source URL: {exc}", file=sys.stderr)
        return 2

    try:
        evidence = extractor(repo=repo, author=args.author)
        result = build_from_evidence(subject=args.author, evidence=evidence, runner=runner, max_claims=args.max_claims)
    except Exception as exc:
        # Top-level CLI error boundary: any extraction/pipeline failure — gh or
        # claude non-zero exit, malformed-but-valid gh JSON (wrong shape), etc. —
        # becomes a clean non-zero exit with a stderr message, not a traceback.
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    markdown = render_markdown(result.portfolio)

    grounding = result.grounding
    print(
        f"grounded: {len(grounding.grounded)}  "
        f"rejected: {len(grounding.rejected)}  "
        f"needs-confirmation: {len(grounding.needs_confirmation)}",
        file=sys.stderr,
    )

    if args.out:
        try:
            Path(args.out).write_text(markdown, encoding="utf-8")
        except OSError as exc:
            print(f"failed to write --out file {args.out!r}: {exc}", file=sys.stderr)
            return 1
    else:
        print(markdown)
    return 0


def main() -> None:
    """Console entrypoint: run with live services and exit with the result code."""
    sys.exit(run(sys.argv[1:]))
