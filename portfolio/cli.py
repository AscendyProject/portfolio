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
from portfolio.output import emit_markdown
from portfolio.pipeline import resolve_to_build_result
from portfolio.render import render_markdown
from portfolio.sources import SourceRequest, UnsupportedSourceError, known_source_types, resolve_source
from portfolio.web import fetch_html


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m portfolio",
        description="Render a grounded portfolio from a developer's real work.",
    )
    parser.add_argument("--source-type", required=True, choices=list(known_source_types()))
    parser.add_argument("--source", help="source URL (a github repo URL, or an article URL for --source-type web)")
    parser.add_argument("--author", help="GitHub handle whose merged PRs are the evidence")
    parser.add_argument("--max-claims", type=int, default=12, help="max claims to draft (default: 12)")
    parser.add_argument("--out", help="write Markdown to this file instead of stdout")
    parser.add_argument("--emit-portfolio", dest="emit_portfolio", help="write Portfolio JSON to this file")
    return parser


def run(
    argv: list[str],
    *,
    extractor=extract_merged_prs,
    runner=run_claude,
    fetcher=fetch_html,
    synthesis_runner=None,
) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web fetch), `runner` (model), and
    `synthesis_runner` (model for synthesis) are injectable seams: the defaults
    hit live services, but tests pass fakes so no live service is required.
    synthesis_runner defaults to None so existing tests that inject only runner=
    continue to work (synthesis is skipped when synthesis_runner is None).
    """
    args = _build_parser().parse_args(argv)

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

    # Extract + build inside a top-level error boundary: any failure — gh or
    # claude non-zero exit, malformed-but-valid gh JSON (wrong shape), etc. —
    # becomes a clean non-zero exit with a stderr message, not a traceback.
    try:
        result = resolve_to_build_result(
            resolved,
            subject=resolved.subject,
            runner=runner,
            max_claims=args.max_claims,
            synthesis_runner=synthesis_runner,
        )
    except Exception as exc:
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    markdown = render_markdown(result.portfolio, synthesis=result.synthesis)

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

    if args.emit_portfolio:
        from portfolio.store import portfolio_to_json

        try:
            Path(args.emit_portfolio).write_text(portfolio_to_json(result.portfolio), encoding="utf-8")
        except OSError as exc:
            print(f"failed to write --emit-portfolio file {args.emit_portfolio!r}: {exc}", file=sys.stderr)
            return 2

    return 0


def main() -> None:
    """Console entrypoint: run with live services and exit with the result code."""
    sys.exit(run(sys.argv[1:], synthesis_runner=run_claude))
