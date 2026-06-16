# Task: /reference-check — a grounded recommendation letter from real work

## Goal
Add a `python -m reference_check` CLI plus a `/reference-check` Claude Code slash
command that, given a source (the same `--source-type` inputs as `/portfolio`),
produces a **recommendation letter** about the developer in Markdown — written
from the developer's *real, grounded* work. Every concrete accomplishment the
letter states must trace to evidence that actually exists in the grounded
`Portfolio`; the letter must never invent a project, metric, or credential.

## Why this matters (hard constraint, not a nicety)
A recommendation letter is a prime place to overclaim ("single-handedly scaled to
millions", "led a team of 20"). This product's whole value is that it *can't*. So:
- The letter is composed **only** from the grounded `Portfolio` (built by reusing
  `portfolio.pipeline` — extract → narrate → ground). The model that writes the
  letter prose receives ONLY the grounded claims + their evidence as source
  material; it may phrase and connect them, but it may NOT introduce a factual
  accomplishment, metric, employer, title, or date that is not in that grounded
  set.
- **Grounding is re-enforced on the letter's own output.** Whatever the letter
  cites as evidence must be a ref that exists in the `Portfolio`'s evidence set;
  a sentence that cites a ref not in the evidence (a hallucinated ref) is dropped
  / the letter fails closed — never shipped. Reuse the existing grounding gate
  (`portfolio.grounding` / `resume.select.enforce_grounding` pattern); do not ask
  a model "is this true".

## What to build
Mirror the `resume` command shape (task-007): a sibling `python -m reference_check`
entrypoint + a `/reference-check` slash command. Do NOT modify `portfolio/`
internals or `resume/select.py`.

1. `python -m reference_check` CLI (`reference_check/__main__.py` + `reference_check/cli.py`):
   `python -m reference_check --source-type {github|web} --source <URL> --author <handle> [--out FILE]`.
   It builds a grounded `Portfolio` by reusing `portfolio.pipeline` (the model
   call stays the existing injectable `runner`), composes the recommendation
   letter from the grounded claims, applies the grounding re-check, and prints the
   letter Markdown to stdout (or `--out`), with a one-line grounding summary on
   stderr — mirroring `portfolio.cli` / `resume.cli` behavior.
2. The letter composition layer (`reference_check/letter.py`): turns the grounded
   `Portfolio` into a structured recommendation letter. **Recommended contract
   (planner to confirm):** the model is asked to return STRUCTURED output — an
   ordered list of letter paragraphs, each carrying the `evidence_refs` it draws
   on — so the grounding gate can verify each paragraph's refs ⊆ the portfolio's
   evidence and drop any paragraph citing a non-existent ref (fail closed). The
   fixed letter framing (salutation, "I am pleased to recommend …", closing) is
   deterministic boilerplate, not model-invented fact. The model call is the same
   injectable `runner` seam so tests run with no live CLI/network.
3. A deterministic letter renderer (`reference_check/render.py`, reusing
   `portfolio.render._escape`): structured letter → Markdown, with the cited
   evidence refs visible (the grounding trace is preserved in the output).
4. A `/reference-check` slash command (`.claude/commands/reference-check.md`)
   modeled on `.claude/commands/portfolio.md` / `resume.md`: collect source type +
   URL + author (+ optional `--out`), run `python -m reference_check ...` with each
   user value as a separate argv token (never shell-assembled), show the letter +
   grounding summary. Include a hard-rule clause forbidding shell string assembly.
5. README note: document `/reference-check` as a new public command bound by the
   grounding contract.

## Constraints / hard rules (see project-context + security-checklist)
- **No invented facts.** The letter may only state accomplishments backed by the
  grounded claims/evidence. The model gets grounded material as its ONLY source;
  the grounding gate re-checks the output. Anything ungrounded is dropped, never
  shipped.
- **No subjective metrics/percentiles.** This is a letter, not a rating: do NOT
  emit invented numbers, rankings, "top X%", or comparative superlatives that
  aren't grounded. (Soft recommender framing language is fine; fabricated metrics
  are not.)
- **Model output is untrusted.** Parse the model's structured output defensively
  (malformed/partial → drop that piece, never fabricate). The grounding gate is
  the guard, not the model's honesty.
- Do NOT modify `resume/select.py` or `portfolio/` internals
  (`extract`/`narrative`/`grounding`/`pipeline`/`model`/`render`/`cli`/`sources`/`web`).
  Import and reuse them.
- **No shell string-building.** All `gh`/`claude` calls and the slash command's
  `python -m reference_check` invocation use argv lists; never interpolate
  untrusted text (URL, author) into a command string.
- Stdlib-only engine; no new runtime dependency.

## Out of scope
- A `fit` (% match) or `rating` (rank/percentile) feature — separate later tasks.
- Multiple recommender personas / tone selection; cover letters; PDF/HTML output.
- Live source for a named referee or real third-party endorsement.
- Modifying `resume`/`portfolio` internals.

## Affected files
- `(new) reference_check/__init__.py`
- `(new) reference_check/__main__.py` — `python -m reference_check` entrypoint
- `(new) reference_check/cli.py` — argparse + pipeline → letter → render wiring (injectable extractor/runner/fetcher seams)
- `(new) reference_check/letter.py` — grounded `Portfolio` → structured letter + grounding re-check
- `(new) reference_check/render.py` — structured letter → Markdown (reuse `portfolio.render._escape`)
- `(new) .claude/commands/reference-check.md` — `/reference-check` slash command
- `(new) tests/test_reference_check.py` — wiring + grounding tests (inject extractor/runner/fetcher; no live services)
- `README.md` — document `/reference-check`

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (build `Portfolio`/`Claim`/`Evidence` directly + inject the seams — no
`gh`/`claude`/network) must cover: an end-to-end run renders a letter whose body
contains only grounded claim content for the author; a model letter-paragraph
that cites an evidence ref NOT in the portfolio is dropped and never appears in
stdout/`--out` (grounding re-check honored); cited refs stay visible in the
output (grounding trace); `--out` writes the file and stdout stays clean; the
grounding summary is on stderr, not in the letter; a bad/unsupported `--source`
exits non-zero without invoking the extractor; an injected runner returning
malformed/partial output yields a clean non-zero exit or a fail-closed empty
letter (no traceback, no fabricated paragraph); a zero-grounded-claims case
renders a deterministic "insufficient grounded evidence" notice, never a
fabricated letter; `.claude/commands/reference-check.md` passes user values as
separate argv tokens and forbids shell string assembly.

## Risks
- **Structured vs free-prose letter.** Free prose is hard to grounding-check; the
  recommended contract makes the model emit paragraphs tagged with evidence_refs
  so the existing gate applies. The planner should confirm this (vs. a stricter
  fully-deterministic template, or a looser free-prose pass) at the gate.
- **Boilerplate framing.** Salutation/closing are fixed, non-factual text; confirm
  they carry no invented specifics (no fake referee name, company, or date).
- **`verify.sh` does not lint the new package** (ruff runs over `portfolio/ tests/`
  only) — same situation as `resume/`; out of scope to widen here.
- **Letter subject/recommender identity.** Following `/portfolio` convention the
  subject is the `--author` value; the recommender is a generic/unnamed referee
  (no fabricated identity). Confirm at the gate.
