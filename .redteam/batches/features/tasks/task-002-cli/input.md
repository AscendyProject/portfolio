# Task: CLI entrypoint that wires the full pipeline to the Markdown renderer

## Goal
Add a user-facing CLI entrypoint (`python -m portfolio`) that runs the existing
pipeline (extract → narrate → ground) for a **GitHub** source and renders the
result with `render_markdown`. This connects the two halves that exist but don't
yet meet: `pipeline.build_portfolio()` and `render.render_markdown()`.

A `--source-type` switch is introduced now with two branches — `github`
(implemented) and `others` (recognized but **not yet supported**) — so the
later multi-source work (blog/web crawling) and the `/portfolio` slash command
have a seam to extend. Only the `github` branch is implemented in this task.

## What to build
- A new module `portfolio/cli.py` and `portfolio/__main__.py` so
  `python -m portfolio ...` works.
- Arguments:
  - `--source-type {github,others}` (required). `github` runs the pipeline;
    `others` exits with a clear, non-zero "source type 'others' is not supported
    yet" message (no empty/misleading output).
  - `--source <url>` (required for github): a GitHub URL like
    `https://github.com/<owner>/<repo>`. Parse it to the `owner/repo` string the
    extractor needs. Reject a URL that is not a parseable GitHub `owner/repo`
    with a clear error (non-zero exit), do not fall through to a `gh` call with
    garbage.
  - `--author <handle>` (required for github): passed through to extraction.
  - `--max-claims <int>` (optional, default 12): forwarded to the pipeline.
  - `--out <file>` (optional): when given, write the rendered Markdown to that
    file (UTF-8); otherwise print it to **stdout**.
- Behaviour for `github`:
  - call the pipeline to produce a `BuildResult`, then `render_markdown` on
    `BuildResult.portfolio`,
  - write the Markdown to stdout (or `--out`),
  - print a one-line **grounding summary** to **stderr** with the counts of
    grounded / rejected / needs-confirmation claims (so the human sees what was
    dropped — never silently hide un-grounded claims).
- The pipeline's model call (`runner`) and the `gh` extraction must be
  **injectable seams** in `cli.py` (e.g. a core function that accepts an
  `extractor` and a `runner`, with the real `extract_merged_prs` / `run_claude`
  as defaults) so the CLI is unit-testable without a live `gh` or `claude`.

## Constraints / hard rules (see project-context + security-checklist)
- Do NOT change the grounding contract: the CLI renders only
  `BuildResult.portfolio.claims` (already the grounded set). It must not
  re-ground, re-classify, or render rejected/needs-confirmation claims into the
  document.
- No shell string interpolation: extraction already shells out via argv lists;
  the CLI must not build shell command strings. The parsed `owner/repo` is passed
  as data to the existing `extract_merged_prs(repo=...)`.
- GitHub URL parsing is the only new "source" logic here. Keep it small; a full
  source dispatcher abstraction is a later task. `others` is a stub branch, not
  an implementation.
- stdlib only (argparse is fine). No new dependencies.
- Errors exit non-zero with a message on stderr; success exits 0.

## Out of scope
- The `others` source implementation (blog/web crawling) — this task only
  reserves the branch and emits "not supported yet".
- The interactive `/portfolio` slash command and any interactive prompting — the
  CLI is flag-driven only.
- A reusable source-dispatcher abstraction / GitHub profile (`/user`) URLs.
- Changing extract / narrate / grounding / render behaviour.

## Affected files
- `(new) portfolio/cli.py`
- `(new) portfolio/__main__.py`
- `(new) tests/test_cli.py`

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests should cover (build `Evidence`/`Claim`/`Portfolio` directly and inject a
fake `extractor` and fake `runner`, no live services — per test-conventions):
- a github run renders the subject + grounded claims to stdout, and writes to a
  file when `--out` is given;
- the grounding summary (grounded/rejected/needs-confirmation counts) is emitted
  to stderr, not into the Markdown;
- `--source-type others` exits non-zero with the "not supported yet" message and
  produces no Markdown document;
- a non-GitHub / unparseable `--source` URL exits non-zero with a clear error and
  never invokes the extractor;
- a valid `https://github.com/<owner>/<repo>` URL parses to `owner/repo` and is
  passed to the injected extractor.

## Risks
- GitHub URL parsing edge cases (trailing slash, `.git` suffix, extra path
  segments, `http` vs `https`). Keep parsing strict and well-tested; reject
  rather than guess when the URL is not a clean `owner/repo`.
- Testability hinges on the injectable seams — if the model/`gh` calls aren't
  injectable, the tests will be forced to hit live services. Design the seam
  first.
