"""CLI entrypoint: wire the pipeline (extract → narrate → ground → profile → grade →
render) into a grounded capability rating in Markdown.

`python -m rating --source-type github --source <url> --author <handle> [--out FILE]`
runs the full pipeline and prints the grounded scorecard as Markdown to stdout
(or to `--out <file>`), with a grounding summary on stderr.

The model call (`runner`), `gh` extraction (`extractor`), web fetch (`fetcher`),
and agent grader (`grader_runner`) are injectable so the CLI is unit-testable without
live services.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from portfolio.extract import extract_merged_prs
from portfolio.narrative import run_claude
from portfolio.output import emit_markdown
from portfolio.pipeline import build_from_evidence
from portfolio.sources import SourceRequest, UnsupportedSourceError, known_source_types, resolve_source
from portfolio.web import fetch_html
from rating.grade import grade
from rating.profile import profile
from rating.render import render_rating


def _default_grader_runner(prompt: str, temperature: int = 0) -> str:
    """Default grader runner: deterministic claude call, JSON output."""
    proc = subprocess.run(
        ["claude", "--print", "--output-format", "json", "--permission-mode", "plan"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}")
    result = json.loads(proc.stdout).get("result")
    if not isinstance(result, str):
        raise RuntimeError("claude returned no string .result")
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rating",
        description="Render a grounded capability rating for a developer.",
    )
    parser.add_argument("--source-type", required=True, choices=list(known_source_types()))
    parser.add_argument("--source", help="source URL (a GitHub repo URL, or an article URL for --source-type web)")
    parser.add_argument("--author", help="GitHub handle whose merged PRs are the evidence")
    parser.add_argument("--out", help="write Markdown to this file instead of stdout")
    return parser


def run(
    argv: list[str],
    *,
    extractor=extract_merged_prs,
    runner=run_claude,
    fetcher=fetch_html,
    grader_runner=_default_grader_runner,
) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web), `runner` (narration model), and
    `grader_runner` (agent grader) are injectable seams: the defaults hit live
    services, but tests pass fakes so no live service is required.
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

    # Extract evidence + build grounded portfolio.
    try:
        evidence = resolved.extract()
        result = build_from_evidence(subject=resolved.subject, evidence=evidence, runner=runner)
    except Exception as exc:
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    # Deterministic profiling (pure, no model call).
    profile_result = profile(result.portfolio)

    # Bounded agent grading (injectable grader_runner, temperature=0).
    try:
        grade_result = grade(result.portfolio, profile_result, grader_runner)
    except Exception as exc:
        print(f"failed to grade: {exc}", file=sys.stderr)
        return 1

    markdown = render_rating(result.portfolio, profile_result, grade_result)

    # Grounding summary on stderr only (never in the rendered body).
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
