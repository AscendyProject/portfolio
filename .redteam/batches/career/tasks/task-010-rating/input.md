# Task: /rating — grounded capability grade + bounded agent score (no global percentile)

## Goal
Add a `python -m rating` CLI plus a `/rating` slash command that produce a
**capability assessment** for `--author` from their real, grounded work: a **grade
(S/A/B/C/D) + score (0–100) + reasons**, via the same **two-tier hybrid** as `/fit`:
1. a **deterministic tier** computes evidence-derived metrics (volume, breadth,
   stack diversity) from the grounded `Portfolio`, maps them to per-dimension bands,
   and combines them into an **overall grade** that **locks a score band** — same
   evidence → same grade, always;
2. an **agent tier** (the injectable model `runner`, temperature 0) picks the
   **precise score inside the locked band** and writes the qualitative reasoning,
   drawing ONLY on grounded claims (grounding gate re-applied; score clamped).

**This is NOT an absolute percentile.** The score is a self-contained rubric
assessment bounded by an evidence-derived grade — it must **not** claim "top X% of
all engineers", a global ranking, or a comparison to any population (no baseline
exists). The grade/band is the honest, reproducible anchor.

## Why this matters (the sharpest grounding boundary)
The original ask was "rank me / top %". A model asserting "top 5%" is exactly the
overclaim this product prevents. The hybrid keeps it honest:
- The **grade is deterministic** from evidence metrics — the model cannot inflate the
  tier. Every metric is traceable to the `Evidence` it came from.
- The **agent acts only inside the locked band**: score clamped to `[min,max]`;
  reasoning/highlights drawn only from grounded claims and citing real refs;
  grounding-checked (un-grounded reasoning dropped). Defensive parse (malformed →
  clamp to band midpoint + safe reasoning, never crash, never fabricate).
- **No population claim**: the rendered output must contain no percentile / global
  ranking wording (assert absence of `top `, `%ile`, `percentile`, `rank`,
  `better than`, `out of all`, `globally`, `talent score`).

## Grade → score band (fixed rubric, pinned in code, shown in output)
| Grade | Score band |
|------|------------|
| S | 96–100 |
| A | 85–95 |
| B | 70–84 |
| C | 55–69 |
| D | 0–54 |

The deterministic **metrics → overall grade** mapping (e.g. per-dimension bands give
points, summed → grade thresholds) is pinned by the planner in `rating/profile.py`
and in tests; recommended dimensions and starting bands below.

## What to build
Mirror the `resume` / `reference_check` / `fit` shape; do NOT modify `portfolio/`
internals or `resume/select.py`.

1. `python -m rating` CLI (`rating/__main__.py` + `rating/cli.py`):
   `python -m rating --source-type {github|web} --source <URL> --author <handle> [--out FILE]`.
   Builds a grounded `Portfolio` (reuse `portfolio.pipeline`), computes the
   deterministic metrics + grade, calls the agent grader for the within-band score +
   reasoning, renders Markdown to stdout (or `--out`), grounding summary on stderr.
2. The deterministic profiler (`rating/profile.py`): pure function over a grounded
   `Portfolio` → metrics + per-dimension bands + overall grade + band. No model /
   network / subprocess / file I/O. Recommended metrics (planner pins exact bands):
   - **volume** = count of grounded `Evidence(kind="pr")` → e.g. Low 1–4 / Steady 5–19 / High 20+
   - **breadth** = distinct `Evidence(kind="file")` refs → e.g. Narrow 1–9 / Moderate 10–29 / Wide 30+
   - **stack diversity** = distinct languages via a fixed extension→language table pinned here → Focused 1 / Versatile 2–3 / Polyglot 4+
   - **recency is omitted** (`Evidence` has no date field — do not fabricate one).
   Each metric cites the exact evidence refs it was computed from.
3. The bounded agent grader (`rating/grade.py`): given grounded claims/evidence + the
   locked grade + `[min,max]`, calls the injectable `grader_runner` **deterministically
   (temperature 0, fixed prompt)**, parses a structured score + reasoning bullets each
   tagged with `evidence_refs`; **clamp** the score to the band; **grounding-check** the
   reasoning (drop bullets whose refs ⊄ portfolio evidence); defensive parse. The model
   may NOT change the grade and may NOT emit a percentile/ranking.
4. A deterministic renderer (`rating/render.py`, reuse `portfolio.render._escape`):
   grade + score + the per-dimension metrics (each with evidence refs + band) +
   grounded reasoning/highlights + the transparent rubric. Emits NO percentile/ranking
   wording.
5. `/rating` slash command (`.claude/commands/rating.md`) modeled on `resume.md`:
   argv-only, hard-rule clause forbidding shell string assembly, explicit "no absolute
   percentile/ranking" wording.
6. README `/rating` section: grounded capability grade; explicitly states it does NOT
   produce an absolute percentile / global ranking.

## Constraints / hard rules (see project-context + security-checklist)
- **No un-grounded percentile or ranking.** No "top X%", no global comparison, no
  population baseline. A reviewer finding such wording in the output is a HIT.
- **The grade is deterministic and evidence-derived.** Same grounded portfolio →
  identical metrics, bands, and grade. The model never changes the grade.
- **The agent's score is clamped; reasoning/highlights are grounding-checked.**
  Out-of-range/malformed → clamp; un-grounded reasoning dropped; never fabricate a
  strength or a metric. Omit a dimension that can't be computed (e.g. recency) rather
  than estimate it.
- **Call the grader runner deterministically (temperature 0).** Injectable seam; tests
  use a fake — no live CLI/network.
- Do NOT modify `resume/select.py` or `portfolio/` internals. Import and reuse.
- **No shell string-building.** argv lists everywhere.
- Stdlib-only engine; no new runtime dependency.

## Out of scope
- ANY absolute percentile, global rank, or comparison to other engineers / a population.
- The model judging or changing the **grade**, or inventing a metric/dimension.
- A `fit` feature; industry benchmarking; salary bands; PDF/HTML.
- Adding a recency dimension by inferring dates not on `Evidence`.
- Modifying `resume`/`portfolio` internals; new runtime dependency.

## Affected files
- `(new) rating/__init__.py`
- `(new) rating/__main__.py` — `python -m rating` entrypoint
- `(new) rating/cli.py` — argparse + pipeline → profile/grade → agent grade → render; injectable extractor/runner/fetcher + grader_runner seams
- `(new) rating/profile.py` — pure deterministic metrics + bands + overall grade; fixed extension→language table
- `(new) rating/grade.py` — bounded agent grader (clamp + grounding-check + defensive parse)
- `(new) rating/render.py` — Markdown scorecard (reuse `portfolio.render._escape`); no percentile/ranking wording
- `(new) .claude/commands/rating.md` — `/rating` slash command
- `(new) tests/test_rating.py` — deterministic-grade + clamp + grounding + no-percentile tests (inject all seams; build Portfolio/Claim/Evidence directly; no live services)
- `README.md` — document `/rating`

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (inject seams incl. a fake `grader_runner`; no `gh`/`claude`/network) must
cover: **deterministic grade** (same portfolio → identical metrics, bands, grade &
band across calls); metric correctness (PR/claim/file counts equal the fixture;
language mix via the pinned table, unknown ext → "other", never guessed); recency
dimension absent; the agent **score is clamped** into the band (fake runner returning
out-of-band → score at bound/midpoint); a reasoning/highlight citing a non-evidence
ref is dropped; a malformed grader_runner response yields a clamped score + safe
reasoning (no crash, no fabrication); the rendered body contains NONE of `top `/
`percentile`/`rank`/`better than`/`out of all`/`globally`/`talent score`
(case-insensitive); `--out` writes the file and stdout stays clean; grounding summary
on stderr only; bad/unsupported `--source` exits non-zero without invoking the
extractor; `.claude/commands/rating.md` passes user values as separate argv tokens,
forbids shell string assembly, and states no-absolute-percentile.

## Risks
- **Within-band non-determinism.** The final score may vary slightly run-to-run; the
  **grade/band is the reproducible guarantee** (mitigated by temp=0). Approved at gate.
- **metrics→grade mapping.** The per-dimension bands and the points→grade thresholds
  are a recommendation; pin exact values in `rating/profile.py` + tests; human may tune.
- **Language/extension table** is fixed and small; pinned in code + tests (no model guess).
- **"score is not a percentile" framing.** The 0–100 score is a rubric assessment, not a
  population percentile; render/README/command must make this explicit. Confirm wording.
- **`verify.sh` does not lint the new package** (same as `resume`/`reference_check`/`fit`).
