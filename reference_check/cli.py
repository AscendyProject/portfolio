"""CLI entrypoint: wire the pipeline (extract → narrate → ground → letter) into a
grounded recommendation letter in Markdown.

`python -m reference_check --source-type github --source <url> --author <handle>`
runs the full pipeline and prints the grounded letter as Markdown to stdout
(or to `--out <file>`), with a grounding summary on stderr.

The model call (`runner`), `gh` extraction (`extractor`), and web fetch
(`fetcher`) are injectable so the CLI is unit-testable without live services.
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
from portfolio.sources import SourceRequest, UnsupportedSourceError, known_source_types, resolve_source
from portfolio.web import fetch_html
from reference_check.letter import build_letter
from reference_check.render import render_letter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reference_check",
        description="Render a grounded recommendation letter from a developer's real work.",
    )
    parser.add_argument("--source-type", required=True, choices=list(known_source_types()))
    parser.add_argument("--source", help="source URL (a github repo URL, or an article URL for --source-type web)")
    parser.add_argument("--author", help="GitHub handle whose merged PRs are the evidence")
    parser.add_argument("--out", help="write Markdown to this file instead of stdout")
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
    visibility_lookup=None,
) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web), and `runner` (model) are injectable
    seams: the defaults hit live services, but tests pass fakes so no live
    service is required. The same `runner` drives both the narration step and
    the letter composition step.
    """
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

    # Extract evidence + build grounded portfolio.
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

    # Compose grounded letter from the portfolio.
    try:
        draft = build_letter(result.portfolio, runner, lang=lang)
    except Exception as exc:
        print(f"failed to build letter: {exc}", file=sys.stderr)
        return 1

    # Post-model scrub: replace any private owner/repo the letter runner emitted
    if args.mask_private and result.relabel:
        from reference_check.letter import LetterDraft, LetterParagraph

        def _scrub(s: str) -> str:
            for repo in sorted(result.relabel, key=len, reverse=True):
                s = s.replace(repo, result.relabel[repo])
            return s

        scrubbed_paragraphs = [
            LetterParagraph(
                text=_scrub(para.text),
                evidence_refs=[_scrub(r) for r in para.evidence_refs],
                grounded=para.grounded,
            )
            for para in draft.paragraphs
        ]
        draft = LetterDraft(
            subject=draft.subject,
            paragraphs=scrubbed_paragraphs,
            rejected_paragraphs=draft.rejected_paragraphs,
        )

    markdown = render_letter(draft, show_refs=args.show_refs, lang=lang)

    # Grounding summary on stderr only.
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
