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

import portfolio.i18n as i18n
from portfolio.extract import extract_merged_prs
from portfolio.i18n import detect_language
from portfolio.jd_source import JDFetchError, JDFileReadError, JDInvalidURLError, load_jd
from portfolio.narrative import run_claude
from portfolio.output import emit_markdown
from portfolio.pipeline import resolve_and_optionally_mask
from portfolio.share import GistSharer, ShareError, Sharer, publish_share
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
    parser.add_argument(
        "--jd",
        required=True,
        help="job description: a local file (UTF-8 text, or PDF with the 'pdf' extra) or an http(s) URL",
    )
    parser.add_argument("--top-n", type=int, default=12, help="max resume bullets to render (default: 12)")
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
        "--share", action="store_true", default=False, help="publish resume to a GitHub Gist and print share links"
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
    visibility_lookup=None,
    sharer: Sharer | None = None,
) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web fetch), and `runner` (model) are injectable
    seams: the defaults hit live services, but tests pass fakes so no live
    service is required.

    `sharer` is an injectable Sharer instance used when --share is set.
    Defaults to GistSharer() when None and --share is active.
    """
    args = _build_parser().parse_args(argv)

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
            max_claims=args.top_n,
            mask_private=effective_mask,
            synthesis_runner=None,
            visibility_lookup=visibility_lookup,
            lang=lang,
        )
    except Exception as exc:
        print(f"failed to build resume: {exc}", file=sys.stderr)
        return 1

    # On the --share path every pre-publish stderr line is deferred until publish
    # succeeds (so a failure emits exactly one clean error line — IR-003). Off the
    # share path this prints here, preserving existing ordering byte-for-byte.
    mask_summary = f"masked {n_masked} private repo(s)" if effective_mask else None
    if mask_summary and not args.share:
        print(mask_summary, file=sys.stderr)

    draft = build_resume(result.portfolio, jd_text, args.top_n)
    markdown = render_resume(draft, show_refs=args.show_refs, lang=lang)

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
                subject=f"resume-{result.portfolio.subject}",
                lang=lang,
                public=args.share_public,
                effective_mask=effective_mask,
                relabel=result.relabel,
                sharer=active_sharer,
                card_svg=None,
            )
        except ShareError:
            print("share failed: could not publish to Gist", file=sys.stderr)
            return 1

        # Success: deferred stderr lines, then stdout lines (no badge for resume).
        if mask_summary:
            print(mask_summary, file=sys.stderr)
        print(grounding_summary, file=sys.stderr)
        emit_markdown(bundle.shared_md)
        print(bundle.url)
        print(bundle.linkedin)
        print(bundle.x)
        return 0

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
