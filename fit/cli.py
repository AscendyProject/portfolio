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

import portfolio.i18n as i18n
from fit.grade import GraderRunner, bounded_grade, default_grader_runner
from fit.render import render_fit
from fit.score import score_fit
from portfolio.extract import extract_merged_prs
from portfolio.i18n import detect_language
from portfolio.jd_source import JDFetchError, JDFileReadError, JDInvalidURLError, load_jd
from portfolio.narrative import run_claude
from portfolio.output import emit_markdown
from portfolio.pipeline import resolve_and_optionally_mask
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
    parser.add_argument(
        "--mask-private", action="store_true", default=False, help="anonymize private GitHub repo names in output"
    )
    parser.add_argument(
        "--show-refs", action="store_true", default=False, help="include grounding refs in rendered output"
    )
    parser.add_argument(
        "--lang", choices=tuple(i18n.LANGS), default=None, help="output language code (default: auto-detect from JD)"
    )
    return parser


def run(
    argv: list[str],
    *,
    extractor=extract_merged_prs,
    runner=run_claude,
    fetcher=fetch_html,
    grader_runner: GraderRunner = default_grader_runner,
    visibility_lookup=None,
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

    # Resolve language: explicit --lang wins; otherwise detect from JD text.
    lang = args.lang if args.lang is not None else detect_language(jd_text)

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
        result, n_masked = resolve_and_optionally_mask(
            resolved,
            subject=resolved.subject,
            runner=runner,
            mask_private=args.mask_private,
            synthesis_runner=None,
            visibility_lookup=visibility_lookup,
            lang=lang,
        )
    except Exception as exc:
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    if args.mask_private:
        print(f"masked {n_masked} private repo(s)", file=sys.stderr)

    # Deterministic grade
    score_result = score_fit(result.portfolio, jd_text)

    # Bounded agent grade (grader_runner called with temperature=0)
    grade_result = bounded_grade(result.portfolio, score_result.grade, score_result.band, grader_runner, lang=lang)

    # Post-model scrub: replace any private owner/repo the grader emitted
    if args.mask_private and result.relabel:
        from fit.grade import GradeResult as _GradeResult

        def _scrub(s: str) -> str:
            for repo in sorted(result.relabel, key=len, reverse=True):
                s = s.replace(repo, result.relabel[repo])
            return s

        scrubbed_reasoning = [
            {
                "text": _scrub(b.get("text", "")),
                "evidence_refs": [_scrub(r) for r in b.get("evidence_refs", [])],
            }
            for b in grade_result.reasoning
        ]
        grade_result = _GradeResult(score=grade_result.score, reasoning=scrubbed_reasoning)

    markdown = render_fit(score_result, grade_result, show_refs=args.show_refs, lang=lang)

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
        emit_markdown(markdown)
    return 0


def main() -> None:
    """Console entrypoint: run with live services and exit with the result code."""
    sys.exit(run(sys.argv[1:]))
