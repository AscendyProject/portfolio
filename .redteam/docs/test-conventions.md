# Test conventions — portfolio

The test-author and test-verifier read this so generated tests match how the
suite is wired. Keep it accurate; refresh it in the same change if the setup changes.

## Layout
- Tests live in `tests/`, files named `test_*.py` (pytest config in
  `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]`).
- One test file per module under test (`test_extract.py`, `test_grounding.py`,
  `test_narrative.py`, …). No per-package conftest; no shared `conftest.py` yet.
- Each test file makes the package importable with:
  `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` then
  `from portfolio.<module> import ...`.

## How external systems are handled (do NOT hit them in tests)
- **`gh` (network):** never called in tests. Test the PURE parser
  (`parse_pr_evidence`) by passing canned `gh ... --json` output as a JSON string.
  Don't invoke `subprocess`/`gh` from a unit test.
- **`claude` / `codex` (model):** never called in tests. The narrative layer takes
  an injectable `runner: Callable[[str], str]`; pass a fake lambda returning canned
  model text (e.g. `runner=lambda _p: '[{"text": ...}]'`). Don't shell out to a
  real model.

## Core patterns a test author should reach for
- **Grounding tests:** build `Evidence` + `Claim` objects directly and call
  `check_claims`; assert the grounded / rejected / needs_confirmation partition.
  The most important property to keep covered: a hallucinated ref → rejected.
- **Pipeline tests:** `build_from_evidence(subject, evidence, runner=<fake>)` to
  exercise narrate→ground end-to-end without live services. Assert that an invented
  ref never reaches `result.portfolio.claims`.
- **Parser tests:** feed `parse_claims` plain JSON, code-fenced JSON, and malformed
  text; malformed must yield `[]` (never a fabricated claim).

## Async / concurrency
None — the code is synchronous. No `pytest-asyncio`.

## Environment
No special env is required at import. Tests must not depend on `gh`/`claude`/`codex`
being installed or authenticated.

## Gaps the sub-agent should NOT silently fill
- No shared fixtures exist yet; pass objects/fakes directly rather than inventing a
  global `conftest.py`. If a shared fixture becomes warranted, add it to
  `tests/conftest.py` and update this file in the same change.
- Never write a test that calls real `gh`/`claude`/`codex` to "make it pass."
