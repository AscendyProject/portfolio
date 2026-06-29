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
import re
import subprocess
import sys
from pathlib import Path

import portfolio.i18n as i18n
from portfolio.extract import extract_merged_prs
from portfolio.narrative import run_claude
from portfolio.output import emit_markdown
from portfolio.mask import _rewrite_text
from portfolio.pipeline import resolve_and_optionally_mask
from portfolio.share import GistSharer, Sharer, share_links
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
    parser.add_argument(
        "--mask-private", action="store_true", default=False, help="anonymize private GitHub repo names in output"
    )
    parser.add_argument(
        "--show-refs", action="store_true", default=False, help="include grounding refs in rendered output"
    )
    parser.add_argument("--lang", choices=tuple(i18n.LANGS), default=None, help="output language code (default: en)")
    parser.add_argument(
        "--share", action="store_true", default=False, help="publish rating to a GitHub Gist and print share links"
    )
    parser.add_argument(
        "--share-public", action="store_true", default=False, help="make the Gist public (default: secret)"
    )
    parser.add_argument(
        "--no-mask-on-share", action="store_true", default=False, help="disable auto-masking when --share is set"
    )
    return parser


def run(
    argv: list[str],
    *,
    extractor=extract_merged_prs,
    runner=run_claude,
    fetcher=fetch_html,
    grader_runner=_default_grader_runner,
    visibility_lookup=None,
    sharer: Sharer | None = None,
) -> int:
    """Execute the CLI. Returns a process exit code (0 = success).

    `extractor` (gh), `fetcher` (web), `runner` (narration model), and
    `grader_runner` (agent grader) are injectable seams: the defaults hit live
    services, but tests pass fakes so no live service is required.

    `sharer` is an injectable Sharer instance used when --share is set.
    Defaults to GistSharer() when None and --share is active.
    """
    args = _build_parser().parse_args(argv)
    lang = args.lang or "en"

    # Privacy-first mask resolution: --share enables masking by default unless
    # --no-mask-on-share is explicitly given. --mask-private always wins.
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

    # Extract evidence + build grounded portfolio.
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
    # succeeds (so a failure emits exactly one clean error line — IR-003). Off the
    # share path this prints here, preserving existing ordering byte-for-byte.
    mask_summary = f"masked {n_masked} private repo(s)" if effective_mask else None
    if mask_summary and not args.share:
        print(mask_summary, file=sys.stderr)

    # Deterministic profiling (pure, no model call).
    profile_result = profile(result.portfolio)

    # Bounded agent grading (injectable grader_runner, temperature=0).
    try:
        grade_result = grade(result.portfolio, profile_result, grader_runner, lang=lang)
    except Exception as exc:
        print(f"failed to grade: {exc}", file=sys.stderr)
        return 1

    # Post-model scrub: replace any private owner/repo the grader emitted
    if effective_mask and result.relabel:
        from rating.grade import GradeResult as _GradeResult

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
        grade_result = _GradeResult(
            score=grade_result.score,
            grade=grade_result.grade,
            reasoning=scrubbed_reasoning,
        )

    markdown = render_rating(result.portfolio, profile_result, grade_result, show_refs=args.show_refs, lang=lang)

    # Grounding summary on stderr only (never in the rendered body). Built here but
    # printed per-path below: on the --share path it is deferred until AFTER a
    # successful publish, so a publish failure emits exactly ONE clean stderr line.
    grounding = result.grounding
    grounding_summary = (
        f"grounded: {len(grounding.grounded)}  "
        f"rejected: {len(grounding.rejected)}  "
        f"needs-confirmation: {len(grounding.needs_confirmation)}"
    )

    if args.share:
        # Append provenance footer — share path only; non-share render stays byte-identical.
        footer = i18n.LANGS[lang]["share_provenance_footer"]
        shared_markdown = markdown + "\n\n" + footer + "\n"

        # The shared artifact and its gist filename are channels that bypass the
        # evidence/claim masking applied during the pipeline — e.g. `render_rating`
        # renders the subject verbatim into the heading. Scrub the FULL shared Markdown
        # AND the title with the same relabel map so no raw private repo name (from the
        # subject or anywhere else) can reach the gist body or filename.
        def _scrub_shared(s: str) -> str:
            # Reuse the canonical masking scrubber (case-insensitive, longest-first)
            # so the share channels mask exactly like the rest of the pipeline.
            return _rewrite_text(s, result.relabel) if (effective_mask and result.relabel) else s

        shared_markdown = _scrub_shared(shared_markdown)

        # Publish via the injected (or default) Sharer. On failure, the only stderr
        # output is the single clean error line below (the grounding summary is not
        # emitted yet), satisfying the single-line failure contract.
        active_sharer = sharer if sharer is not None else GistSharer()
        # Title → gist filename: scrub with the relabel map, then restrict to
        # filename-safe characters (no path separators / odd bytes reach `gh`).
        title = re.sub(r"[^A-Za-z0-9._-]+", "-", _scrub_shared(f"rating-{result.portfolio.subject}")).strip("-") or (
            "rating"
        )
        try:
            share_result = active_sharer.publish(shared_markdown, title=title, public=args.share_public)
        except Exception:
            print("share failed: could not publish to Gist", file=sys.stderr)
            return 1

        # Success: deferred stderr lines (mask summary, grounding summary), then the
        # footer-bearing report → gist URL → social links on stdout.
        if mask_summary:
            print(mask_summary, file=sys.stderr)
        print(grounding_summary, file=sys.stderr)
        emit_markdown(shared_markdown)
        links = share_links(share_result.url, f"My grounded capability rating: {share_result.url}")
        print(share_result.url)
        print(links["linkedin"])
        print(links["x"])
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
