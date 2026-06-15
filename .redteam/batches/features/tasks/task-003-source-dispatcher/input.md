# Task: source dispatcher — make Evidence extraction pluggable by source type

## Goal
Extract the source-specific logic that currently lives inline in `portfolio/cli.py`
(GitHub URL parsing + the `github`/`others` branching) into a dedicated
`portfolio/sources.py` dispatcher. After this, **adding a new source type is
registering a handler in `sources.py` — the CLI does not change.** This is the
seam the later web/blog source (task-004) and the `/portfolio` slash command
(task-005) build on.

This is a behavior-preserving refactor: from the user's point of view the CLI
behaves exactly as it does today for `github`, `others`, and bad URLs.

## What to build
- A new module `portfolio/sources.py` containing:
  - `parse_github_source(url) -> str` — **moved** from `cli.py` unchanged
    (same strict parsing/rejection rules).
  - `KNOWN_SOURCE_TYPES` — the recognized source types (currently
    `("github", "others")`); `cli.py`'s `--source-type` choices come from this.
  - `class UnsupportedSourceError(Exception)` — raised for a recognized but
    unimplemented type (`others`) and for an unknown type.
  - `SourceRequest` — the raw CLI inputs a handler needs (`source`, `author`,
    and the injectable `extractor`).
  - `ResolvedSource` — what a handler returns: a `subject` plus a **deferred**
    `extract()` callable that performs the (network) extraction only when called.
  - `resolve_source(source_type, request) -> ResolvedSource` — looks the type up
    in a handler registry and dispatches; raises `UnsupportedSourceError` for
    `others`/unknown, and the handler raises `ValueError` for a bad/missing
    source spec.
  - a handler registry (type -> handler) with the `github` handler registered.
- Refactor `portfolio/cli.py` to delegate to `resolve_source`:
  - `--source-type` choices come from `KNOWN_SOURCE_TYPES`.
  - validation/parse errors (`UnsupportedSourceError`, `ValueError`) exit `2`
    with a stderr message **before** any extraction;
  - the deferred `extract()` + `build_from_evidence` run inside the existing
    top-level error boundary (any failure -> exit `1` with a stderr message).
  - The github-specific parsing must no longer live inline in `cli.py`.

## Constraints / hard rules (see project-context + security-checklist)
- Behavior preserving: every existing `tests/test_cli.py` behavior must still
  hold (github render to stdout / `--out`; grounding summary on stderr; grounded
  claims only; `others` -> non-zero "not supported yet"; bad/non-github
  `--source` -> non-zero **without invoking the extractor**; valid URL ->
  `owner/repo` passed to the extractor).
- The extractor stays an injectable seam (now carried on `SourceRequest`) so the
  CLI and the dispatcher are unit-testable without live `gh`.
- `extract()` is deferred: `resolve_source` itself must NOT hit the network — a
  bad source URL is rejected (parse error) before any extraction is attempted.
- stdlib only; do not change extract / narrate / grounding / render behaviour.

## Out of scope
- Any new source implementation (web/blog) — only `github` is wired; `others`
  stays an unsupported stub. (task-004)
- The `/portfolio` slash command. (task-005)
- Changing the grounding contract or the rendered Markdown.

## Affected files
- `(new) portfolio/sources.py`
- `(modified) portfolio/cli.py`
- `(new) tests/test_sources.py`
- `(modified) tests/test_cli.py` — move the `parse_github_source` unit cases to
  `test_sources.py`; keep the CLI-behavior tests.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (build objects directly; inject a fake `extractor`; no live services):
- `test_sources.py`: `resolve_source("github", ...)` returns `subject == author`
  and a deferred `extract()` that, when called, invokes the injected extractor
  with `repo == "owner/repo"`; `resolve_source` does NOT call the extractor until
  `extract()` is invoked; `others` and an unknown type raise
  `UnsupportedSourceError`; a missing `--source`/`--author` raises `ValueError`;
  the `parse_github_source` accept/reject cases (moved from `test_cli.py`).
- A test proving the seam: registering a fake handler for a new source type makes
  `resolve_source` dispatch to it (without editing the CLI).
- `test_cli.py`: all existing CLI behaviors continue to pass against the
  refactored wiring.

## Risks
- Import churn: `tests/test_cli.py` currently imports `parse_github_source` from
  `portfolio.cli`; move that import/those cases to `test_sources.py` rather than
  leaving a dead re-export.
- Over-abstraction: keep the registry minimal (one real handler + the `others`
  stub). Do not introduce a class hierarchy or plugin-entrypoint machinery.
