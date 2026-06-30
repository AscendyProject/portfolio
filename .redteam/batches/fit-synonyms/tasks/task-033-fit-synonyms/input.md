+++
mode = "agent-pair"
+++

# Task: deterministic tech-synonym matching for fit coverage (issue #37, synonym subset)

## Goal
Improve `fit`'s coverage signal by matching common tech **synonyms/abbreviations**
deterministically, so a JD requirement and equivalent portfolio work align even when they
use different surface words (e.g. `k8s` ↔ `kubernetes`, `js` ↔ `javascript`,
`postgres` ↔ `postgresql`). This is the DETERMINISTIC subset of issue #37's "semantic
matching" — a pinned, high-precision alias table, NOT embeddings and NOT a model call.

## Why (issue #37)
#44 shipped the deterministic defects fix (meta-cleaning, stemming, non-code-axis
separation). The remaining gap: exact/stem matching still misses pure synonyms —
`kubernetes` (JD) ✗ `k8s` (portfolio), `javascript` ✗ `js`, `postgresql` ✗ `postgres`.
These are real, common equivalences that drag coverage down. A small pinned alias table
fixes the highest-frequency cases without a model, staying within the project's
"deterministic, pinned in code, a model never contributes" ethos (mirrors the existing
language taxonomy / non-code-axis / banned-lexicon tables).

## Part A — pinned synonym/alias table
Add a conservative, high-precision `dict` mapping an alias token → its canonical token
(single tokens only in v1), pinned in code (e.g. in `resume/select.py` next to the
existing `_stem` / meta-cleaning, or a small dedicated map). Cover the common dev
abbreviations/synonyms, e.g. `k8s→kubernetes`, `js→javascript`, `ts→typescript`,
`py→python`, `postgres→postgresql`, `pg→postgresql`, `golang→go`, `k8s`, `ror→rails`,
`tf→terraform`, `gha→github actions`(skip if multi-word), etc. Keep it small and
HIGH-PRECISION — only pairs that are unambiguous equivalences. Document each entry's intent
briefly. (Ambiguous/risky aliases are out — false matches are worse than a missed one.)

## Part B — apply the alias canonicalization to BOTH sides
Normalize tokens through the alias table so JD tokens and portfolio claim tokens match on a
common canonical form. The SAME normalization (meta-clean → alias-canonicalize → stem, in a
consistent order applied identically to both sides) must be used for `jd_keywords(...)` and
for the portfolio/claim token extraction that feeds `fit/score.py::score_fit`. Order must be
consistent on both sides so an alias and its canonical collapse to one key. Preserve the
existing stemming and meta-cleaning from #44; aliasing is an ADDITIONAL normalization step.

## Part C — preserve all invariants
- **Deterministic**: same (portfolio, JD) → same score; no model call, no new dependency,
  stdlib only.
- **Preserve task-021 Unicode tokenization** — Korean JDs still produce real keywords;
  `tests/test_resume_select.py` and `tests/test_jd_keywords_unicode.py` stay green (the
  alias table is ASCII tech terms; non-matching tokens pass through unchanged).
- **Grounding unchanged**; JD never persisted as Evidence.
- **Rubric/bands/score math in `fit/grade.py` unchanged** — only the requirement/claim
  token SET feeding coverage changes (more true matches via aliases). No weighting (that is
  a separate #37 follow-up).
- **No over-matching**: a token that is NOT a pinned alias must behave exactly as today
  (alias table is a lookup with passthrough default).

## Out of scope (explicit — separate follow-ups)
- **Embedding / vector / model-based** semantic matching (`containerization` ↔
  `kubernetes`, fuzzy similarity). Needs a bounded model/embedding seam — separate task.
- **Multi-word / phrase synonyms** (`google cloud` ↔ `gcp`, `ci/cd` ↔ `continuous
  integration`). Bag-of-words token matching can't align phrases cleanly; v1 is
  single-token aliases only. Note this limitation in code/README.
- Must-have vs nice-to-have **weighting** and JD section structure (separate #37 follow-up).
- Changing `resume` selection behavior beyond the shared normalization (existing
  `tests/test_resume_select.py` assertions must stay green — improvement, no regression).

## Affected files
- `resume/select.py` — the pinned alias table + the alias-canonicalization step in the
  shared token normalization (`jd_keywords` and the claim/portfolio token path), applied
  consistently to both sides, after meta-cleaning, composed with `_stem`.
- `fit/score.py` — only if the claim-token side of `score_fit` needs the normalization
  wired through (prefer routing both sides through the same `resume/select` helper).
- `tests/` — synonym pairs now match (`k8s` portfolio covers `kubernetes` JD, etc.); a
  well-matched JD scores materially higher than a poorly-matched one (and higher than the
  same JD scored before aliasing); a non-aliased token is unaffected (no over-match);
  Korean + ASCII no-regression; the alias table is high-precision (a chosen risky-looking
  non-entry does NOT match).
- `README.md` / fit doc — note synonym matching (single-token, pinned; phrase/embedding
  matching is a documented limitation/follow-up).

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (especially task-021 Unicode and existing `resume/select` /
fit tests); new tests cover single-token synonym matching + no-over-match + no-regression.
Partially addresses #37 (deterministic synonym subset; embedding + phrase + weighting
tracked separately).
