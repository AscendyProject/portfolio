+++
mode = "agent-pair"
+++

# Task: deterministic fit-score quality — stop collapsing all fits to ~26% (issue #37, deterministic part)

## Goal
`fit`'s coverage score is a raw bag-of-words ratio that is structurally low and
useless as a ranking signal — in dogfooding, four very different JDs (Google /
OpenAI / PayPay / Sakana) all scored 26–27 regardless of true fit. Fix the
DETERMINISTIC defects so the score reflects real code-fit and can rank roles.
Scope is the deterministic improvements ONLY; semantic/embedding matching is a
separate follow-up (see Out of scope).

## Why (issue #37)
`coverage% = |JD tokens the portfolio mentions| / |all JD tokens|`, where tokens
come from `jd_keywords()` (`resume/select.py`) — a plain split minus a 38-word
stoplist. Three defects:
1. **Denominator pollution** — JD-file meta-text and junk tokens count as
   requirements (`10`, `s`, `com`, `keywords`, `description`, `job`, `fit`,
   `resume`, `portfolio` — all from the JD-file preamble the harness adds).
2. **Exact-token only** — `migration` ✗ `migrations` (stem variants miss); plus
   true synonyms (`gcp`↔`Google Cloud`) which are OUT OF SCOPE here.
3. **Non-codeable axes counted** — `japanese`, `years`, `bachelor`, `degree`,
   `sales` sit in the denominator and drag code-fit coverage down.

## Part A — clean requirement extraction (defect 1)
Make the JD→requirements step produce real requirements, not file noise:
- Drop meta/preamble lines and JD-format words the harness itself adds (e.g.
  "extracted job description for resume/fit keyword matching", and tokens like
  `job`, `description`, `keywords`, `resume`, `portfolio`, `fit`).
- Drop too-short tokens (length < 2) and pure numbers.
- Deterministic; **preserve the Unicode-aware behavior from task-021** (Korean
  JDs must still produce real keywords — no ASCII or Korean regression).

## Part B — deterministic stemming (defect 2, deterministic part only)
Normalize stem variants deterministically so `migration`/`migrations`,
`deploy`/`deploys`/`deployed`, `container`/`containers` align. Use a small
stdlib-only normalizer (lightweight, pinned suffix stripping) — NOT a stemming
library, NOT embeddings. Apply the SAME normalization to both JD tokens and
portfolio claim tokens so they match on a common stem.

## Part C — non-codeable axis separation (defect 3)
Requirements no code can prove — natural languages (`japanese`, `english`),
experience years (`years`, `3+`), education (`bachelor`, `degree`, `bs`, `ms`) —
must NOT drag the code-fit coverage down. Either exclude them from the coverage
denominator, or report them in a separate "non-code requirements" section that
does not affect the grade. Use a pinned, tested list (same "pinned in code,
a model never contributes" spirit as the existing denylists). This is
fit-specific (do it in `fit/score.py`, not in the shared `jd_keywords`, so
`resume` selection is unaffected unless intentionally shared).

## Hard rules
- **Deterministic**: same (portfolio, JD) → same score. No model call, no new
  dependency, stdlib only.
- **Preserve task-021 Unicode tokenization** (Korean JD still works; existing
  `tests/test_resume_select.py` and `tests/test_jd_keywords_unicode.py` stay
  green).
- **Grounding unchanged**; JD is never persisted as Evidence.
- **Rubric/bands/score math in `fit/grade.py` unchanged** — only the requirement
  set feeding coverage changes. (No weighting in this task — see Out of scope.)

## Out of scope (explicit — separate follow-ups)
- Semantic / synonym / embedding matching (`containerization`↔`kubernetes`,
  `gcp`↔`Google Cloud`). Needs a bounded model/embedding seam — separate task.
- Must-have vs nice-to-have **weighting** and honoring the JD's
  Minimum/Preferred/Tech-stack section STRUCTURE — separate task.
- Batch/ranked output (#38) and JD providers (#41–43).

## Affected files
- `resume/select.py` — `jd_keywords` (and `_claim_tokens` if it mirrors it):
  Part A cleaning + Part B stemming, applied to BOTH JD and claim tokens. Shared
  by resume and fit; keep resume selection behavior sane (improvement, no
  regression of existing assertions).
- `fit/score.py` — `score_fit`: Part C non-codeable axis separation in the
  coverage computation; deterministic.
- `fit/render.py` — only if non-codeable requirements get a separate rendered
  section (must stay i18n/lang-aware per task-021 if so).
- `tests/` — Part A (preamble/junk/short/number tokens dropped), Part B (stem
  variants like `migration`/`migrations` match), Part C (non-codeable axes don't
  drag coverage); a regression proving a WELL-matched JD now scores materially
  higher than a POORLY-matched one (no longer all ~26); Korean + ASCII
  no-regression.
- `README.md` / fit command doc if requirement semantics are documented.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (especially task-021 Unicode and existing
`resume/select` tests); new tests cover the above. Partially addresses #37
(deterministic part; semantic matching tracked separately).
