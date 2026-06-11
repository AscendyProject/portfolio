# Outcome — render a grounded Portfolio to Markdown

## Goal
Add a deterministic, stdlib-only `portfolio/render.py` exposing
`render_markdown(portfolio: Portfolio) -> str` that turns a grounded `Portfolio`
(subject + evidence + already-grounded claims) into a human-readable Markdown
document in which every rendered claim visibly shows its grounding (cited
evidence refs, evidence URL when present, and the claim's confidence), while
Markdown-significant characters in interpolated text are escaped so a hostile
PR/repo title cannot corrupt the document structure.

## Done-when
- [ ] `portfolio/render.py` exists and defines `render_markdown(portfolio: Portfolio) -> str` (importable as `from portfolio.render import render_markdown`).
- [ ] `render_markdown` uses only the Python standard library — no new runtime dependency is added to `pyproject.toml`, and the module's `import` statements reference only stdlib modules and `portfolio.*` (specifically `portfolio.model`).
- [ ] `render_markdown` never calls a model, never invokes `subprocess` / `os.system` / `gh` / `claude` / `codex`, never opens a network socket, and never writes to disk — the module contains no `subprocess`, `socket`, `urllib`, `http`, `requests`, `open(`, or `Path(...).write` references; verified by inspection and by the test suite passing without network/process side effects.
- [ ] The returned string starts with a top-level Markdown heading that includes the portfolio's `subject` (e.g. `# Portfolio — <subject>`), with the subject text escaped.
- [ ] For every claim in `portfolio.claims` (and ONLY those — `render_markdown` does not re-run grounding and does not consult any "rejected"/external claim list), the output contains a section showing: (a) the claim text, (b) each cited evidence ref from `claim.evidence_refs`, (c) the corresponding `Evidence.url` when the looked-up `Evidence` has a non-empty `url`, (d) the claim's `confidence` value.
- [ ] Each cited ref is resolved by lookup against `portfolio.evidence` (matching `Evidence.ref`); the renderer never invents a URL or detail and never emits a URL for a ref absent from `portfolio.evidence`.
- [ ] When `portfolio.claims` is empty, `render_markdown` returns a document containing a clear "no grounded claims" notice (a literal, human-readable phrase such as `no grounded claims`) instead of an empty or claim-less-but-misleading document; the subject heading is still present.
- [ ] Markdown-significant characters appearing in interpolated text (subject, claim text, evidence ref, evidence url, evidence detail) are escaped so that a hostile value containing characters such as `` ` ``, `[`, `]`, `\`, `*`, `_`, `#`, `<`, `>`, and embedded newlines cannot introduce new Markdown headings, links, code spans, or break the per-claim section structure. Escaping is implemented in stdlib code (no Markdown library).
- [ ] A new pytest module at `tests/test_render.py` exercises the behaviors above by constructing `Portfolio` / `Evidence` / `Claim` instances directly (no live `gh`, no live model runner), and `bash .redteam/scripts/verify.sh` passes end-to-end (ruff check + ruff format check + pytest including the new tests).

## Out of scope
- Any change to `portfolio/extract.py`, `portfolio/narrative.py`, `portfolio/grounding.py`, `portfolio/pipeline.py`, or `portfolio/model.py`.
- HTML output, styling, themes, or alternative output formats.
- Writing the rendered string to a file or stdout — `render_markdown` returns the string and a caller decides where it goes.
- A `/resume` harness or any CLI wiring.
- Re-running or weakening the grounding gate inside the renderer (the renderer trusts that `portfolio.claims` is already the grounded set).
- Rendering `rejected` or `needs_confirmation` claims from `GroundingResult` (these are not on `portfolio.claims`).
- Adding a runtime dependency on a Markdown library.

## Affected files
- `(new) portfolio/render.py` — new deterministic, stdlib-only render layer exposing `render_markdown(portfolio: Portfolio) -> str`.
- `(new) tests/test_render.py` — pytest module covering the render behaviors described under Done-when; lives at the project test location and follows the existing `tests/test_*.py` pattern.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Existing (must continue to pass)
- `bash .redteam/scripts/verify.sh` — runs `ruff check portfolio/ tests/`, `ruff format --check portfolio/ tests/`, and `pytest tests -x --tb=short`; full suite must pass with the new module and tests in place.
- `pytest tests/test_grounding.py tests/test_extract.py tests/test_narrative.py -x --tb=short` — the existing three layers' tests must still pass unchanged (renderer must not perturb them).

### To be created (test-author will define exact test names)
- A new pytest module at `tests/test_render.py` that builds `Portfolio` / `Evidence` / `Claim` dataclass instances directly (no live `gh`, no live `claude` / `codex` runner) and asserts the renderer's behavior, covering:
  - A portfolio with one or more grounded claims renders the subject heading, each claim's text, each claim's cited evidence refs, the evidence URL when present on the looked-up `Evidence`, and the claim's confidence.
  - A claim citing a ref that resolves to an `Evidence` record whose `url` is empty does not emit a fabricated URL.
  - An empty `portfolio.claims` produces output containing a clear "no grounded claims" notice and still includes the subject heading.
  - Markdown-significant characters (at minimum `` ` ``, `[`, `]`, `\`, `*`, `_`, `#`, `<`, `>`, and embedded `\n`) appearing in subject / claim text / evidence ref / evidence url / evidence detail are escaped such that they do not introduce new headings, links, code spans, or break the per-claim section boundary.
  - The renderer is a pure function: calling it twice on the same `Portfolio` returns identical strings, and it does not mutate the input `Portfolio`, `Claim`, or `Evidence` objects.

## Risks
- The exact Markdown shape (heading levels per claim, bullet vs. list layout, label text such as `Confidence:` / `Evidence:`) is not pinned by the brief; the test-author and implementer must agree on a concrete shape that satisfies the Done-when behaviors without over-specifying cosmetic formatting.
- The escaping strategy is a small design choice (backslash-escape a fixed set of Markdown-significant characters vs. wrapping interpolated text in a safer construct); the brief mandates "simple, well-tested" — the implementer picks one and the tests pin it.
- The exact wording of the "no grounded claims" notice is not specified; pick a stable phrase (e.g. `no grounded claims`) and have the test assert on a substring.
- Confidence display format (raw float vs. percentage vs. fixed decimals) is unspecified; pick a deterministic representation and pin it in the test, but do not introduce locale-dependent formatting.
- The brief shows an em-dash example (`# Portfolio — <subject>`); ensure the source file's encoding declaration / repo defaults handle non-ASCII heading punctuation, or fall back to an ASCII separator — either is acceptable as long as `ruff format --check` passes.
