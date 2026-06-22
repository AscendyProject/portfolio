# Outcome — deterministic fit-score quality (issue #37, deterministic part)

## Goal
Stop `/fit`'s coverage% from collapsing to ~26% on every JD by fixing three
deterministic defects in keyword extraction so the score actually reflects
code-fit: (A) strip whole JD-format preamble lines AND drop residual meta-token
noise so the denominator holds real requirements, (B) stem English variants
deterministically so `migration`/`migrations` and `deploy`/`deployed` align,
and (C) keep non-codeable axes (`japanese`, `years`, `bachelor`, …) out of the
coverage denominator. Korean tokenization (task-021) and the grade rubric /
score bands must remain untouched.

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

## Out of scope
- Semantic / synonym / embedding matching (`containerization` ↔ `kubernetes`,
  `gcp` ↔ `Google Cloud`). Requires a bounded model/embedding seam — separate
  follow-up of #37.
- Must-have vs nice-to-have **weighting** and honoring the JD's
  Minimum / Preferred / Tech-stack section STRUCTURE — separate task.
- Batch / ranked output (#38) and JD providers (#41–#43).
- A real stemming library (PorterStemmer, snowballstemmer, NLTK) — explicitly
  forbidden by the brief; the helper is a small ASCII suffix stripper.
- Editing `fit/grade.py` (rubric / bands / score math). Locked.
- Renderer changes — `fit/render.py` is NOT in scope unless a separate
  "Non-code requirements" rendered section is later requested. The new
  `ScoreResult.non_code_requirements` field is data-only for now.
- Modifying the JD-source layer (`portfolio/jd_source.py`) to inject or
  rewrite preamble at load time. Preamble-line stripping happens inside
  `jd_keywords` only.

## Affected files
- `resume/select.py` — add `JD_META_LINE_PATTERNS` pinned tuple,
  `_strip_meta_lines` helper, `JD_META_STOPWORDS` pinned set, and `_stem`
  helper; extend `jd_keywords` and `_claim_tokens` to apply Part A line-
  stripping + token cleaning (denylist + len<2 + pure-digit drop) and
  Part B stemming. Shared by resume + fit.
- `fit/score.py` — add `NON_CODE_AXES` pinned set (already stemmed), add
  `non_code_requirements: set[str]` field to `ScoreResult`, update
  `score_fit` to remove non-code tokens from both numerator and denominator
  and populate the new field.
- `(new) tests/test_fit_score_quality.py` — new pytest file (matches the
  project's `test_*.py` pattern). Covers Parts A.1 / A.2 / B / C, the
  preamble-format regression test, and the well-matched vs poorly-matched
  ranking regression; the Korean no-regression assertion also lives here.
  Existing `tests/test_resume_select.py`, `tests/test_fit.py`, and
  `tests/test_jd_keywords_unicode.py` are NOT edited.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

## Verification hooks

### Existing (must continue to pass)
- `bash .redteam/scripts/verify.sh` — full suite (ruff check, ruff format
  check, pytest -x over `tests/`).
- `pytest tests/test_jd_keywords_unicode.py -x --tb=short` — task-021 Korean
  regression guard.
- `pytest tests/test_resume_select.py -x --tb=short` — existing resume
  selection behavior must not regress.
- `pytest tests/test_fit.py -x --tb=short` — existing fit semantics
  (grounding, bands, hallucinated-ref handling) must not regress.

### To be created (test-author will define exact test names)
- New tests under `tests/test_fit_score_quality.py` covering:
  - Part A.1: `JD_META_LINE_PATTERNS` exists and is importable; a JD that
    begins with the literal harness preamble line
    `"Extracted job description for resume/fit keyword matching"` followed by
    a real requirement line yields keywords containing only the real-
    requirement stems (no `extracted`, no `matching`, no `description`, no
    `keyword`, no `resume`, no `fit`, no `portfolio`); `_strip_meta_lines`
    also runs on claim text.
  - Part A.2: `JD_META_STOPWORDS` membership; `jd_keywords` and
    `_claim_tokens` drop every meta token, every len-`<2` token, and every
    pure-digit token even when those tokens appear inside an otherwise
    legitimate requirement line.
  - Part B: `_stem` exists; `_stem` is identity on non-ASCII tokens
    (Korean); pinned English suffix-pair stemming behavior; JD-vs-claim
    stem-match behavior end-to-end via `select_claims` and `score_fit`.
  - Part C: `NON_CODE_AXES` membership; `score_fit` excludes non-code tokens
    from both numerator and denominator; `ScoreResult.non_code_requirements`
    surfaces them; `resume/select.jd_keywords` does NOT filter on
    `NON_CODE_AXES`.
  - End-to-end regression: well-matched JD vs poorly-matched JD against the
    same portfolio — coverage% gap ≥ 30 percentage points AND well-matched
    coverage% ≥ 50.
  - Preamble-robustness regression: prepending the harness preamble line to
    JD-MATCH shifts `coverage_pct` by no more than ±2.0.
  - Korean no-regression: a Korean JD still produces real Korean keywords
    after Part A.1 + Part A.2 + Part B run.
  - No NEW third-party dependency: this is a negative, no-new-dependency
    property verified by the code REVIEWER against the branch diff — confirming
    no forbidden external stemming package (`nltk`, `snowballstemmer`,
    `Stemmer`, `pystemmer`, `porter2stemmer`, `spacy`) is imported AND that
    `pyproject.toml` runtime deps are unchanged — NOT by a pytest. A pytest
    grepping source for absent package names is non-discriminating (passes
    pre-change) and reading VCS state from a unit test is non-hermetic
    (cf. PR-004). The positive stdlib-only proof is the Part B stemming tests.

## Risks
- **Decision pinned but flagged:** Part C is implemented as
  *exclude-from-coverage* (numerator AND denominator) AND surface in a new
  `ScoreResult.non_code_requirements` data field. The brief allows the
  alternative *report-in-separate-section-but-still-counted* path — the human
  should confirm the exclude-from-coverage choice is the intended one. If the
  alternative is preferred, the `score_fit` change and one done-when item
  change.
- **`JD_META_LINE_PATTERNS` is a hand-pinned list of harness preamble
  patterns.** The brief identifies one explicit pattern (the
  `"extracted job description for resume/fit keyword matching"` line) plus a
  generic `<label>:` form. Future harness changes that introduce a new
  preamble shape will need a new pattern added; this list is the contract.
- **`NON_CODE_AXES` is a hand-pinned list.** Tokens not on the list (e.g.
  `mandarin`, `phd`, `mba`, `aws-certified`) will still drag coverage down
  until added. The brief explicitly accepts this ("pinned in code, a model
  never contributes" spirit) — but the list will need maintenance.
- **`_stem` is a hand-rolled suffix stripper, not a real stemmer.** It will
  over-stem (e.g. `class` → `cla`?) or under-stem on edge cases the test
  suite doesn't cover. The brief explicitly chose this over a library;
  surface here so the human knows the tradeoff and so the test-author pins
  ONLY the suffix-pair behavior the brief named, not arbitrary English.
- **The "all four JDs scored 26%" defect is observational, not in a test
  fixture.** The Done-when regression uses synthetic JD text crafted to
  exercise the matched/mismatched contrast, not the real Google / OpenAI /
  PayPay / Sakana JDs. The human should confirm the synthetic regression is
  an adequate stand-in.
- **`ScoreResult` gains a new field** (`non_code_requirements`). Any
  downstream consumer that destructures `ScoreResult` positionally would
  break — `fit/render.py` and `fit/cli.py` are the only known consumers and
  both use attribute access, so the risk is contained, but worth a sanity
  grep during implementation.
- **The shared `_claim_tokens` change affects resume selection scoring too**
  (because stems now collapse and preamble lines now strip). The brief
  allows "improvement, no regression of existing assertions" — but a few
  existing `test_resume_select.py` assertions check exact match counts on
  multi-token claims, which could shift if stemming changes the result set
  size. The implementer must verify every existing assertion still passes;
  if any breaks, surface to the human rather than weaken the test.
