# Outcome — `rating --out-card` PNG via optional `card` extra

## Goal
`python -m rating --out-card <path>.png` writes a real PNG (rasterized from the
existing SVG) gated behind a new optional `card` extra whose dependency
(`cairosvg`) is lazy-imported, leaving the core install dependency-free and the
`.svg` / `--share` paths byte-identical to task-030.

## Done-when
- [ ] `bash .redteam/scripts/verify.sh` exits 0 in a clean checkout that has NOT
      installed `cairosvg` (the full suite is green without the extra installed).
- [ ] `pyproject.toml` defines `[project.optional-dependencies] card = ["cairosvg"]`,
      and no top-level `[project.dependencies]` key is added — verifiable by
      `python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));
      assert d['project'].get('dependencies', []) == [];
      assert d['project']['optional-dependencies']['card'] == ['cairosvg']"`.
- [ ] `portfolio/card.py` exports `svg_to_png(svg: str) -> bytes` and
      `CardExtraMissingError` (subclass of `Exception`); `import portfolio.card`
      succeeds with `cairosvg` ABSENT (no top-level `import cairosvg`).
- [ ] When `cairosvg` is absent, `svg_to_png("<svg/>")` raises
      `CardExtraMissingError` whose `str(exc)` contains the literal substring
      `pip install 'portfolio[card]'` (mirrors the `pypdf`/`portfolio[pdf]` hint
      at `portfolio/jd_source.py:116`).
- [ ] `rating.cli.run()` accepts a keyword-only `rasterizer` parameter that
      defaults to `portfolio.card.svg_to_png`; verifiable via
      `inspect.signature(rating.cli.run).parameters['rasterizer'].default is
      portfolio.card.svg_to_png`.
- [ ] `--out-card card.png` (no `--share`) calls the injected rasterizer exactly
      once with the rendered SVG string and writes the returned bytes verbatim
      (binary write, not text) to the file; exit code 0.
- [ ] `--out-card card.svg` (and any non-`.png` suffix) continues to write the
      SVG text and is byte-identical to the file task-030 would have written for
      the same inputs (no rasterizer call). Asserted by a test that compares the
      `.svg` output against `render_card(...)` directly.
- [ ] `--out-card card.png` when the (injected) rasterizer raises
      `CardExtraMissingError`: exit code is non-zero, stderr contains one clean
      line including `pip install 'portfolio[card]'`, no traceback is emitted,
      and the target path is NOT created (no partial/empty file left behind).
- [ ] `--out-card card.png` when writing the PNG fails with `OSError`: exit code
      is non-zero, stderr contains one clean line referencing the card path or
      `out-card`, no traceback. (Mirrors the existing `.svg` OSError tests at
      `tests/test_card.py:373` and `tests/test_card.py:386`.)
- [ ] `--share` path is unchanged: `extra_files` still contains exactly one
      `.svg` entry and zero `.md`/`.png` entries; badge snippet still prints the
      gist raw `.svg` URL. Existing tests
      `test_share_extra_files_has_svg_entry`, `test_share_badge_snippet_in_stdout`,
      `test_share_badge_uses_gist_raw_url`, `test_share_badge_after_social_links`
      still pass without modification.
- [ ] One test guarded by `pytest.importorskip("cairosvg")` calls the real
      `svg_to_png` on `render_card(...)` output and asserts the result starts
      with the PNG signature `b"\x89PNG\r\n\x1a\n"` and is non-empty. No
      byte-identity assertion across platforms.
- [ ] `README.md` documents `--out-card card.png` and the
      `pip install 'portfolio[card]'` extra (replaces the existing "PNG
      rasterization is planned" callout at `README.md:289`).
- [ ] `CHANGELOG.md` gains an `[Unreleased]` entry describing the optional `card`
      extra and the `.png` routing.

## Out of scope
- PNG output for `resume`, `fit`, `reference_check` (this task is `rating` only).
- Embedding the PNG in the gist's `extra_files` (gists keep `.md` + `.svg`; PNG
  is a local artifact written from `--out-card` only).
- Replacing or modifying `render_card`, the masking/banned-lexicon scrubbing, or
  the README badge URL (still SVG).
- Adding a pure-Python rasterizer fallback (one extra suffices for v1).
- Open Graph / hosted preview image (depends on a future hosted platform).
- Any change to `[project.dependencies]` — the core install stays dependency-free.

## Affected files
- `pyproject.toml` — add `card = ["cairosvg"]` under
  `[project.optional-dependencies]`; touch nothing else.
- `portfolio/card.py` — add `CardExtraMissingError` and `svg_to_png(svg: str)
  -> bytes` with a lazy `import cairosvg` inside the function; do not modify
  `render_card` or any existing helper.
- `rating/cli.py` — add a keyword-only `rasterizer=svg_to_png` parameter on
  `run(...)`, branch the `--out-card` write on the path's `.png` suffix, handle
  the missing-extra and `OSError` paths with single clean stderr lines and
  non-zero exit, and ensure no partial file is left on failure. The `--share`
  block stays SVG-only.
- `(extend) tests/test_card.py` — add tests for extension routing (`.png`
  invokes the injected rasterizer and writes its bytes; `.svg` is unchanged),
  the missing-extra failure path (fake rasterizer raises
  `CardExtraMissingError` → non-zero + clean hint, no file written), the
  `OSError`-on-PNG-write path, and the real-`cairosvg` PNG-signature check
  guarded by `pytest.importorskip("cairosvg")`. Existing tests stay green
  unchanged.
- `README.md` — replace the "PNG rasterization is planned" callout at
  `README.md:289` with the shipped behavior; document the `card` extra.
- `CHANGELOG.md` — add an `[Unreleased]` bullet under `### Added` for the PNG
  routing and the `card` extra.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Existing (must continue to pass)
- `bash .redteam/scripts/verify.sh` — full suite (ruff check, ruff format check,
  pytest over `tests/`); must pass with `cairosvg` NOT installed.
- `pytest -x tests/test_card.py` — every existing test in this file
  (`test_render_card_*`, `test_out_card_*`, `test_share_*`, `test_gist_*`)
  remains green without source modification.
- `pytest -x tests/test_version.py` — pyproject parse still works after the
  optional-deps edit.

### To be created (test-author will define exact test names)
- New tests in `tests/test_card.py` covering, all without requiring `cairosvg`
  installed (use an injected fake rasterizer except where noted):
  - `.png` extension on `--out-card` invokes the injected rasterizer with the
    rendered SVG string and writes the returned bytes verbatim (binary).
  - `.svg` extension on `--out-card` does NOT invoke the rasterizer and writes
    bytes identical to `render_card(...)` for the same inputs (task-030
    parity).
  - Missing-extra path: fake rasterizer raises `CardExtraMissingError` → exit
    code non-zero; stderr has one clean line containing
    `pip install 'portfolio[card]'`; no `Traceback`; target file is not
    created.
  - OSError on `.png` write: exit code non-zero; stderr clean; no traceback.
  - `svg_to_png` raises `CardExtraMissingError` with the install-hint substring
    when `cairosvg` is absent (simulated by patching the lazy import to raise
    `ImportError`).
  - Real-rasterizer happy path guarded by `pytest.importorskip("cairosvg")`:
    `svg_to_png(render_card(...))` returns non-empty bytes starting with
    `b"\x89PNG\r\n\x1a\n"`.
  - `pyproject.toml` shape check: `card` extra present with `cairosvg`; no
    runtime `[project.dependencies]` key (or it is an empty list).

## Risks
- The brief mandates a "single clean stderr line" on the missing-extra path but
  the existing `--out-card` OSError tests only assert "at least one error
  line" (`tests/test_card.py:386`). The implementer should follow the brief's
  stricter contract (exactly one non-empty stderr line for the missing-extra
  case) — if the human disagrees, surface here before coding.
- `cairosvg` pulls native deps (Cairo, Pango, libffi) on some platforms; CI
  must still pass without `cairosvg` installed (the injected fake covers this).
  Documenting the system-level install for end users is out of scope for this
  task but may need a README note in a follow-up.
- The brief says "do NOT write a partial/empty file" on the missing-extra path.
  This requires routing: render SVG → call rasterizer → only on success
  `Path(...).write_bytes(...)`. The implementer must NOT open the file before
  the rasterizer call.
- Whether the `--share` + `--out-card foo.png` combination should also gate on
  the extra (rasterizing the local PNG while still publishing the SVG to the
  gist) is implied but not explicit. Reading the brief literally: yes, the
  local `.png` write must rasterize and therefore needs the extra; the gist
  itself remains SVG. The implementer should treat the local `.png` write the
  same way regardless of `--share`. Flagging in case the human wants a
  different shape.
