"""CLI entrypoint: wire the pipeline (extract → narrate → ground) plus
deterministic JD scoring and bounded agent grading into a Markdown fit report.

`python -m fit --source-type github --source <gh-url> --author <handle> --jd <path>`
runs the full pipeline and prints the grounded fit assessment as Markdown to stdout
(or to `--out <file>`), with a one-line grounding summary on stderr.

The model call (`runner`), `gh` extraction (`extractor`), web fetch (`fetcher`),
and bounded grader (`grader_runner`) are injectable so the CLI is unit-testable
without live services.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fit.grade import GraderRunner, bounded_grade, default_grader_runner
from fit.render import render_fit
from fit.score import score_fit
from portfolio.extract import extract_merged_prs
from portfolio.jd_source import JDFetchError, JDFileReadError, JDInvalidURLError, load_jd
from portfolio.narrative import run_claude
from portfolio.pipeline import build_from_evidence
from portfolio.sources import SourceRequest, UnsupportedSourceError, known_source_types, resolve_source
from portfolio.web import fetch_html


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fit",
        description="Render a grounded JD fit assessment for a developer's real work.",
    )
    parser.add_argument("--source-type", required=True, choices=list(known_source_types()))
    parser.add_argument(
        "--source",
        help="source URL (a GitHub repo URL, or an article URL for --source-type web)",
    )
    parser.add_argument("--author", help="GitHub handle or subject name")
    parser.add_argument("--jd", required=True, help="path to the job description file (plain text)")
    parser.add_argument("--out", help="write Markdown to this file instead of stdout")
    return parser


def run(
    argv: list[str],
    *,
    extractor=extract_merged_prs,
    runner=run_claude,
    fetcher=fetch_html,
    grader_runner: GraderRunner = default_grader_runner,
) -> int:
    """Execute the /fit CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web fetch), `runner` (narrative model), and
    `grader_runner` (bounded grader model) are injectable seams: the defaults hit
    live services, but tests pass fakes so no live service is required.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    # Load the JD (file path or http(s) URL) — fail early with a clean error.
    try:
        jd_text = load_jd(args.jd, fetcher=fetcher)
    except JDFileReadError as exc:
        print(f"cannot read --jd file {args.jd!r}: {exc}", file=sys.stderr)
        return 2
    except JDInvalidURLError as exc:
        print(f"invalid --jd URL {args.jd!r}: {exc}", file=sys.stderr)
        return 2
    except JDFetchError as exc:
        print(f"failed to fetch --jd URL {args.jd!r}: {exc}", file=sys.stderr)
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
        result = build_from_evidence(subject=resolved.subject, evidence=evidence, runner=runner)
    except Exception as exc:
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    # Deterministic grade
    score_result = score_fit(result.portfolio, jd_text)

    # Bounded agent grade (grader_runner called with temperature=0)
    grade_result = bounded_grade(result.portfolio, score_result.grade, score_result.band, grader_runner)

    markdown = render_fit(score_result, grade_result)

    # Grounding summary → stderr only
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
