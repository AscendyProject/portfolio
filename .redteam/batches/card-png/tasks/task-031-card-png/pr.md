## What
`python -m rating --out-card <path>.png` writes a real PNG (rasterized from the
existing SVG) gated behind a new optional `card` extra whose dependency
(`cairosvg`) is lazy-imported, leaving the core install dependency-free and the
`.svg` / `--share` paths byte-identical to task-030.

## Why
task-030 ships an SVG capability card that works for the README badge but cannot
be attached to a LinkedIn/X post — those surfaces don't render uploaded SVG. The
"thing you attach" is a PNG. Rather than introducing a second renderer, this
rasterizes the SVG we already produce, keeping one source of truth; gating the
`cairosvg` dependency behind an optional extra preserves the zero-dependency
core install promise.

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

## Verification
- Tests: `test_out_card_png_calls_rasterizer_and_writes_bytes`, `test_out_card_svg_does_not_call_rasterizer`, `test_out_card_svg_byte_identical_to_render_card`, `test_out_card_png_missing_extra_nonzero_exit`, `test_out_card_png_missing_extra_hint_in_stderr`, `test_out_card_png_missing_extra_no_file_created`, `test_out_card_png_oserror_nonzero_exit`, `test_out_card_png_oserror_clean_stderr`, `test_svg_to_png_raises_card_extra_missing_when_cairosvg_absent`, `test_svg_to_png_card_extra_missing_is_exception_subclass`, `test_svg_to_png_real_png_signature`, `test_pyproject_card_extra_present_and_no_runtime_deps`, `test_run_rasterizer_param_default_is_svg_to_png`
- Verify command: `bash .redteam/scripts/verify.sh` ✅

## Code review summary
- Diff: optional `card` extra in `pyproject.toml`; new `CardExtraMissingError` + lazy `svg_to_png` in `portfolio/card.py`; `--out-card` extension routing + injectable `rasterizer=svg_to_png` seam in `rating/cli.py`; new tests in `tests/test_card.py`; README/CHANGELOG callouts updated.
- IR-001 resolved: `grounding_summary` is deferred until after the `--out-card` write succeeds, so `CardExtraMissingError` and PNG-write `OSError` paths emit exactly one clean stderr line with no preprinted grounding summary.
- IR-002 resolved: the SVG-parity test now spies on `render_card(...)` and asserts `written == captured_svgs[0]`, enforcing the byte-identity contract for non-`.png` `--out-card` output (and failing pre-change because `run()` lacked the `rasterizer` seam).
- Verification: `verification.log` records `bash .redteam/scripts/verify.sh` exit 0 with 918 passed and 2 skipped (`state.verification.last_exit_code == 0`).
- Security checklist: no HIGH findings — no grounding-gate changes, no new shell construction, no secret logging, `cairosvg` is optional/lazy, and the `--share` `extra_files` payload remains SVG-only.
- REVIEW_DECISION: APPROVED.

## Generated by
redteam / batch card-png / task task-031-card-png
