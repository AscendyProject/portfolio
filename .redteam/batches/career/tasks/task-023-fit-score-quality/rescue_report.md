# Rescue report — task-023 (deterministic fit-score quality, issue #37)

## Why rescue was entered
After implement (round 2), review_code (codex) returned CHANGES_REQUESTED with
IR-001/IR-002 open. With `retries["implement"] >= 2` the orchestrator routed to
rescue. The implementation worked (verify green, 676 passed); the findings were
test-quality gaps.

## Findings and resolutions

### IR-002 (major) — claim-cleaning tested only indirectly — RESOLVED
The claim-cleaning tests checked `_claim_tokens` only via `select_claims`, which
intersects claim tokens with an already-cleaned JD set — so they passed vacuously
(junk claim tokens could never surface in `matched_keywords` even with a no-op
cleaner). Fixed: `_claim_tokens` is now imported and called DIRECTLY; the two tests
assert on `_claim_tokens(claim)`'s own output (no JD intersection) that a Claim
mixing a preamble line + meta stopwords + len<2 + pure-digit + real tokens yields
only the real stems and none of the junk. These fail against a no-op pre-change
`_claim_tokens`.

### IR-001 (major) — two non-discriminating new tests — RESOLVED
- `test_korean_jd_passes_through_part_a_and_b_unchanged` REMOVED — Korean
  no-regression is covered by the existing `tests/test_jd_keywords_unicode.py`
  (green under verify.sh after Parts A/B; Part A removes only ASCII meta tokens,
  Part B `_stem` is identity on non-ASCII).
- `test_no_forbidden_stemming_packages_in_source` REMOVED — "no new stemming
  dependency" is an inherently negative guard that passes pre-change; moved to a
  REVIEWER check against the branch diff (outcome.md updated, consistent with the
  PR-004 pattern). Positive proof that `_stem` is stdlib-only is the Part B
  stemming tests.

### IR-003 (major, raised in clean re-review) — outcome/test mismatch — RESOLVED
After removing the Korean passthrough test, outcome.md still listed a Done-when
item requiring "a new Korean test". Updated that item to designate the existing
`tests/test_jd_keywords_unicode.py` as the Korean no-regression guard (a fresh
passthrough test would be non-discriminating, cf. IR-001) — outcome and tests now
agree. Outcome-only change; no code/test behavior change.

## Verification
- `bash .redteam/scripts/verify.sh` → **674 passed, 1 skipped** (ruff + format + pytest).
- Clean codex re-review (read-only, working tree): IR-001 & IR-002 RESOLVED; IR-003
  was the outcome/test-mismatch above, now fixed in outcome.md.
- Scope: `resume/select.py` (Part A/B), `fit/score.py` (Part C), and
  `tests/test_fit_score_quality.py`. `fit/grade.py` (rubric/bands) untouched;
  grounding unchanged; JD never persisted as Evidence; no new dependency.

## Outcome
Converged. `/fit`'s deterministic coverage no longer collapses every JD to ~26%:
JD preamble/meta/short/digit tokens are dropped, English stem variants align
(`migration`↔`migrations`), and non-codeable axes (language/years/degree/sales)
are excluded from coverage (surfaced as `ScoreResult.non_code_requirements`). A
well-matched JD now scores materially higher than a poorly-matched one. Semantic
matching, weighting, batch/ranked output, and JD providers remain separate
follow-ups. Partially addresses #37 (deterministic part).
