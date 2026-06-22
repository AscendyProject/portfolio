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
from fit.render import render_fit, render_fit_batch
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
    parser.add_argument("--jd", default=None, help="path or http(s) URL to the job description file (plain text)")
    parser.add_argument(
        "--jd-dir",
        default=None,
        help="directory of JD files (*.txt, *.md) to score in batch; mutually exclusive with --jd",
    )
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

    # Mutual-exclusion and required check for --jd / --jd-dir.
    if args.jd is not None and args.jd_dir is not None:
        print("--jd and --jd-dir are mutually exclusive; supply exactly one", file=sys.stderr)
        return 2
    if args.jd is None and args.jd_dir is None:
        print("one of --jd or --jd-dir is required", file=sys.stderr)
        return 2

    # ── Batch mode (--jd-dir) ─────────────────────────────────────────────────
    if args.jd_dir is not None:
        return _run_batch(args, extractor=extractor, runner=runner, visibility_lookup=visibility_lookup)

    # ── Single-JD mode (--jd) — original path, byte-identical output ─────────
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


def _run_batch(
    args,
    *,
    extractor,
    runner,
    visibility_lookup,
) -> int:
    """Execute batch mode: score the portfolio against every JD in --jd-dir."""
    jd_dir = Path(args.jd_dir)

    # Collect matching files non-recursively; accepted suffixes are .txt and .md (case-sensitive).
    _ACCEPTED_SUFFIXES = {".txt", ".md"}
    try:
        entries = list(jd_dir.iterdir())
    except OSError:
        entries = []

    jd_files = sorted(
        [p for p in entries if p.is_file() and p.suffix in _ACCEPTED_SUFFIXES],
        key=lambda p: p.name,
    )

    if not jd_files:
        print(f"--jd-dir {args.jd_dir!r}: no matching JD files (*.txt, *.md) found", file=sys.stderr)
        return 2

    # Language: explicit --lang wins; batch mode defaults to "en" (no auto-detect from JD).
    lang = args.lang if args.lang is not None else "en"

    # Resolve the source (validation/parse only — no extraction yet).
    try:
        resolved = resolve_source(
            args.source_type,
            SourceRequest(source=args.source, author=args.author, extractor=extractor, fetcher=None),
        )
    except UnsupportedSourceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"invalid source: {exc}", file=sys.stderr)
        return 2

    # Build the portfolio ONCE.
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

    portfolio = result.portfolio

    # Score per JD; collect (basename, ScoreResult) pairs.
    batch_results: list[tuple[str, object]] = []
    for jd_path in jd_files:
        jd_text = jd_path.read_text(encoding="utf-8")
        score_result = score_fit(portfolio, jd_text)
        batch_results.append((jd_path.name, score_result))

    # Grounding summary → stderr, exactly once.
    grounding = result.grounding
    print(
        f"grounded: {len(grounding.grounded)}  "
        f"rejected: {len(grounding.rejected)}  "
        f"needs-confirmation: {len(grounding.needs_confirmation)}",
        file=sys.stderr,
    )

    markdown = render_fit_batch(batch_results, lang=lang)

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
