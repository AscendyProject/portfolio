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
from portfolio.share import GistSharer, ShareError, Sharer, publish_share
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
    parser.add_argument(
        "--jd",
        default=None,
        help="job description: a local file (UTF-8 text, or PDF with the 'pdf' extra) or an http(s) URL",
    )
    parser.add_argument(
        "--jd-dir",
        default=None,
        help="directory of JD files (*.txt, *.md, *.pdf) to score in batch; mutually exclusive with --jd",
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
    parser.add_argument(
        "--share", action="store_true", default=False, help="publish fit report to a GitHub Gist and print share links"
    )
    parser.add_argument(
        "--share-public", action="store_true", default=False, help="make the Gist public (default: secret)"
    )
    parser.add_argument(
        "--no-mask-on-share",
        action="store_true",
        default=False,
        help="disable auto-masking when --share is set",
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
    sharer: Sharer | None = None,
) -> int:
    """Execute the /fit CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web fetch), `runner` (narrative model), and
    `grader_runner` (bounded grader model) are injectable seams: the defaults hit
    live services, but tests pass fakes so no live service is required.

    `sharer` is an injectable Sharer instance used when --share is set.
    Defaults to GistSharer() when None and --share is active.
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
        return _run_batch(
            args,
            extractor=extractor,
            runner=runner,
            fetcher=fetcher,
            visibility_lookup=visibility_lookup,
            sharer=sharer,
        )

    # ── Single-JD mode (--jd) — original path, byte-identical output ─────────
    # Privacy-first mask resolution: --share enables masking by default unless
    # --no-mask-on-share is explicitly given. --mask-private always wins.
    effective_mask = args.mask_private or (args.share and not args.no_mask_on_share)

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
            mask_private=effective_mask,
            synthesis_runner=None,
            visibility_lookup=visibility_lookup,
            lang=lang,
        )
    except Exception as exc:
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    # On the --share path every pre-publish stderr line is deferred until publish
    # succeeds (so a failure emits exactly one clean error line — IR-003).
    mask_summary = f"masked {n_masked} private repo(s)" if effective_mask else None
    if mask_summary and not args.share:
        print(mask_summary, file=sys.stderr)

    # Deterministic grade
    score_result = score_fit(result.portfolio, jd_text)

    # Bounded agent grade (grader_runner called with temperature=0)
    grade_result = bounded_grade(result.portfolio, score_result.grade, score_result.band, grader_runner, lang=lang)

    # Post-model scrub: replace any private owner/repo the grader emitted
    if effective_mask and result.relabel:
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

    grounding = result.grounding
    grounding_summary = (
        f"grounded: {len(grounding.grounded)}  "
        f"rejected: {len(grounding.rejected)}  "
        f"needs-confirmation: {len(grounding.needs_confirmation)}"
    )

    if args.share:
        active_sharer = sharer if sharer is not None else GistSharer()
        try:
            bundle = publish_share(
                markdown,
                subject=f"fit-{result.portfolio.subject}",
                lang=lang,
                public=args.share_public,
                effective_mask=effective_mask,
                relabel=result.relabel,
                sharer=active_sharer,
                card_svg=None,
                summary="My grounded JD fit",
            )
        except ShareError:
            print("share failed: could not publish to Gist", file=sys.stderr)
            return 1

        # Success: deferred stderr lines, then stdout lines (no badge for fit).
        if mask_summary:
            print(mask_summary, file=sys.stderr)
        print(grounding_summary, file=sys.stderr)
        emit_markdown(bundle.shared_md)
        print(bundle.url)
        print(bundle.linkedin)
        print(bundle.x)
        return 0

    # Non-share path: grounding summary now.
    print(grounding_summary, file=sys.stderr)

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
    fetcher,
    visibility_lookup,
    sharer: Sharer | None = None,
) -> int:
    """Execute batch mode: score the portfolio against every JD in --jd-dir."""
    jd_dir = Path(args.jd_dir)

    # Collect matching files non-recursively; accepted suffixes are .txt, .md, .pdf
    # (case-sensitive). PDFs are extracted via load_jd, exactly like single --jd.
    _ACCEPTED_SUFFIXES = {".txt", ".md", ".pdf"}
    try:
        entries = list(jd_dir.iterdir())
    except OSError:
        entries = []

    jd_files = sorted(
        [p for p in entries if p.is_file() and p.suffix in _ACCEPTED_SUFFIXES],
        key=lambda p: p.name,
    )

    if not jd_files:
        print(f"--jd-dir {args.jd_dir!r}: no matching JD files (*.txt, *.md, *.pdf) found", file=sys.stderr)
        return 2

    # Language: explicit --lang wins; batch mode defaults to "en" (no auto-detect from JD).
    lang = args.lang if args.lang is not None else "en"

    # Privacy-first mask resolution (same as single-JD mode).
    effective_mask = args.mask_private or (args.share and not args.no_mask_on_share)

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

    # Preflight: read & validate EVERY JD before the expensive build (codex IR-002),
    # so a missing pypdf / corrupt / encrypted / oversized PDF fails fast without
    # wasting source extraction or model work. Loaded text is reused for scoring.
    jd_loaded: list[tuple[str, str]] = []
    for jd_path in jd_files:
        try:
            # PDFs are extracted the same way as single --jd (text → UTF-8 decode,
            # PDF → pypdf). fetcher is unused for a local path but required by the sig.
            jd_loaded.append((jd_path.name, load_jd(str(jd_path), fetcher=fetcher)))
        except JDFileReadError as exc:
            print(f"cannot read JD file {jd_path!r}: {exc}", file=sys.stderr)
            return 2

    # Build the portfolio ONCE.
    try:
        result, n_masked = resolve_and_optionally_mask(
            resolved,
            subject=resolved.subject,
            runner=runner,
            mask_private=effective_mask,
            synthesis_runner=None,
            visibility_lookup=visibility_lookup,
            lang=lang,
        )
    except Exception as exc:
        print(f"failed to build portfolio: {exc}", file=sys.stderr)
        return 1

    # On the --share path defer mask summary until after successful publish.
    mask_summary = f"masked {n_masked} private repo(s)" if effective_mask else None
    if mask_summary and not args.share:
        print(mask_summary, file=sys.stderr)

    portfolio = result.portfolio

    # Score per JD; collect (basename, ScoreResult) pairs.
    batch_results: list[tuple[str, object]] = []
    for name, jd_text in jd_loaded:
        score_result = score_fit(portfolio, jd_text)
        batch_results.append((name, score_result))

    grounding = result.grounding
    grounding_summary = (
        f"grounded: {len(grounding.grounded)}  "
        f"rejected: {len(grounding.rejected)}  "
        f"needs-confirmation: {len(grounding.needs_confirmation)}"
    )

    markdown = render_fit_batch(batch_results, lang=lang)

    if args.share:
        active_sharer = sharer if sharer is not None else GistSharer()
        try:
            bundle = publish_share(
                markdown,
                subject=f"fit-{result.portfolio.subject}",
                lang=lang,
                public=args.share_public,
                effective_mask=effective_mask,
                relabel=result.relabel,
                sharer=active_sharer,
                card_svg=None,
                summary="My grounded JD fit",
            )
        except ShareError:
            print("share failed: could not publish to Gist", file=sys.stderr)
            return 1

        # Success: deferred stderr lines, then stdout lines.
        if mask_summary:
            print(mask_summary, file=sys.stderr)
        print(grounding_summary, file=sys.stderr)
        emit_markdown(bundle.shared_md)
        print(bundle.url)
        print(bundle.linkedin)
        print(bundle.x)
        return 0

    # Non-share path: grounding summary now.
    print(grounding_summary, file=sys.stderr)

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
