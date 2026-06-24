+++
mode = "agent-pair"
+++

# Task: fit batch scoring + ranked output (--jd-dir) — enable reverse fit (issue #38)

## Goal
`fit` scores ONE portfolio against ONE JD today (`--jd <path>` required;
`fit/cli.py`, `fit/score.py:score_fit`). To answer "which of these N positions
fits me best?" a user must run the command N times by hand. Add batch input + a
ranked table, building the portfolio ONCE and scoring it against every JD. This
is the enabling capability for reverse fit (#40); it pairs with the now-meaningful
coverage score (#37, just landed).

## Part A — batch input (`--jd-dir`)
- Add `--jd-dir <dir>`: score the built portfolio against EVERY JD file in the
  directory. Pin the accepted extensions (e.g. `*.txt` and `*.md`); ignore others;
  deterministic file ordering (sorted by filename).
- `--jd <path>` (single) keeps its CURRENT behavior and output byte-identical.
- `--jd` and `--jd-dir` are mutually exclusive; exactly one is required — clean
  single-line exit-2 message if both are given or neither.
- An empty `--jd-dir` (no matching files) is a clean exit-2 message, not a crash.

## Part B — build the portfolio ONCE, score per JD
- Resolve/extract the portfolio source ONCE (extraction is the slow part — today
  it is rebuilt per invocation) and reuse the same in-memory `Portfolio` to
  `score_fit` against each JD. Do NOT re-extract per JD.
- Reuse the existing `score_fit` unchanged — batch just calls it per JD and
  collects the `ScoreResult`s.

## Part C — ranked output
- Emit a ranked table sorted **best-first** by score, tiebroken by coverage%,
  then by JD filename (stable, deterministic). Columns:
  `JD | Grade | Score | Coverage% | Top Gaps` — Top Gaps = the first N gap tokens
  per JD (N pinned, e.g. 5).
- The table UI strings (column headers, any labels) come from the task-021 `LANGS`
  i18n table so `--lang ko` localizes them; no hardcoded English UI in the table.
  Table-header language follows `--lang` (default `en`); JD filenames and gap
  tokens are data (language-neutral).
- Deterministic: same (portfolio, JD set, lang) → byte-identical table.

## Hard rules
- Deterministic; stdlib only; no new dependency; argv-only.
- Grounding unchanged; JD is NEVER persisted as Evidence (each JD is scored, not
  stored).
- `score_fit` and `fit/grade.py` rubric/bands/score math are UNCHANGED — batch
  calls the existing scorer per JD and ranks the results.
- **Single-`--jd` behavior and output stay byte-identical** (golden tests).
- i18n: ranked-table headers localize via the task-021 `LANGS` table; the
  no-English-leak contract holds for `--lang ko`.

## Out of scope
- JD providers / job discovery (#41–#43) — `--jd-dir` consumes LOCAL files only.
- Semantic matching and must-have/nice-to-have weighting (separate #37 follow-ups).
- Changing `score_fit` math, the rubric, or `fit/grade.py`.
- Reverse-fit job-discovery seam (#40) — this task is local batch + rank only.

## Affected files
- `fit/cli.py` — `--jd-dir` arg + mutual-exclusion/required validation, build the
  portfolio once, per-JD scoring loop, dispatch to ranked rendering.
- `fit/render.py` — ranked-table renderer (lang-aware via `LANGS`).
- `portfolio/i18n.py` — new UI strings for the ranked table (column headers) in
  both `en` and `ko`, with the existing completeness/no-leak tests covering them.
- `tests/` — `--jd-dir` scores N JDs; ranked best-first (+ tiebreak); the
  portfolio is built ONCE (assert the extractor/runner is invoked once, not N
  times, e.g. via a counting fake); single-`--jd` output unchanged; mutual-
  exclusion and empty-dir exit-2; `--lang ko` localizes headers with no English
  leak; determinism (same inputs → identical table).
- `.claude/commands/fit.md` + `README.md` — document `--jd-dir` and the ranked
  output.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (especially the single-`--jd` golden output and the
task-021 i18n/no-leak tests); new tests cover the above. Closes #38.
