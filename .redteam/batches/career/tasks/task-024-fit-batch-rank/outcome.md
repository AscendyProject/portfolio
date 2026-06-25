# Outcome — fit batch scoring + ranked output (`--jd-dir`)

## Goal
`python -m fit` accepts `--jd-dir <dir>` to score one built portfolio against every
JD file in a directory and emits a deterministic, language-aware ranked table
(best-first), while the existing `--jd <path>` single-JD code path stays
byte-identical (stdout AND stderr) to the base-branch implementation.

## Done-when
- [ ] `python -m fit --source-type … --source … --author … --jd-dir <dir>` runs end-to-end and exits 0 when at least one `*.txt` or `*.md` file under `<dir>` is scored.
- [ ] `--jd-dir` scans `<dir>` non-recursively (top-level only), accepts ONLY files whose suffix is `.txt` or `.md` (case-sensitive match against the literal lowercase suffixes `.txt` and `.md`), and ignores all other entries (including subdirectories). The list of JDs is sorted by basename (Python default `sorted()`) before scoring.
- [ ] When neither `--jd` nor `--jd-dir` is supplied: the CLI exits with code 2 and prints exactly ONE line to stderr naming both options as mutually exclusive and required.
- [ ] When both `--jd` and `--jd-dir` are supplied: the CLI exits with code 2 and prints exactly ONE line to stderr naming both options as mutually exclusive.
- [ ] When `--jd-dir` resolves to zero matching files (empty dir, dir-of-only-other-extensions, or a non-existent dir): the CLI exits with code 2 and prints exactly ONE line to stderr that names `--jd-dir <path>` and the reason (no matching JDs). It does NOT raise an uncaught exception.
- [ ] The portfolio is built exactly ONCE per `--jd-dir` invocation: in a test, an injected counting `extractor` is called exactly once when N JDs are scored (N ≥ 2). Likewise the injected `runner` (narrative model) is called the same number of times it would be for a single `--jd` invocation, regardless of N.
- [ ] `score_fit` is invoked once per matching JD file (asserted by counting calls through a wrapper in a test); the `Portfolio` object passed to it is the SAME in-memory instance (`is`-identical) across all calls.
- [ ] In batch mode the CLI emits a Markdown ranked table to stdout (or to `--out <file>` when supplied) with exactly these columns in this order: `JD`, `Grade`, `Score`, `Coverage%`, `Top Gaps`. Header text comes from new `portfolio.i18n.LANGS[lang]` keys (no hardcoded English header text in `fit/render.py` or `fit/cli.py` for these labels).
- [ ] Table rows are sorted: primary key Score descending, secondary key Coverage% descending, tertiary key JD basename ascending. A test with hand-crafted ScoreResults exercises all three tiers of the tiebreak.
- [ ] The `JD` column contains the JD's basename (filename including extension), not its full path.
- [ ] The `Grade` column contains the deterministic `score_result.grade` (one of S/A/B/C/D) from `score_fit`.
- [ ] The `Score` column contains a deterministic integer derived from `score_result.band` as the band midpoint `(min + max) // 2` (matching `bounded_grade`'s midpoint convention). `bounded_grade` is NOT called in batch mode.
- [ ] The `Coverage%` column contains `score_result.coverage_pct` rendered as an integer percent (`{:.0f}%`), matching the existing `render_fit` format.
- [ ] The `Top Gaps` column contains the first 5 elements of `sorted(score_result.gaps)` (alphabetical, deterministic), joined by `, `; if a JD has zero gaps the cell shows the localized `none_notice` string from `LANGS[lang]`.
- [ ] **Table-cell escaping (PR-002).** A NEW cell-level escaper helper is added in `fit/render.py` (e.g. `_escape_cell`) and is applied to every value rendered inside a `|`-delimited cell in the ranked table — at minimum the `JD`, `Top Gaps`, and any other data column. The cell escaper must neutralize ALL of: `|` (backslash-escaped as `\|`), `\n` and `\r` (each replaced with a single space; consecutive whitespace from this collapse is acceptable as long as no row spans multiple output lines), AND the Markdown-significant characters already covered by `portfolio.render._escape` (`` ` [ ] \ * _ # < > ``). The cell escaper MAY call `portfolio.render._escape` internally for those existing specials, then layer the `|`/newline handling on top — but it MUST NOT modify `portfolio.render._escape` or `portfolio.render._ESCAPE_CHARS`.
- [ ] **Global escaper is untouched (PR-004).** `portfolio/render.py` is UNCHANGED by this task: `git diff` against the base branch shows no edits to `portfolio/render.py` (in particular `_ESCAPE_CHARS` and `_escape` remain byte-identical). This is a hard guard against silently altering single-`--jd` and `render_portfolio` output that may contain `|` characters in claim text, evidence detail, URLs, or refs.
- [ ] **Table-cell escaping is tested.** A test feeds the renderer a JD basename containing a literal `|` and a JD basename containing a literal `\n` (real newline, not the two characters `\\n`) and asserts: (a) the rendered table still has exactly one row per JD, (b) no unescaped `|` appears inside any data cell, (c) no row spans more than one line of output, (d) the offending characters are encoded according to the rule above. A second assertion exercises a `Top Gaps` token containing a literal `|` (deterministic gap strings can include pipes if a JD does) and confirms it is escaped identically.
- [ ] **Language default in batch mode (PR-001).** When `--jd-dir` is used and `--lang` is OMITTED, the table language is `en`. There is no auto-detection from JD contents in batch mode. An explicit `--lang ko` (or `--lang en`) overrides this default. A test runs `--jd-dir` against a directory of Korean-text JDs without `--lang`, asserts the rendered headers are the English `LANGS["en"]` table-header strings, and asserts the Korean header strings from `LANGS["ko"]` do NOT appear in stdout.
- [ ] **Single-JD `--lang` behavior is unchanged.** When `--jd <path>` is used and `--lang` is omitted, `detect_language(jd_text)` still chooses the language exactly as today. A test runs `--jd <path>` against a Hangul-dominant JD without `--lang` and asserts the output is rendered in `ko` (i.e. the existing auto-detect path is intact).
- [ ] Determinism: running `--jd-dir` twice with the same `(portfolio source inputs, JD set, --lang)` produces byte-identical stdout. A test asserts this by running the CLI twice in-process and comparing captured stdout.
- [ ] **Single-JD byte-identity golden (PR-003).** A golden file pair captured from the BASE branch (pre-change) implementation is checked in at `tests/golden/fit_single_jd/stdout.md` and `tests/golden/fit_single_jd/stderr.txt`. A test in the new test module runs `fit.cli.run(...)` on the same `--jd <path>` argv that produced the golden (with the same injected `extractor`, `runner`, `fetcher`, and `grader_runner` fakes already used in `tests/test_fit.py`) and asserts `captured.out == golden_stdout` AND `captured.err == golden_stderr`, byte-for-byte. The test-author captures the golden by running the CLI on the base branch BEFORE applying the implementation diff; the implementer must NOT regenerate the golden.
- [ ] `--lang ko` localizes the ranked-table column headers and the "none" cell text. A test renders the ko ranked table and asserts none of the new `LANGS["en"]` UI strings for the table appear verbatim in the stdout (extending the existing structural English-leak test pattern in `tests/test_i18n.py`).
- [ ] New i18n keys for the ranked table are present in BOTH `LANGS["en"]` and `LANGS["ko"]` with non-empty values; the existing `tests/test_i18n.py` completeness tests (every key in `LANGS["en"]` is in `LANGS["ko"]`; no empty values) pass without modification.
- [ ] `score_fit` and `fit/grade.py` (the rubric, `COVERAGE_CUTOFFS`, `GRADE_BANDS`, and the score math) are UNCHANGED — `git diff` against the base branch shows no edits to `fit/score.py` or `fit/grade.py`.
- [ ] The grounding gate is unchanged: `--jd-dir` performs grounding exactly once (during the single portfolio build) and never persists JD text as `Evidence`. A test inspects the in-memory `Portfolio` after a `--jd-dir` run and asserts no JD basename and no substring of any JD body appears in any `Evidence.ref` or `Evidence.detail`.
- [ ] The stderr grounding summary line (`grounded: N  rejected: N  needs-confirmation: N`) is printed exactly ONCE per `--jd-dir` invocation, identical in format to single-`--jd` mode.
- [ ] `bash .redteam/scripts/verify.sh` passes (ruff, ruff-format, pytest over `portfolio/` and `tests/`).
- [ ] `.claude/commands/fit.md` documents `--jd-dir`, the accepted extensions, the mutual-exclusion contract, the ranked-output columns, and the batch-mode `--lang` default (`en`).
- [ ] `README.md` `/fit` section documents `--jd-dir` with at least one example invocation and a brief note on the ranked output and on the batch-mode `--lang` default.

## Out of scope
- JD providers / remote job discovery (#41–#43). `--jd-dir` reads LOCAL files only; no HTTP fetching for batch inputs.
- The reverse-fit job-discovery seam (#40); this task ships only the local batch + rank enabling step.
- Semantic matching and must-have/nice-to-have weighting (separate #37 follow-ups).
- Any change to `score_fit`, the rubric, `COVERAGE_CUTOFFS`, `GRADE_BANDS`, or `fit/grade.py` — math is frozen.
- Per-JD bounded agent grading. `bounded_grade` is NOT called in batch mode (would defeat "build ONCE" via N model calls and would break determinism, since the default grader runner is non-deterministic by its own docstring).
- Recursive directory traversal under `--jd-dir`. Top-level only.
- Auto-detecting `--lang` from the JD set in batch mode. Per PR-001, batch defaults to `en`; auto-detection is single-JD only.
- Per-JD output files in `--out` mode. `--out` writes the single ranked table when `--jd-dir` is used; per-JD file emission is not in scope.
- Modifying `portfolio.render._escape` or `portfolio.render._ESCAPE_CHARS`. Per PR-004, the global escaper is a shared dependency of `render_fit` (single-JD) and `render_portfolio`; adding `|` there would alter any existing output containing `|` and break the single-JD byte-identity contract. The cell escaper lives in `fit/render.py` and applies only to ranked-table cells.

## Affected files
- `fit/cli.py` — add `--jd-dir`, mutual-exclusion + required validation, empty-dir guard, single portfolio build, per-JD `score_fit` loop, dispatch to the ranked-table renderer; preserve the single-`--jd` path verbatim including its existing `--lang` auto-detect behavior; in batch mode default `lang` to `"en"` when `--lang` is omitted.
- `fit/render.py` — add (1) a ranked-table renderer (e.g. `render_fit_batch`) that takes `list[(jd_basename, ScoreResult)] + lang` and emits a Markdown table sourcing labels from `LANGS[lang]`, and (2) a NEW table-cell escaper helper (e.g. `_escape_cell`) that handles `|`, `\n`, `\r` in addition to delegating to `portfolio.render._escape` for the existing Markdown specials. Existing `render_fit` and its single-JD code path are untouched.
- `portfolio/i18n.py` — add ranked-table UI string keys to BOTH `LANGS["en"]` and `LANGS["ko"]`: column headers (`JD`, `Grade`, `Score`, `Coverage%`, `Top Gaps`) and any cell labels the renderer needs. Exact key names are the implementer's choice; the new keys must be non-empty in both langs.
- `.claude/commands/fit.md` — document the new `--jd-dir` flag, the accepted extensions, the mutual-exclusion contract, the ranked-output format, and the batch-mode `--lang` default (`en`).
- `README.md` — extend the `/fit` section with `--jd-dir` usage, a one-line note on the ranked output, and the batch-mode `--lang` default.
- `(new) tests/test_fit_batch.py` — the test-author writes new batch-mode tests here, following the `tests/test_*.py` pattern. Some i18n leak/completeness coverage may instead extend `tests/test_i18n.py` if the test-author judges that natural; see Verification hooks.
- `(new) tests/golden/fit_single_jd/stdout.md` — checked-in golden stdout captured from the base-branch single-`--jd` happy-path invocation (PR-003).
- `(new) tests/golden/fit_single_jd/stderr.txt` — checked-in golden stderr captured from the base-branch single-`--jd` happy-path invocation (PR-003).

## Verification hooks

### Existing (must continue to pass)
- `bash .redteam/scripts/verify.sh` — full suite (ruff + ruff-format + pytest over `portfolio/` and `tests/`).
- `python -m pytest tests/test_fit.py` — single-`--jd` behavior, including the existing grounding-summary and out-file tests.
- `python -m pytest tests/test_i18n.py` — LANGS completeness, structural no-English-leak in `ko` renders, and SUPPORTED_LANGS live view.

### To be created (test-author will define exact test names)
- A `--jd-dir` happy-path test: build a temp dir with ≥ 2 `*.txt` / `*.md` JDs of differing keyword density, run the CLI in-process, assert exit code 0 and a Markdown ranked table on stdout with N rows in best-first order.
- An extension-filter test: a `--jd-dir` containing `.txt`, `.md`, `.json`, and `.txt.bak` files — only `.txt` and `.md` are scored.
- A filename-tiebreak test: inject two JDs that tie on score and coverage% so only the basename tiebreak distinguishes their row order; assert ascending basename order.
- A mutual-exclusion test: `--jd a --jd-dir b` → exit 2, exactly one stderr line.
- A neither-supplied test: omit both → exit 2, exactly one stderr line.
- An empty-dir test: `--jd-dir` pointing to a dir with no matching files → exit 2, exactly one stderr line, no traceback.
- A "build once" test: inject a counting `extractor` (and a counting `runner`); after `--jd-dir` over N JDs, assert the extractor was called exactly once and the runner was called the same number of times a single-`--jd` invocation calls it.
- A "score_fit per JD, same Portfolio instance" test: wrap or count calls into `score_fit` and assert it was called exactly N times AND the `Portfolio` argument is the same object (`is`-identical) on every call.
- A determinism test: invoke the CLI twice in-process with the same inputs; assert byte-identical stdout.
- A single-JD byte-identity test (PR-003): assert `captured.out == open("tests/golden/fit_single_jd/stdout.md").read()` AND `captured.err == open("tests/golden/fit_single_jd/stderr.txt").read()` for the same fakes and argv used to capture the golden on the base branch.
- A table-cell escaping test (PR-002): basenames containing `|` and a literal `\n` are rendered with `|` escaped and newline collapsed to a space; row count and per-row line count are preserved.
- A `--lang ko` no-leak test on the ranked-table output, extending the structural English-leak pattern already used in `tests/test_i18n.py` — assert no `LANGS["en"]` UI string used by the ranked table appears verbatim in the `ko` rendered output.
- A batch-default-lang test (PR-001): `--jd-dir` over a directory of Korean-text JDs with `--lang` omitted renders English headers; the Korean header strings from `LANGS["ko"]` are absent from stdout.
- A single-JD lang-autodetect preservation test (PR-001): `--jd <path>` with a Hangul-dominant JD and `--lang` omitted still renders in `ko` exactly as before.
- A grounding-isolation test: after a `--jd-dir` run, no JD basename and no substring of any JD body appears in any `Evidence.ref` or `Evidence.detail` of the in-memory `Portfolio`.
- An i18n completeness assertion: the new ranked-table keys are present in both `LANGS["en"]` and `LANGS["ko"]` (covered by extending or relying on the existing completeness tests).

## Risks
- **Golden capture procedure (PR-003).** The single-JD golden must be captured on the BASE branch (pre-change) and checked in BEFORE the implementer's diff is reviewed. If the test-author captures the golden from a post-change tree by accident, the byte-identity assertion becomes a tautology. The phase prompt's test-author instructions should make this explicit; otherwise the human must verify the golden's provenance at the gate.
- **N for Top Gaps.** Pinned to 5 per the brief's "e.g. 5". If the human prefers 3 or 10 the constant must change before tests are authored.
- **Score column derivation.** Pinned to band midpoint `(min + max) // 2`. The brief lists a `Score` column but only `score_fit` (which yields a band, not an integer) is reused; `bounded_grade` is excluded by the determinism contract. If the human prefers band-min, band-max, or showing the band as a range string, the pin must change.
- **Mutual-exclusion mechanism.** The outcome requires "exit 2 + one-line stderr". `argparse`'s native `add_mutually_exclusive_group(required=True)` emits a two-line usage + error output. The implementer may need to validate manually post-parse to keep the message to exactly one line; the one-line assertion in the test enforces this.
- **`--out <file>` semantics in batch.** Assumed: batch mode writes the single ranked-table Markdown to `--out` when given. If the human wants per-JD Markdown files instead, the design materially changes.
- **JD filename collisions.** If two files in `--jd-dir` differ only by extension (`role.txt` and `role.md`), they produce two table rows with distinct `JD` basenames; no dedup is performed. Confirm this is the desired behavior.
- **Grade / Score / Coverage% redundancy.** Grade is fully determined by `coverage_pct` cutoffs and `Score` is the band midpoint of that grade, so the three columns repeat information. This is consistent with the brief's column list and is intentional; flagged so the human knows the table is not surfacing the LLM-graded integer.
- **Cell escaper location is locked to `fit/render.py` (PR-004).** Reviewer flagged that touching `portfolio.render._ESCAPE_CHARS` would change `_escape` for `render_fit` (single-JD) and `render_portfolio`, breaking byte-identity for any existing output containing `|` (claim text, evidence detail, URLs, refs). The cell escaper is therefore a NEW helper in `fit/render.py` and is invoked only for ranked-table cells. The global `portfolio.render._escape` is forbidden from modification by a Done-when guard above.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```
