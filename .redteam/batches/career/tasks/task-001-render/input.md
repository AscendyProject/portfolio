# Task: render a grounded Portfolio to Markdown

## Goal
Add a `render` layer that turns a grounded `Portfolio` (subject + evidence +
grounded claims) into a human-readable **Markdown** portfolio document. This is
the last of the three layers (extract → narrate → ground → **render**).

## What to build
- A new module `portfolio/render.py` with a pure function:
  `render_markdown(portfolio: Portfolio) -> str`.
- The output must include:
  - a title with the subject (e.g. `# Portfolio — <subject>`),
  - one section per grounded claim showing the claim text and its cited evidence
    refs (and the evidence URL if present), so **every claim visibly shows its
    grounding** — this is the product's whole point,
  - confidence shown per claim,
  - if the portfolio has zero claims, render a clear "no grounded claims" notice
    rather than an empty/っmisleading document.
- Each claim's cited evidence refs must be looked up against
  `portfolio.evidence` so the rendered link/detail comes from the real Evidence
  record (do not invent URLs or details).
- **Escape** any claim/evidence text that could break Markdown structure (e.g. a
  PR title containing `]` `[` backticks or a newline) so a hostile repo/PR title
  cannot corrupt the output. A simple, well-tested escaping of Markdown-significant
  characters in interpolated text is enough.

## Constraints / hard rules (see project-context + security-checklist)
- `render.py` is DETERMINISTIC and pure — it must NOT call a model, `gh`, or any
  network/subprocess. It only formats data already on the `Portfolio`.
- Only render claims that are on `portfolio.claims` (these are already the grounded
  ones from the pipeline). Do not re-derive grounding here; do not render rejected
  claims.
- Stdlib only.

## Out of scope
- The `/resume` harness, HTML output, styling/themes, file writing (return the
  string; a caller decides where it goes).
- Changing extract / narrate / grounding / pipeline behavior.

## Affected files
- `(new) portfolio/render.py`
- `(new) tests/test_render.py`

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests should cover: a portfolio with grounded claims renders subject + each claim
+ its evidence refs + confidence; an empty portfolio renders the "no grounded
claims" notice; a claim/evidence text with Markdown-significant characters is
escaped so the structure is intact. Build `Portfolio`/`Evidence`/`Claim` objects
directly (no live services), per test-conventions.

## Risks
- Escaping approach is a small design choice — keep it simple and tested, don't
  pull in a Markdown library (stdlib only).
