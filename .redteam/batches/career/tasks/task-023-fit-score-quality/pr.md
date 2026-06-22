## What
Stop `/fit`'s coverage% from collapsing to ~26% on every JD by fixing three
deterministic defects in keyword extraction so the score actually reflects
code-fit: (A) strip whole JD-format preamble lines AND drop residual meta-token
noise so the denominator holds real requirements, (B) stem English variants
deterministically so `migration`/`migrations` and `deploy`/`deployed` align,
and (C) keep non-codeable axes (`japanese`, `years`, `bachelor`, …) out of the
coverage denominator. Korean tokenization (task-021) and the grade rubric /
score bands must remain untouched.

## Why
In dogfooding, four very different JDs (Google / OpenAI / PayPay / Sakana) all
scored 26–27% regardless of true fit (issue #37). The cause is three
deterministic defects in `jd_keywords`: harness-added preamble/meta tokens
pollute the denominator, exact-token matching misses common stem variants
(`migration` vs `migrations`), and non-codeable axes (`japanese`, `years`,
`bachelor`) drag code-fit coverage down. This task fixes the deterministic
defects only — semantic/embedding matching is a separate follow-up.

## Done-when

### Part A — requirement extraction cleaning (in `resume/select.py`)

**A.1 — line-level preamble stripping (deterministic)**
- [ ] A new module-level pinned tuple of compiled regexes (importable from
      `resume.select`, e.g. `JD_META_LINE_PATTERNS`) matches whole-line JD
      preamble noise. It includes at minimum a pattern that matches the
      harness-style preamble line
      `"extracted job description for resume/fit keyword matching"`
      (case-insensitive, with leading/trailing whitespace tolerated) AND a
      pattern that matches a generic `"job description:"` / `"keywords:"` /
      `"resume:"` / `"portfolio:"` header line (the line is a `<label>:` form
      with nothing else on it).
- [ ] A new private helper (e.g. `_strip_meta_lines(text: str) -> str`) drops
      every line that matches any pattern in `JD_META_LINE_PATTERNS`, then
      joins the survivors with `"\n"`. Pure, deterministic, stdlib-only.
- [ ] `jd_keywords(jd_text)` calls `_strip_meta_lines` on its input BEFORE
      tokenizing — asserted by a regression test that feeds the exact
      preamble line from the brief plus one real requirement line:
      `"Extracted job description for resume/fit keyword matching\n" +
       "python backend kubernetes"` and asserts the result contains
      `python`, `backend`, `kubernetes` (stemmed) and does NOT contain
      `extracted`, `matching`, `for`, `description`, `job`, `keyword`,
      `resume`, `fit`, `portfolio`.
- [ ] The same `_strip_meta_lines` runs on claim text in `_claim_tokens`
      (asserted: a `Claim` whose text accidentally contains the preamble line
      contributes only its real tokens).

**A.2 — token-level junk filter (residual)**
- [ ] A new module-level pinned set (importable from `resume.select`, e.g.
      `JD_META_STOPWORDS`) contains at minimum: `job`, `description`,
      `keywords`, `keyword`, `resume`, `portfolio`, `fit`, `com`, `extracted`,
      `matching`. Tests assert each of those tokens is in the set.
- [ ] `jd_keywords(jd_text)` returns a set that contains NONE of the tokens in
      `JD_META_STOPWORDS` even when those tokens appear mid-sentence in a
      requirement line (asserted by feeding a JD line like
      `"strong python backend resume preferred"` and confirming `resume` is
      absent while `python`, `backend` survive).
- [ ] `jd_keywords(jd_text)` drops tokens whose length (after lowercasing) is
      `< 2` (asserted by feeding `"a b cd e"` and confirming only `cd` survives,
      modulo other filters).
- [ ] `jd_keywords(jd_text)` drops pure-digit tokens (asserted by feeding
      `"python 3 10 2024 microservices"` and confirming `3`, `10`, `2024` are
      absent from the result while `python` and `microservices` survive in
      their stemmed form).
- [ ] The same cleaning is applied to claim tokens: `_claim_tokens(claim)`
      contains NONE of `JD_META_STOPWORDS`, no len-`<2` tokens, no pure-digit
      tokens (asserted by building a `Claim` with text containing those tokens
      and inspecting `_claim_tokens`).

### Part B — deterministic stdlib-only stemming (in `resume/select.py`)
- [ ] A private helper (e.g. `_stem(token: str) -> str`) is defined in
      `resume/select.py`. It is pure, deterministic, and ASCII-aware: any
      token containing a non-ASCII character (e.g. Hangul) is returned
      unchanged (asserted by `_stem("파이썬") == "파이썬"` and
      `_stem("개발자") == "개발자"`).
- [ ] `_stem` collapses at minimum these English suffix variants to a single
      stem (asserted by tests pinning each pair to the same output):
      `migration` ↔ `migrations`, `deploy` ↔ `deploys` ↔ `deployed` ↔
      `deploying`, `container` ↔ `containers`, `service` ↔ `services`,
      `orchestrate` ↔ `orchestrated` ↔ `orchestrating`.
- [ ] `jd_keywords(jd_text)` returns stemmed tokens (asserted:
      `jd_keywords("kubernetes migrations and deploys")` and
      `jd_keywords("kubernetes migration deployed")` produce the same set).
- [ ] `_claim_tokens(claim)` returns the SAME stemmed token form (asserted: a
      `Claim(text="ran migrations and deployed containers", refs=["PR#1"])`
      against `jd_keywords("migration deploy container")` produces a non-empty
      intersection equal to all three stems).
- [ ] `select_claims` and `score_fit` therefore match `migration` in a JD
      against `migrations` in a claim (end-to-end assertion via
      `select_claims` returning score > 0, AND via `score_fit` returning a
      `covered` dict containing the shared stem).
- [ ] **No new third-party dependency / import is introduced.** The `_stem`
      helper uses only Python stdlib facilities (`str` methods, `re`). This is a
      negative, no-new-dependency property and is verified by the code REVIEWER
      against the branch diff (confirming no runtime dependency is added to
      `pyproject.toml` and no forbidden external stemming package — `nltk`,
      `snowballstemmer`, `Stemmer`, `pystemmer`, `porter2stemmer`, `spacy` —
      is imported), NOT by a pytest. A pytest grepping source for absent package
      names is inherently non-discriminating (it passes pre-change, since those
      packages were never present) and reading VCS state from a unit test is
      non-hermetic (cf. PR-004). The POSITIVE proof that `_stem` is stdlib-only
      is the Part B stemming tests above, which exercise real `_stem` behavior.

### Part C — non-codeable axis separation (in `fit/score.py`, NOT shared)
- [ ] A new module-level pinned set (importable from `fit.score`, e.g.
      `NON_CODE_AXES`) contains at minimum: `japanese`, `english`, `korean`,
      `year`, `years`, `bachelor`, `bachelors`, `degree`, `bs`, `ms`, `phd`,
      `master`, `masters`, `sales` — note these are stored already in their
      `_stem`'d form so they compare correctly to stemmed JD tokens. (`sales`
      is the non-codeable axis explicitly named in issue #37 / the brief —
      PR-002.) Tests assert each listed token appears in the set after stemming,
      including `sales`.
- [ ] `score_fit` excludes `NON_CODE_AXES` tokens from BOTH the coverage
      numerator AND the coverage denominator. Asserted by: a JD
      `"python backend years bachelor japanese"` against a portfolio whose
      only claim is `text="python backend service"` produces
      `coverage_pct == 100.0` (because the two codeable tokens `python` and
      `backend` are both covered, and the three non-codeable tokens are
      excluded from the denominator entirely).
- [ ] `ScoreResult` gains a `non_code_requirements: set[str] =
      field(default_factory=set)` field — a DEFAULTED field (via
      `dataclasses.field`) so every existing `ScoreResult(...)` construction
      site in tests and code stays valid WITHOUT edits (PR-003) — listing JD
      tokens that were recognised as non-codeable axes and excluded. Asserted by: for the JD above, `result.non_code_requirements`
      contains (at minimum, in stemmed form) the three non-code tokens, and
      none of them appears in either `result.covered` or `result.gaps`.
- [ ] The `NON_CODE_AXES` filter lives in `fit/score.py` only — `resume/select.py`
      `jd_keywords` and `_claim_tokens` do NOT filter on it. Asserted by:
      `jd_keywords("python years bachelor")` still contains the stems of
      `years` and `bachelor` (resume selection is unaffected).

### End-to-end ranking regression — well-matched vs poorly-matched
- [ ] One pytest test builds a portfolio of grounded claims about a python /
      backend / kubernetes / microservices skill set (using
      `Portfolio`/`Claim`/`Evidence` in-process — no live `gh`, no model
      call), computes `score_fit` against two JDs:
        - JD-MATCH = a real-style JD heavy in python / backend / kubernetes /
          microservices / deploy / container vocabulary
        - JD-MISMATCH = a real-style JD heavy in java / spring / hibernate /
          jvm vocabulary
      and asserts `match_result.coverage_pct - mismatch_result.coverage_pct
      >= 30.0` (i.e. the well-matched JD scores materially higher; the
      `~26%-for-everything` defect is gone).
- [ ] The same regression test additionally asserts
      `match_result.coverage_pct >= 50.0` (a well-matched JD now lands in at
      least the C/B band range, not stuck below it).
- [ ] One pytest test prepends the actual preamble line from the brief
      (`"Extracted job description for resume/fit keyword matching\n\n"`) to
      JD-MATCH and asserts the resulting `coverage_pct` is within ±2.0 of
      the no-preamble JD-MATCH `coverage_pct` (i.e. preamble-line removal
      makes the score robust to the preamble noise).

### Task-021 Unicode no-regression
- [ ] All assertions in `tests/test_jd_keywords_unicode.py` and
      `tests/test_resume_select.py` continue to pass byte-for-byte (no edits
      to those files; verified by running them under `bash
      .redteam/scripts/verify.sh`).
- [ ] Korean no-regression is guarded by the EXISTING
      `tests/test_jd_keywords_unicode.py` (Korean keyword extraction), which
      stays green under `verify.sh` AFTER Parts A/B run on `jd_keywords` —
      Part A meta-stripping / token-filtering only removes ASCII meta tokens,
      and Part B `_stem` is identity on non-ASCII, so Korean tokens pass
      through unchanged. No NEW Korean passthrough test is added: such a test
      is inherently non-discriminating (it passes pre-change too — cf. IR-001),
      so the existing Unicode suite is the designated guard (IR-003).

### Grade math / grounding unchanged
- [ ] `fit/grade.py` is NOT edited. The `bounded_grade` function and the
      `COVERAGE_CUTOFFS` / `GRADE_BANDS` constants are byte-identical pre/post
      (asserted by `git diff fit/grade.py` being empty in the implementer's
      `impl_diff.patch`).
- [ ] The grounding contract is preserved: a `Claim` whose `evidence_refs ⊄
      portfolio.evidence` still contributes 0 to coverage (existing
      `test_hallucinated_ref_ignored_in_coverage` continues to pass).
- [ ] JD text is never persisted as `Evidence` (no new code path in
      `score_fit` or `jd_keywords` constructs an `Evidence` object — asserted
      by grepping `fit/score.py` and `resume/select.py` post-change for
      `Evidence(` and confirming the count is unchanged).

### Verification
- [ ] `bash .redteam/scripts/verify.sh` exits 0 (ruff check + ruff format
      check + pytest, all green).

## Verification
- Tests: test_jd_meta_line_patterns_is_importable_tuple, test_jd_meta_line_patterns_matches_harness_preamble, test_jd_meta_line_patterns_matches_preamble_lowercase, test_jd_meta_line_patterns_matches_generic_label_headers, test_strip_meta_lines_removes_preamble_line, test_strip_meta_lines_preserves_real_content, test_jd_keywords_strips_preamble_before_tokenizing, test_claim_tokens_strip_meta_lines, test_jd_meta_stopwords_is_importable_frozenset, test_jd_meta_stopwords_contains_required_tokens, test_jd_keywords_drops_meta_stopwords_mid_sentence, test_jd_keywords_drops_len_less_than_2, test_jd_keywords_drops_pure_digit_tokens, test_claim_tokens_drop_meta_stopwords, test_stem_is_importable, test_stem_identity_on_non_ascii, test_stem_migration_migrations, test_stem_deploy_variants, test_stem_container_containers, test_stem_service_services, test_stem_orchestrate_variants, test_jd_keywords_produces_stemmed_tokens, test_claim_tokens_use_same_stems, test_stem_match_end_to_end_select_claims, test_stem_match_end_to_end_score_fit, test_non_code_axes_is_importable_frozenset, test_non_code_axes_contains_required_tokens, test_score_fit_excludes_non_code_axes_from_numerator_and_denominator, test_score_fit_non_code_requirements_field, test_score_fit_non_code_not_in_covered_or_gaps, test_score_result_non_code_requirements_has_default, test_jd_keywords_does_not_filter_non_code_axes, test_well_matched_vs_poorly_matched_ranking_regression, test_well_matched_coverage_at_least_50_pct, test_preamble_prepend_does_not_shift_coverage_more_than_2pct (new file `tests/test_fit_score_quality.py`)
- Verify command: `bash .redteam/scripts/verify.sh` ✅ (ruff clean, 674 passed, 1 skipped per `verification.log`)

## Code review summary
- Diff summary: `resume/select.py` gains `JD_META_LINE_PATTERNS`, `JD_META_STOPWORDS`, `_strip_meta_lines`, and a stdlib-only ASCII suffix stemmer `_stem`; `jd_keywords` and `_claim_tokens` now strip preamble lines, drop meta/len<2/pure-digit tokens, and emit stemmed tokens. `fit/score.py` gains `NON_CODE_AXES` (already in stemmed form) and a defaulted `ScoreResult.non_code_requirements` field; `score_fit` excludes non-code axes from both numerator and denominator.
- Verification: `bash .redteam/scripts/verify.sh` → exit 0 (ruff check + ruff format + pytest, 674 passed, 1 skipped). `state.verification.last_exit_code == 0`; `impl_diff.patch` matches `git diff main...HEAD`.
- Initial codex review surfaced IR-001 (two non-discriminating new tests) and IR-002 (claim-cleaning tested only via JD intersection, vacuously passes against a no-op `_claim_tokens`). Both resolved in rescue: the two non-discriminating tests were removed (Korean passthrough → already guarded by existing `tests/test_jd_keywords_unicode.py`; absent-package grep → reviewer-checked against branch diff, not a pytest), and the claim-cleaning tests now call `_claim_tokens` directly with no JD intersection (fails against a no-op pre-change `_claim_tokens`).
- Clean codex re-review after rescue: IR-001 & IR-002 RESOLVED. No new dependency added (no `nltk` / `snowballstemmer` / `Stemmer` / `pystemmer` / `porter2stemmer` / `spacy` imports; `pyproject.toml` unchanged). No subprocess / network / secret-handling / evidence-construction / grounding-gate / `fit/grade.py` changes.
- Grounding contract preserved (hallucinated-ref claims still contribute 0 to coverage; JD never persisted as `Evidence`). Korean tokenization from task-021 stays green: Part A meta-stripping removes only ASCII meta tokens, Part B `_stem` is identity on non-ASCII, so `tests/test_jd_keywords_unicode.py` continues passing byte-for-byte.

## Generated by
redteam / batch career / task task-023-fit-score-quality
