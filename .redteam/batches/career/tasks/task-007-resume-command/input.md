# Task: /resume command — wire the grounded resume selector into a real command

## Goal
Turn the existing deterministic resume core (`resume/select.py`, from task-002)
into a **user-facing command**: a `python -m resume` CLI plus a `/resume` Claude
Code slash command that, given a source (the same `--source-type` inputs as
`/portfolio`) and a target job description (JD), produces an **evidence-grounded
resume in Markdown** — selecting and ordering the portfolio's already-grounded
claims to fit the JD. This is the command-wiring slice; it adds NO new judgment.

## Why this matters (hard constraint, not a nicety)
The resume is exactly where overclaiming happens, so this command must be a thin,
**grounding-preserving** shell over machinery that already exists:
- It reuses the `/portfolio` pipeline to obtain a grounded `Portfolio`, then
  `resume.select` (`jd_keywords` → `select_claims` → `enforce_grounding`) to pick
  claims. It must NOT invent claims, add evidence, raise confidence, or re-score
  by any means other than the existing deterministic selection.
- Every bullet in the rendered resume must trace to a claim already on
  `portfolio.claims` whose `evidence_refs` are a subset of the portfolio's
  evidence. The `enforce_grounding` honesty re-check is applied; anything that
  fails is dropped (fail closed), never rendered.

## What to build
Mirror the existing `python -m portfolio` shape; do NOT restructure the portfolio
CLI (the `/portfolio` command depends on `python -m portfolio --source-type ...`).

1. `python -m resume` CLI (`resume/__main__.py` + `resume/cli.py`):
   `python -m resume --source-type {github|web} --source <URL> --author <handle>
   --jd <path-to-jd.txt> [--top-n N] [--out FILE]`. It:
   - builds a grounded `Portfolio` by reusing `portfolio.pipeline` (extract →
     narrate → ground) — the narrative model call stays the existing injectable
     `runner` so tests run with no live CLI/network;
   - reads the JD text from `--jd`, runs `resume.select.build_resume` (or the
     `jd_keywords`/`select_claims`/`enforce_grounding` functions) with `--top-n`
     (reuse the module's default if omitted);
   - renders the resulting `ResumeDraft` to Markdown and prints to stdout (or
     writes `--out`), with a one-line grounding summary on stderr (mirror the
     portfolio CLI's behavior).
2. A small deterministic resume renderer (`resume/render.py`, or reuse helpers
   from `portfolio.render` — reuse, don't duplicate): `ResumeDraft` → Markdown,
   each selected grounded claim as a bullet that keeps its evidence refs. Escape
   claim/evidence text the same way the portfolio renderer does.
3. A `/resume` slash command (`.claude/commands/resume.md`) modeled on
   `.claude/commands/portfolio.md`: ask for source type + URL + author + a JD,
   run `python -m resume ...` (values as separate argv args, never shell-assembled),
   and show the grounded resume + grounding summary. No hand-written bullets.
4. README note: add `/resume` to the documented surface (a new public command
   that consumes the grounding contract — project-context requires a README note).

## Constraints / hard rules (see project-context + security-checklist)
- **No new judgment in this slice.** Reuse `resume.select` as-is; do not add an
  LLM tailoring/rewording step, scoring change, or any "% / rank" feature here.
- Do NOT modify `resume/select.py`'s logic, or `portfolio/` internals
  (`extract`/`narrative`/`grounding`/`pipeline`/`model`/`render`). Import and
  reuse them.
- **Grounding is the security boundary.** A resume bullet not in the grounded
  portfolio set, or citing a ref not in the portfolio's evidence, must be rejected
  — never rendered. Apply `enforce_grounding`.
- **No shell string-building.** All `gh`/`claude`/`codex` and the slash command's
  `python -m resume` invocation use argv lists; never interpolate untrusted text
  (URL, author, JD) into a command string.
- **Model output is untrusted** (handled inside the existing pipeline); the CLI
  must not fabricate claims if narration returns nothing — emit an empty/though
  grounded resume and a clear summary, fail closed.
- Stdlib-only engine; no new runtime dependency.

## Out of scope
- LLM-based rewriting/tailoring of bullet wording, and any "% fit / rank /
  percentile" judgment (these are later tasks: fit, rating).
- reference-check / fit / rating commands (separate tasks).
- PDF/HTML output; live JD fetching from a URL; cover letters.

## Affected files
- `(new) resume/__main__.py` — `python -m resume` entrypoint
- `(new) resume/cli.py` — arg parsing + pipeline→select→render wiring (injectable runner/fetcher seams for tests)
- `(new) resume/render.py` — deterministic `ResumeDraft` → Markdown (or reuse `portfolio.render` helpers)
- `(new) .claude/commands/resume.md` — `/resume` slash command
- `(new) tests/test_resume_cli.py` — CLI wiring tests (injected runner + fetcher; no live services)
- `README.md` — document the new `/resume` command

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (build `Portfolio`/`Claim`/`Evidence` directly and inject the narrative
runner + any fetcher — no `gh`/network/live CLI) must cover: an end-to-end
`python -m resume` run renders only grounded selected claims for a JD; `--top-n`
caps the bullets; `--out` writes the file and stdout stays clean; a claim whose
evidence is not in the portfolio never reaches the output (honesty re-check);
exit codes (0 success, non-zero on bad source/JD path); the slash command passes
user values as separate argv args (no shell assembly).

## Risks
- Command surface choice: a sibling `python -m resume` entrypoint (recommended,
  least invasive) vs adding subcommands to `python -m portfolio`. The planner
  should pick one and justify; recommendation is the sibling entrypoint so the
  existing `/portfolio` invocation is untouched.
- Resume rendering format is a small design choice — keep it simple and pinned in
  tests; do not over-engineer (no templating engine, no PDF).
