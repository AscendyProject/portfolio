# portfolio — Sub-agent context

Compact reference for every sub-agent. Authoritative source is `README.md`.

## Domain
A harness that turns a developer's real GitHub work into a **grounded** portfolio:
every portfolio claim must trace to real evidence (a PR, commit, file) pulled
deterministically from `gh` — never invented by a model.

## Stack
- Python 3.11+, **stdlib only** for the engine (`subprocess`, `json`, `dataclasses`).
- External tools shelled out to: `gh` (evidence), `claude` / `codex` (narrative).
- Tests: pytest. Lint/format: ruff. No mypy gate.

## Architecture entry points (three layers — keep them separated)
- `portfolio/extract.py` — DETERMINISTIC. `gh` → `Evidence` (refs like `PR#128`,
  `app/auth.py`). A model never adds to this set.
- `portfolio/narrative.py` — LLM. Drafts `Claim`s citing ONLY extracted refs; the
  model call is an injectable `runner` (testable without a live CLI).
- `portfolio/grounding.py` — DETERMINISTIC trust gate: a claim ships only if every
  cited ref exists in the evidence set; an invented ref is a hard reject.
- `portfolio/pipeline.py` — wires extract → narrate → ground; `model.py` holds the
  `Evidence` / `Claim` / `Portfolio` dataclasses.

## Hard rules (must respect when writing code)
- **Every claim must be grounded.** Never let a code path ship a `Claim` whose
  cited ref is not in the extracted `Evidence` set. The grounding gate is the
  product's whole value — do not weaken or bypass it.
- **Deterministic vs LLM separation stays clean.** `extract` and `grounding` are
  pure/deterministic and must NOT call a model. Only `narrative` calls a model.
- **No shell string-building.** All `gh`/`claude`/`codex` calls are argv lists to
  `subprocess.run` (never `shell=True`); never interpolate untrusted text into a command.
- **Model output is untrusted input.** Parse it defensively (malformed → drop,
  never fabricate); the grounding gate is the real guard, not the model's honesty.
- **Stdlib-only engine.** No new runtime pip dependency without an explicit reason.

## Architecture boundaries
- `pipeline` calls `extract` / `narrate` / `ground`; the deterministic layers never
  call the LLM layer. Shared types live in `model.py`.
- A new public function/module that affects the grounding contract needs a README note.

## Forbidden actions (sub-agents must refuse)
- `git push --force` to main or shared branches.
- Editing `.env*`, credentials, or anything secret.
- Weakening tests / ruff to make the gate pass.
- Making the grounding check accept un-cited or hallucinated-ref claims.

## Verification
Run `bash .redteam/scripts/verify.sh` (ruff + ruff-format + pytest over
`portfolio/` + `tests/`) and report failures rather than papering over them.
