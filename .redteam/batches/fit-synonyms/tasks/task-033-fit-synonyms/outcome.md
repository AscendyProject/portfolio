# Outcome — deterministic tech-synonym matching for fit coverage (issue #37, synonym subset)

## Goal
A pinned, single-token tech-alias table in `resume/select.py` makes `fit`'s coverage signal
match common synonyms/abbreviations deterministically (e.g. `k8s` ↔ `kubernetes`, `js` ↔
`javascript`, `postgres` ↔ `postgresql`) so a JD requirement and equivalent portfolio claim
align on a common canonical token, with no model call and no new dependency.

## Done-when
- [ ] `resume/select.py` defines a module-level, importable constant of type
  `dict[str, str]` (single-token alias → single-token canonical, both lowercase ASCII)
  containing AT MINIMUM these unambiguous pairs from the brief:
  `k8s → kubernetes`, `js → javascript`, `ts → typescript`, `py → python`,
  `postgres → postgresql`, `pg → postgresql`, `golang → go`, `ror → rails`,
  `tf → terraform`. Every entry is a single token on both sides (no whitespace,
  no `/`, no `.`) — verifiable by a test that asserts the shape of every entry.
- [ ] `resume/select.py::jd_keywords` applies the alias lookup as an additional
  normalization step between the existing filters and `_stem`, i.e. the effective
  order is `_strip_meta_lines → tokenize → lower → STOPWORDS/JD_META_STOPWORDS/len/digit
  filters → alias-canonicalize (passthrough on miss) → _stem`. Order is identical for
  the JD side and the claim/portfolio side (the claim side already routes through
  `jd_keywords` via `fit/score.py::_claim_tokens` and `resume/select.py::_claim_tokens`;
  no second normalization path is introduced).
- [ ] For every pair in the alias table, `jd_keywords("<alias>") == jd_keywords("<canonical>")`
  produces the same single-element set (verified by a parametrized test that iterates the
  table). Specifically, `jd_keywords("k8s")` and `jd_keywords("kubernetes")` return the
  same set; same for `js`/`javascript`, `postgres`/`postgresql`, etc.
- [ ] In `fit/score.py::score_fit`, a portfolio whose only claim text is the alias form
  (e.g. `"shipped on k8s"`, grounded by a real evidence ref) covers a JD that uses only
  the canonical form (e.g. `"requires kubernetes"`), and vice versa — i.e. the keyword
  appears in `ScoreResult.covered` and not in `ScoreResult.gaps`. A test asserts both
  directions for at least the `k8s`/`kubernetes` and `postgres`/`postgresql` pairs.
- [ ] Passthrough invariant: a token that is NOT a key in the alias table is unchanged
  by the alias step. Test: pick a representative non-alias token already used by existing
  tests (e.g. `python` used directly, `service`, `backend`) and assert
  `jd_keywords("<token>")` returns the same set it would have without the alias step
  (i.e. equals `{_stem("<token>")}`).
- [ ] High-precision guard: an ambiguous single-character or short token that a naive
  table might be tempted to alias is NOT a key in the table. Test asserts the table does
  NOT contain `c`, `r`, `go` (as a KEY — `go` may appear only as a VALUE, the canonical
  side of `golang → go`), `ml`, `ai`. (Plain English: aliases must be unambiguous tech
  equivalences; `c → c++` etc. are forbidden.) The test reads the table directly to
  assert these keys are absent.
- [ ] End-to-end coverage uplift: a JD that exercises at least three alias pairs
  (e.g. `kubernetes`, `javascript`, `postgresql`) scored against a portfolio whose
  claims use the alias forms (`k8s`, `js`, `postgres`) yields strictly higher
  `coverage_pct` than the same `score_fit` call would return if the alias table were
  empty. The test asserts the inequality with both runs in-process (monkeypatch the
  table to `{}` for the baseline run).
- [ ] No-regression: `bash .redteam/scripts/verify.sh` passes (ruff check, ruff format
  check, and full pytest including `tests/test_resume_select.py`,
  `tests/test_jd_keywords_unicode.py`, `tests/test_fit.py`, `tests/test_fit_score_quality.py`).
- [ ] Korean no-regression: `tests/test_jd_keywords_unicode.py` stays green — the alias
  table contains only ASCII keys and ASCII values, so non-ASCII tokens flow through
  unchanged. Verified by the existing Korean-JD assertions plus a new test that asserts
  every alias-table key and value satisfies `.isascii()` and `len(k) >= 2`.
- [ ] Determinism: a test calls `score_fit` twice on the same `(portfolio, jd_text)`
  inputs and asserts the two `ScoreResult` objects compare equal (or that
  `coverage_pct`, `covered`, `gaps` are equal across runs). No model call, no
  subprocess, no network introduced by the alias step.
- [ ] `README.md` `/fit command` section (or the immediately adjacent prose, lines
  ~148–192) gains a one-paragraph note that fit coverage now matches a pinned set of
  single-token tech synonyms (giving 2–3 concrete examples) and that multi-word
  synonyms and embedding-based semantic matching are explicit non-goals tracked
  separately under issue #37.

## Out of scope
- Embedding / vector / model-based semantic matching (e.g. `containerization` ↔
  `kubernetes`). Separate #37 follow-up.
- Multi-word / phrase aliases (e.g. `google cloud` ↔ `gcp`, `github actions` ↔ `gha`,
  `ci/cd` ↔ `continuous integration`). v1 is single-token only; brief explicitly
  defers these.
- Must-have vs nice-to-have weighting, JD section/structure parsing — separate
  #37 follow-up.
- Changing `COVERAGE_CUTOFFS`, `GRADE_BANDS`, or any math inside `fit/grade.py`.
- Changing the rubric, the bounded-agent step, or grounding semantics.
- Touching `portfolio/extract.py`, `portfolio/narrative.py`, `portfolio/grounding.py`,
  or `portfolio/pipeline.py`.
- Adding a new runtime pip dependency or a configuration file for the alias table —
  the table stays pinned in code, mirroring `STOPWORDS` / `JD_META_STOPWORDS` /
  `NON_CODE_AXES`.
- Transitive / chained alias resolution (alias → canonical → another canonical). The
  table is a flat single-step lookup with passthrough default.
- Improving `resume`-side selection behavior beyond what falls out of the shared
  normalization change (existing `tests/test_resume_select.py` must stay green).

## Affected files
- `resume/select.py` — add the pinned alias `dict` constant, add a small helper that
  applies the alias lookup with passthrough default, wire it into `jd_keywords`
  between the existing filters and `_stem`. This is the ONLY engine change required;
  `fit/score.py::_claim_tokens` already routes through `jd_keywords`, so the claim
  side picks the alias step up automatically.
- `README.md` — one short paragraph in the `/fit command` section documenting
  single-token synonym matching and the multi-word / embedding non-goals.
- `(new) tests/test_fit_synonyms.py` — new tests at the canonical test location
  (matches the `test_*.py` pattern) covering: every Done-when assertion above
  (table shape, table content, both-direction `jd_keywords` equivalence, JD↔claim
  coverage in both directions, passthrough, high-precision guard, coverage uplift,
  ASCII invariant, determinism). Test-author writes this file; outcome-planner does
  not enumerate function names.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Existing (must continue to pass)
- `bash .redteam/scripts/verify.sh` — full project gate (ruff check, ruff format
  check, full pytest under `tests/`).
- `pytest tests/test_resume_select.py -x --tb=short` — existing resume.select
  contract (stopwords, stemming, meta-cleaning, selection ranking, grounding).
- `pytest tests/test_jd_keywords_unicode.py -x --tb=short` — task-021 Unicode
  guard (Korean JD tokenization not degraded by the alias step).
- `pytest tests/test_fit_score_quality.py -x --tb=short` — issue #44 deterministic
  defects fix (meta-cleaning, stemming, non-code axes) still holds end-to-end.
- `pytest tests/test_fit.py -x --tb=short` — `/fit` command grounded coverage and
  banded scoring still hold.

### To be created (test-author will define exact test names)
- Tests under `tests/` (new file matching `test_*.py`) covering, in plain English:
  - the alias table is a `dict[str, str]` of single ASCII tokens (≥2 chars on
    each side), exported as a module-level name from `resume.select`;
  - the table contains the brief's required pairs (`k8s→kubernetes`,
    `js→javascript`, `ts→typescript`, `py→python`, `postgres→postgresql`,
    `pg→postgresql`, `golang→go`, `ror→rails`, `tf→terraform`);
  - the table does NOT contain ambiguous keys (`c`, `r`, `go` as a key, `ml`, `ai`);
  - `jd_keywords(alias) == jd_keywords(canonical)` for every pair in the table;
  - in `score_fit`, a portfolio claim using the alias form covers a JD using the
    canonical form (and vice versa) for `k8s`/`kubernetes` and `postgres`/`postgresql`;
  - a non-alias token (e.g. `service`, `backend`, `python` directly) survives
    `jd_keywords` exactly as it did before the alias step (i.e. `{_stem(token)}`);
  - a JD exercising ≥3 alias pairs against a portfolio using the alias forms
    yields strictly higher `coverage_pct` than the same `score_fit` call with the
    alias table monkeypatched to `{}`;
  - all alias keys and values are ASCII (Korean / non-ASCII tokens are unaffected);
  - `score_fit` on identical inputs is byte-equal across two consecutive calls
    (determinism preserved).

## Risks
- **Where the alias table lives.** Brief permits `resume/select.py` next to `_stem`
  or "a small dedicated map" module. Outcome locks it to `resume/select.py` (mirrors
  `STOPWORDS` / `JD_META_STOPWORDS`); if the human prefers a dedicated module
  (e.g. `resume/aliases.py`), this must be decided BEFORE implementation, since it
  changes the `Affected files` budget.
- **Stem vs alias ordering.** Outcome locks the order to `… → alias → _stem` so
  the table's values must be pre-stem forms whose `_stem` matches what the other
  side produces (e.g. `kubernetes` stems to `kubernetes` because `-tes` is blocked,
  so `k8s → kubernetes` round-trips cleanly). If a future canonical (not in v1) would
  stem differently on either side, the table author must verify equivalence.
- **`go` as a value but not a key.** `golang → go` is in the required set, but `go`
  is a plausible English word and a high-risk alias key. Outcome forbids `go` as a
  KEY; if the human wants `go` aliased anywhere else (it shouldn't), surface before
  implementation.
- **Transitivity.** Outcome forbids transitive resolution. If the human later wants
  chained aliases (alias A → alias B → canonical C), that is a separate task — single
  lookup keeps the contract auditable.
- **Whether `fit/score.py` needs a wiring change.** Today `fit/score.py::_claim_tokens`
  calls `jd_keywords` directly, so adding the alias inside `jd_keywords` covers both
  sides without editing `fit/score.py`. If implementer discovers a second tokenization
  path that bypasses `jd_keywords`, they must surface it rather than silently edit
  outside the `Affected files` budget.
- **README placement.** The note lives in the `/fit command` section (around lines
  148–192). If the human wants it in a different section (e.g. a new "Limitations"
  block), surface before merge — it does not affect engine behavior.
- **Alias-table completeness.** v1 ships the brief's required pairs only. Additional
  entries (e.g. `node ↔ nodejs`, `rb ↔ ruby`) are tempting but each one is a precision
  risk; outcome leaves expansion to a follow-up so the v1 table is reviewable in a
  single diff.
