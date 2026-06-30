+++
mode = "agent-pair"
+++

# Task: `rating --out-card` PNG output via an optional `card` extra

## Goal
Make the capability card postable on social (LinkedIn/X don't render uploaded SVG).
Let `--out-card` write a **PNG** by rasterizing the existing SVG, behind an **optional
`card` extra** (lazy-imported, exactly like the existing `pdf` extra) so the core install
stays dependency-free. The default SVG path and the `--share` gist path are unchanged.

## Why
task-030 ships an SVG card: perfect for a README badge, but SVG can't be attached to a
LinkedIn/X post. A PNG is the "thing you attach". Rasterizing the SVG we already produce
(rather than a second renderer) keeps one source of truth, and gating the rasterizer
dependency behind an extra keeps the zero-dependency core promise.

## Part A — optional `card` extra (`pyproject.toml`)
- Add `[project.optional-dependencies] card = ["cairosvg"]` (mirrors the existing `pdf`
  extra). The core `[project.dependencies]` stays empty — `cairosvg` is NOT a runtime
  dependency of the core install.

## Part B — SVG→PNG rasterizer (`portfolio/card.py`)
- Add `svg_to_png(svg: str) -> bytes`: **lazily** import `cairosvg` inside the function;
  if the import fails, raise a clear `CardExtraMissingError` (new, in `portfolio/card.py`)
  whose message tells the user to `pip install 'portfolio[card]'` — mirroring how the PDF
  path errors when `pypdf` is absent. Convert the SVG string to PNG bytes via
  `cairosvg.svg2png(bytestring=...)`.
- A successful result is valid PNG bytes (starts with the `\x89PNG\r\n\x1a\n` signature).
  Do NOT assert byte-identical output across platforms (rasterization can vary); assert
  the PNG signature / non-empty bytes instead.

## Part C — `rating/cli.py` `--out-card` format routing
- Infer the output format from the `--out-card` path **extension**: `.png` → rasterize
  via the rasterizer and write **bytes**; `.svg` (or any non-`.png`) → write the SVG
  **text** (current behavior, byte-identical).
- Make the rasterizer an **injectable seam** on `run(...)` (e.g. a keyword-only
  `rasterizer=svg_to_png` parameter), so tests inject a fake and CI does not require
  `cairosvg`. The default is the real `svg_to_png`.
- When a `.png` card is requested but the `card` extra is not installed, exit non-zero
  with a single clean, actionable stderr line (the `pip install 'portfolio[card]'` hint);
  do NOT write a partial/empty file. Same clean-error + non-zero-exit contract for an
  OSError on write.
- `--share` is unchanged: the gist still carries the `.svg` (and `.md`); PNG is a local
  `--out-card` artifact only. Behavior with no `--out-card` (or an `.svg` one) is
  byte-identical to task-030.

## Hard rules
- **Core install stays dependency-free** — `card` is an OPTIONAL extra; `cairosvg` is
  lazily imported and never required unless a `.png` card is actually requested. (Assert
  via the existing "no `[project.dependencies]`" check; the new entry lives under
  `[project.optional-dependencies]`.)
- The injectable rasterizer keeps the **full test suite green WITHOUT `cairosvg`
  installed** (tests use a fake rasterizer; any test exercising real `cairosvg` is guarded
  by `pytest.importorskip("cairosvg")`).
- No change to `render_card` SVG output, the masking/banned-lexicon scrubbing, the
  `--share` gist path, or the README badge. The `.svg` `--out-card` path is byte-identical.
- Clean errors only; no secret/traceback leak; no `shell=True` anywhere new.

## Out of scope (follow-ups)
- Embedding the PNG in the gist (gists keep `.md` + `.svg`; PNG is a local attach artifact).
- PNG/cards for `resume`, `fit`, `reference_check`.
- Open Graph / hosted preview image (needs the future platform).
- A pure-Python rasterizer alternative to `cairosvg` (one extra is enough for v1).

## Affected files
- `pyproject.toml` — add the optional `card` extra (`cairosvg`); core deps unchanged.
- `portfolio/card.py` — `svg_to_png(svg) -> bytes` (lazy `cairosvg`), `CardExtraMissingError`.
- `rating/cli.py` — `--out-card` extension routing (.png → rasterize bytes, else SVG text);
  injectable `rasterizer` seam; clean actionable error when the extra is missing.
- `(extend) tests/test_card.py` — extension routing (.svg writes SVG text; .png calls the
  injected rasterizer and writes its bytes); missing-extra → non-zero exit + clean hint
  (fake import failure); PNG signature when `cairosvg` is available
  (`pytest.importorskip`); the `.svg` path and no-card path stay byte-identical.
- `README.md` / `CHANGELOG.md` — document `--out-card card.png` and the optional
  `pip install 'portfolio[card]'` extra (LinkedIn/X want PNG; README badge stays SVG).

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green WITHOUT `cairosvg` installed (rasterizer is injected/faked;
real-lib tests use `pytest.importorskip`). New tests cover Parts B–C. Core install adds no
runtime dependency — `card` is an optional extra.
