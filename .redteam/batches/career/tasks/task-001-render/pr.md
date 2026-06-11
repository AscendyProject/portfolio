## What
Add a deterministic, stdlib-only `portfolio/render.py` exposing
`render_markdown(portfolio: Portfolio) -> str` that turns a grounded `Portfolio`
(subject + evidence + already-grounded claims) into a human-readable Markdown
document in which every rendered claim visibly shows its grounding (cited
evidence refs, evidence URL when present, and the claim's confidence), while
Markdown-significant characters in interpolated text are escaped so a hostile
PR/repo title cannot corrupt the document structure.

## Why
The brief asks for the final layer of the extract → narrate → ground → **render**
pipeline: a Markdown renderer that takes an already-grounded `Portfolio` and
produces the human-readable artifact. The product's whole point is that every
rendered claim visibly shows its grounding (cited evidence refs + URL +
confidence), so the renderer must be deterministic, stdlib-only, and never
re-derive grounding. It must also escape Markdown-significant characters so a
hostile PR/repo title can't corrupt the document structure.

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

## Verification
- Tests: test_subject_heading_present, test_claim_text_rendered, test_claim_confidence_rendered, test_claim_evidence_ref_rendered, test_evidence_url_rendered_when_present, test_no_fabricated_url_when_evidence_url_empty, test_no_fabricated_url_for_ref_absent_from_evidence, test_multiple_claims_all_rendered, test_evidence_detail_rendered_when_present, test_empty_claims_contains_no_grounded_notice, test_empty_claims_still_has_subject_heading, test_escape_hostile_subject, test_escape_hostile_claim_text, test_escape_backslash_in_subject, test_escape_hostile_evidence_ref, test_escape_hostile_evidence_url, test_escape_hostile_evidence_detail, test_escape_newline_in_subject, test_idempotent, test_no_mutation_of_portfolio
- Verify command: `bash .redteam/scripts/verify.sh` ✅

## Code review summary
- Diff is scoped to the two new files declared in `outcome.md`'s Affected files: `portfolio/render.py` (82 lines) and `tests/test_render.py` (302 lines); no other source file is touched.
- `portfolio/render.py` imports only `portfolio.model` plus `__future__` annotations — no `subprocess`, `socket`, `urllib`, `http`, `requests`, `open(`, or `Path(...).write` references, satisfying the deterministic / stdlib-only Done-when items.
- Renderer iterates `portfolio.claims` only (never `rejected` / `needs_confirmation`) and resolves each `claim.evidence_refs` ref against `portfolio.evidence` via a `{ref: Evidence}` lookup, never fabricating a URL when the ref is absent or `Evidence.url` is empty.
- Escaping covers `` ` ``, `[`, `]`, `\`, `*`, `_`, `#`, `<`, `>`, plus newline-to-space normalisation, and is applied to subject, claim text, evidence ref, evidence URL, and evidence detail — verified by hostile-input tests on every interpolated field.
- Empty-claims case returns a document with the subject heading and a literal `no grounded claims` notice, as required.
- `code_review.md` final line: `REVIEW_DECISION: APPROVED`, with all three reviewer items (IR-001 / IR-002 / IR-003) marked resolved. `bash .redteam/scripts/verify.sh` reports 36 passed (20 new render tests + the three existing layers untouched).

## Generated by
redteam / batch career / task task-001-render
