# Task: richer web body extraction — give the model article text, not just the title

## Goal
The web source (task-004) currently turns an article into `Evidence` carrying
only the `<title>`. That is thin material for the narrative model. Extract a clean
**body excerpt** from the article and feed it to the model as grounding context —
*without* polluting the rendered portfolio (the excerpt is context for narration,
not output).

## What to build
- Add a `context: str = ""` field to `Evidence` (`portfolio/model.py`) — longer
  free text a model may use to write claims about that evidence. It is **fed to
  the narrative prompt but NOT rendered** (render shows `ref`/`url`/`detail`
  only). Defaulting to `""` keeps every existing `Evidence` construction valid.
- In `portfolio/web.py`, extract a body excerpt alongside the title:
  - Parse visible text from the HTML with the stdlib `html.parser`, **skipping
    `<script>` / `<style>` / `<noscript>` / `<template>` content** and the
    `<title>` (captured separately).
  - Collapse runs of whitespace to single spaces; trim.
  - Truncate to a bounded length (a module constant, e.g. ~1500 chars) with a
    clear truncation marker, so the prompt stays bounded.
  - `extract_article_evidence` sets `detail=<title>` (unchanged) and
    `context=<body excerpt>`.
- In `portfolio/narrative.py`, `build_prompt` includes an evidence item's
  `context` (clearly labeled, e.g. an `excerpt:` line) when present, so the model
  can ground claims in the article's actual text. Items without context render in
  the prompt exactly as before.

## Constraints / hard rules (see project-context + security-checklist)
- Grounding unchanged: `context` is narration material only. A claim must still
  cite a real `ref`; the grounding gate is unchanged and still drops un-grounded
  claims. `context` is NEVER treated as a citable ref.
- `context` must NOT appear in rendered output — `render.py` stays untouched and
  keeps showing only `ref`/`url`/`detail`.
- The body excerpt is bounded (truncated) so a huge page can't blow up the prompt.
- Pure extraction: `extract_article_evidence` stays a pure function (no network);
  the fetch remains the only network call, behind the injectable seam.
- stdlib only; don't change extract / grounding / render behaviour; the github
  path is untouched.

## Out of scope
- Readability-style main-content detection (boilerplate/nav/footer stripping
  beyond skipping script/style). A first clean excerpt is enough.
- Multiple Evidence per article, summarization, or language detection.
- Changing how claims are grounded or rendered.

## Affected files
- `(modified) portfolio/model.py` — add `context: str = ""` to `Evidence`
- `(modified) portfolio/web.py` — body excerpt extraction
- `(modified) portfolio/narrative.py` — include `context` in the prompt
- `(modified) tests/test_web.py`, `tests/test_narrative.py` (+ adjust any
  `Evidence`-equality assertions affected by the new field)

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (pure; no network):
- body excerpt includes visible text and EXCLUDES `<script>`/`<style>` contents;
  whitespace is collapsed; a long body is truncated to the bound (with marker).
- `extract_article_evidence` sets `detail` from `<title>` and `context` from the
  body; a title-only document yields empty `context`.
- `build_prompt` includes an evidence item's `context` when present, and is
  unchanged for items without it.
- render still shows only `ref`/`url`/`detail` — `context` does not leak into the
  Markdown (assert a sentinel context string is absent from the rendered output).
- existing grounding safety still holds (an invented ref never reaches the
  portfolio).

## Risks
- Adding a field to the frozen `Evidence` dataclass can break `Evidence(...)`
  equality assertions in tests — update them in the same change.
- Prompt bloat / injection feel: keep the excerpt bounded and clearly labeled as
  context, never as a citable ref, so the model isn't nudged to cite the excerpt
  text itself.
