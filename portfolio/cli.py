"""CLI entrypoint: wire the pipeline (extract -> narrate -> ground) to the
Markdown renderer.

`python -m portfolio --source-type github --source <github-url> --author <handle>`
runs the full pipeline and prints the grounded portfolio as Markdown to stdout
(or to `--out <file>`), with a one-line grounding summary on stderr.

Source resolution is delegated to `portfolio.sources`: `--source-type github`
is implemented, `others` is a recognized-but-unsupported stub. The model call
(`runner`) and the `gh` extraction (`extractor`) are injectable so the CLI is
unit-testable without a live `gh`/`claude`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from portfolio.extract import extract_merged_prs
from portfolio.narrative import run_claude
from portfolio.pipeline import build_from_evidence
from portfolio.render import render_markdown
from portfolio.sources import SourceRequest, UnsupportedSourceError, known_source_types, resolve_source


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m portfolio",
        description="Render a grounded portfolio from a developer's real work.",
    )
    parser.add_argument("--source-type", required=True, choices=list(known_source_types()))
    parser.add_argument("--source", help="source URL, e.g. https://github.com/owner/repo")
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

    # Resolve the source (validation/parse only — no extraction yet).
    try:
        resolved = resolve_source(
            args.source_type,
            SourceRequest(source=args.source, author=args.author, extractor=extractor),
        )
    except UnsupportedSourceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"invalid source: {exc}", file=sys.stderr)
        return 2

    # Extract + build inside a top-level error boundary: any failure — gh or
    # claude non-zero exit, malformed-but-valid gh JSON (wrong shape), etc. —
    # becomes a clean non-zero exit with a stderr message, not a traceback.
    try:
        evidence = resolved.extract()
        result = build_from_evidence(
            subject=resolved.subject, evidence=evidence, runner=runner, max_claims=args.max_claims
        )
    except Exception as exc:
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
