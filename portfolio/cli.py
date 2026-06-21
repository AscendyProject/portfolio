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

import portfolio.i18n as i18n
from portfolio.extract import extract_merged_prs
from portfolio.narrative import run_claude
from portfolio.output import emit_markdown
from portfolio.pipeline import resolve_and_optionally_mask
from portfolio.render import render_markdown
from portfolio.sources import SourceRequest, UnsupportedSourceError, known_source_types, resolve_source
from portfolio.web import fetch_html


def _run_merge(argv: list[str]) -> int:
    """Handle `python -m portfolio merge <a.json> <b.json> ... --subject <s> --out <f>`."""
    from portfolio.store import PortfolioStoreError, merge_portfolios, portfolio_from_json, portfolio_to_json

    parser = argparse.ArgumentParser(prog="python -m portfolio merge")
    parser.add_argument("inputs", nargs="*", metavar="INPUT", help="input Portfolio JSON paths (>=2 required)")
    parser.add_argument("--subject", default=None, help="canonical subject name for the merged portfolio")
    parser.add_argument("--out", default=None, help="write merged Portfolio JSON to this file")
    args = parser.parse_args(argv)

    if len(args.inputs) < 2:
        print(f"merge requires at least 2 input paths, got {len(args.inputs)}", file=sys.stderr)
        return 2

    if args.subject is None:
        print("--subject is required", file=sys.stderr)
        return 2
    if not args.subject.strip():
        print("--subject must not be empty or whitespace-only", file=sys.stderr)
        return 2

    if args.out is None:
        print("--out is required", file=sys.stderr)
        return 2

    portfolios = []
    for path_str in args.inputs:
        path = Path(path_str)
        if not path.exists():
            print(f"input file not found: {path_str!r}", file=sys.stderr)
            return 2
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"cannot read {path_str!r}: {exc}", file=sys.stderr)
            return 2
        try:
            p = portfolio_from_json(text)
        except PortfolioStoreError as exc:
            print(f"invalid portfolio JSON in {path_str!r}: {exc}", file=sys.stderr)
            return 2
        portfolios.append(p)

    try:
        merged = merge_portfolios(portfolios, subject=args.subject)
    except PortfolioStoreError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        Path(args.out).write_text(portfolio_to_json(merged), encoding="utf-8")
    except OSError as exc:
        print(f"failed to write --out file {args.out!r}: {exc}", file=sys.stderr)
        return 1

    return 0


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
    parser.add_argument(
        "--mask-private", action="store_true", default=False, help="anonymize private GitHub repo names in output"
    )
    parser.add_argument(
        "--show-refs", action="store_true", default=False, help="include grounding refs in rendered output"
    )
    parser.add_argument("--lang", choices=tuple(i18n.LANGS), default=None, help="output language code (default: en)")
    return parser


def run(
    argv: list[str],
    *,
    extractor=extract_merged_prs,
    runner=run_claude,
    fetcher=fetch_html,
    synthesis_runner=None,
    visibility_lookup=None,
) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web fetch), `runner` (model), and
    `synthesis_runner` (model for synthesis) are injectable seams: the defaults
    hit live services, but tests pass fakes so no live service is required.
    synthesis_runner defaults to None so existing tests that inject only runner=
    continue to work (synthesis is skipped when synthesis_runner is None).
    """
    # `merge` is a positional subcommand; detect it before the main parser runs
    # (the main parser has --source-type required, which would reject merge args).
    if argv and argv[0] == "merge":
        return _run_merge(argv[1:])

    args = _build_parser().parse_args(argv)
    lang = args.lang or "en"

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
        result, n_masked = resolve_and_optionally_mask(
            resolved,
            subject=resolved.subject,
            runner=runner,
            max_claims=args.max_claims,
            mask_private=args.mask_private,
            synthesis_runner=synthesis_runner,
            visibility_lookup=visibility_lookup,
            lang=lang,
        )
    except Exception as exc:
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    if args.mask_private:
        print(f"masked {n_masked} private repo(s)", file=sys.stderr)

    markdown = render_markdown(result.portfolio, synthesis=result.synthesis, show_refs=args.show_refs, lang=lang)

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
