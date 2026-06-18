"""CLI entrypoint: wire the pipeline (extract -> narrate -> ground) plus
JD-aware resume selection into a Markdown resume.

`python -m resume --source-type github --source <gh-url> --author <handle> --jd <path>`
runs the full pipeline and prints the grounded resume as Markdown to stdout
(or to `--out <file>`), with a one-line grounding summary on stderr.

The model call (`runner`), `gh` extraction (`extractor`), and web fetch
(`fetcher`) are injectable so the CLI is unit-testable without live services.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from portfolio.extract import extract_merged_prs
from portfolio.narrative import run_claude
from portfolio.output import emit_markdown
from portfolio.pipeline import build_from_evidence
from portfolio.sources import SourceRequest, UnsupportedSourceError, known_source_types, resolve_source
from portfolio.web import fetch_html
from resume.render import render_resume
from resume.select import build_resume


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m resume",
        description="Render a grounded resume from a developer's real work and a job description.",
    )
    parser.add_argument("--source-type", required=True, choices=list(known_source_types()))
    parser.add_argument("--source", help="source URL (a github repo URL, or an article URL for --source-type web)")
    parser.add_argument("--author", help="GitHub handle whose merged PRs are the evidence")
    parser.add_argument("--jd", required=True, help="path to the job description file (plain text)")
    parser.add_argument("--top-n", type=int, default=12, help="max resume bullets to render (default: 12)")
    parser.add_argument("--out", help="write Markdown to this file instead of stdout")
    return parser


def run(
    argv: list[str],
    *,
    extractor=extract_merged_prs,
    runner=run_claude,
    fetcher=fetch_html,
) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web fetch), and `runner` (model) are injectable
    seams: the defaults hit live services, but tests pass fakes so no live
    service is required.
    """
    args = _build_parser().parse_args(argv)

    # Read the JD file up front — fail early with a clean error if missing.
    jd_path = Path(args.jd)
    try:
        jd_text = jd_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read --jd file {args.jd!r}: {exc}", file=sys.stderr)
        return 2

    # Resolve the source (validation/parse only — no extraction yet).
    try:
        resolved = resolve_source(
            args.source_type,
            SourceRequest(source=args.source, author=args.author, extractor=extractor, fetcher=fetcher),
        )
    except UnsupportedSourceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"invalid source: {exc}", file=sys.stderr)
        return 2

    # Extract + build inside a top-level error boundary.
    try:
        evidence = resolved.extract()
        result = build_from_evidence(subject=resolved.subject, evidence=evidence, runner=runner, max_claims=args.top_n)
    except Exception as exc:
        print(f"failed to build resume: {exc}", file=sys.stderr)
        return 1

    draft = build_resume(result.portfolio, jd_text, args.top_n)
    markdown = render_resume(draft)

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
        emit_markdown(markdown)
    return 0


def main() -> None:
    """Console entrypoint: run with live services and exit with the result code."""
    sys.exit(run(sys.argv[1:]))
