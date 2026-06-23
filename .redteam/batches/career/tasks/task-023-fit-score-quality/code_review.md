## redteam adversarial review (codex · agent-pair)
Reviewed `git diff main...HEAD` against project hard rules, security checklist, and task artifacts (`outcome.md`, `plan_review.md`, `impl_diff.patch`, `verification.log`, `state.json`).

---

IR-001 severity:major status:open

Two new tests would pass against the pre-change implementation: `test_no_forbidden_stemming_packages_in_source` and `test_korean_jd_passes_through_part_a_and_b_unchanged`. The review contract requires every new test to demonstrably fail before the change.

IR-002 severity:major status:open

The claim-cleaning tests do not prove claim-side cleaning. They intersect claim tokens with an already-cleaned JD keyword set, so meta, short, and numeric claim tokens cannot appear in `matched_keywords` even if `_claim_tokens` remains unchanged. Test `_claim_tokens` directly or supply an independently constructed keyword set containing the prohibited tokens.

New-test justification: Tests covering newly introduced constants, helpers, stemming, non-code separation, ranking, and preamble handling fail against pre-change code. The two tests in IR-001 do not. Claim-cleaning tests are insufficient for the stated acceptance criterion as described in IR-002.

Verification: `verification.log` exists; `state.verification.last_exit_code` is `0`. The recorded run reports ruff clean and 676 passed, 1 skipped. `impl_diff.patch` matches `git diff main...HEAD`. No dependency, subprocess, network, secret-handling, evidence-construction, grounding-gate, or `fit/grade.py` changes were found.

REVIEW_DECISION: CHANGES_REQUESTED
