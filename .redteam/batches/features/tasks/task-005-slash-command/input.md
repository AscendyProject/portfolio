# Task: `/portfolio` slash command — interactive front door to the CLI

## Goal
Add a Claude Code slash command `/portfolio` that is the interactive front door
to the flag-driven CLI. The user runs `/portfolio`, picks a source type
(github / web) and gives the source URL + author; the command runs
`python -m portfolio` with those values and shows the grounded portfolio. This
completes the original vision: pick a source, github → `gh`, blog → crawl.

This is a prompt/markdown artifact (a command definition), not Python — it adds
no runtime code and no tests; it wires the existing CLI to an interactive flow.

## What to build
- A project command file `.claude/commands/portfolio.md` with:
  - YAML frontmatter: a `description` and an `argument-hint` showing the expected
    args (e.g. `[github <repo-url> <author>] | [web <article-url> <author>]`).
  - A body that instructs the assistant to:
    1. Determine `source_type` (one of the CLI's `--source-type` choices:
       `github`, `web`), the source URL, and the author from `$ARGUMENTS`; if any
       is missing, ask the user (offer the github/web choice explicitly).
    2. Run the CLI exactly:
       `python -m portfolio --source-type <type> --source <url> --author <author>`
       (add `--out <file>` only if the user asked to save to a file).
    3. On non-zero exit, surface the stderr message and help the user correct the
       input (bad URL, unsupported type) — do NOT retry with invented values.
    4. On success, show the rendered Markdown and the one-line grounding summary
       (grounded / rejected / needs-confirmation counts) so the user sees what was
       dropped.
  - A hard rule in the body: use ONLY the source/author the user supplies; never
    fabricate a repo, URL, or author, and never edit code to "make it work" — this
    command only invokes the CLI.

## Constraints / hard rules (see project-context + security-checklist)
- The command must invoke the CLI via argv (`python -m portfolio ...`), never via
  a shell string it assembles from raw user input.
- It must not bypass the grounding/extraction logic — all work goes through the
  CLI; the command never writes portfolio claims itself.
- Keep `--source-type` choices in sync with the CLI by deferring to the CLI's own
  validation (the command should not hardcode a stale list beyond naming the two
  current types in the hint/prompt).
- No new Python, no new dependencies; do not change `portfolio/` behaviour.

## Out of scope
- Any change to the CLI / extract / narrate / ground / render code.
- Packaging the command into the redteam plugin (this is a project command under
  `.claude/commands/`).
- New source types (those are added in `portfolio/sources.py`, task-004 onward).

## Affected files
- `(new) .claude/commands/portfolio.md`

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
There are no unit tests for a prompt artifact; `verify.sh` (ruff + pytest over
`portfolio/`/`tests/`) must still pass unchanged (this task touches no Python).
Manual check: the command file is valid (parseable frontmatter), names the
correct CLI invocation and the current `--source-type` choices, and encodes the
"never invent a source/author; only invoke the CLI" rule.

## Risks
- Prompt drift: hardcoding source types in the command that later diverge from
  `known_source_types()`. Mitigate by phrasing the prompt to rely on the CLI's
  own error for an unknown type, and only naming github/web as the current
  options.
- A command that edits code or fabricates inputs would violate the grounding
  contract — the body must explicitly forbid both.
