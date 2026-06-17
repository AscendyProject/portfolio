# Task: /fit — grounded JD match with a deterministic grade + bounded agent score

## Goal
Add a `python -m fit` CLI plus a `/fit` slash command that, given a source (the
same `--source-type` inputs as `/portfolio`) and a job description (JD), reports
**how well the developer's grounded work matches the position** as a **grade +
score (0–100) + reasons**. The design is a **two-tier hybrid**:
1. a **deterministic tier** computes a JD-coverage signal from the grounded
   `Portfolio` and maps it to a **grade (S/A/B/C/D)** that **locks a score band** —
   same evidence → same grade, always; the model cannot escape it;
2. an **agent tier** (the injectable model `runner`, called deterministically /
   temperature 0) picks the **precise score inside the locked band** and writes the
   qualitative reasoning — using ONLY grounded evidence (the grounding gate is
   re-applied to its output; the score is clamped into the band).

## Why this matters (hard constraint, not a nicety)
A "% fit" is where a tool is tempted to let a model guess a flattering number. Here
the **grade is evidence-locked and deterministic**, so the model can refine *within*
the band but can never overclaim the tier:
- The **coverage signal is deterministic**: overlap between `resume.select.jd_keywords(jd)`
  and grounded claim/evidence tokens, with the same defensive grounding re-check as
  `resume.select.enforce_grounding` (a claim contributes only if its `evidence_refs`
  are non-empty AND ⊆ the portfolio's evidence refs; hallucinated-ref claims are
  ignored). This signal → grade is a pure function (no model).
- The **agent only acts inside the locked band**: it receives the grounded evidence
  + the locked grade + the band's `[min,max]`, returns a score in that range and
  reasoning that cites real evidence refs. Its score is **clamped** to the band
  defensively (out-of-range / malformed → clamp to the band, e.g. midpoint). Its
  reasoning is **grounding-checked** — any sentence citing a ref not in the
  portfolio's evidence is dropped, never shipped.
- Reproducibility: the **grade + band are fully reproducible**; only the within-band
  score and reasoning wording may vary, minimized by calling the runner at
  temperature 0 with a fixed prompt.

## Grade → score band (fixed rubric, pinned in code, shown in output)
| Grade | Score band |
|------|------------|
| S | 96–100 |
| A | 85–95 |
| B | 70–84 |
| C | 55–69 |
| D | 0–54 |

Deterministic **coverage% → grade** thresholds (planner pins exact cutoffs; pin in
tests; recommended starting point): `≥90 → S`, `≥75 → A`, `≥55 → B`, `≥35 → C`,
`else D`. The coverage% itself is also shown in the report (transparent anchor).

## What to build
Mirror the `resume` / `reference_check` command shape; do NOT modify `portfolio/`
internals or `resume/select.py`.

1. `python -m fit` CLI (`fit/__main__.py` + `fit/cli.py`):
   `python -m fit --source-type {github|web} --source <URL> --author <handle> --jd <path> [--out FILE]`.
   Builds a grounded `Portfolio` (reuse `portfolio.pipeline`; pipeline's narrative
   `runner` stays injectable), computes the deterministic coverage + grade, calls the
   agent grader for the within-band score + reasoning, renders Markdown to stdout (or
   `--out`), and emits the one-line grounding summary on stderr — mirroring `resume.cli`.
2. The deterministic grader (`fit/score.py`): pure function `(Portfolio, jd_text) ->`
   coverage set / covered keywords (each with the grounded evidence ref(s) covering
   it) / gaps / coverage% / **grade + band**. No model, network, subprocess, file I/O.
   Reuse `resume.select.jd_keywords` and replicate the same `claim.text + evidence_refs`
   tokenizer rule locally (do NOT promote `resume.select._claim_tokens` to public).
3. The bounded agent grader (`fit/grade.py`): given the grounded claims/evidence + the
   locked grade + its `[min,max]`, calls a **new `grader_runner` seam defined for this
   feature** — its signature explicitly accepts temperature (e.g.
   `grader_runner(prompt, *, temperature=0) -> str`), and `grade.py` always calls it
   with `temperature=0` and a fixed prompt. This is a SEPARATE seam from the shared
   `portfolio.narrative` `Runner` (`Callable[[str], str]`), which is NOT modified; the
   default `grader_runner` wraps the model, and tests inject a fake that records the
   `temperature` it was called with. It parses a structured result: an integer score +
   reasoning bullets each tagged with `evidence_refs`. Then: **clamp** the score into
   `[min,max]`; **grounding-check** each reasoning bullet (drop any whose refs ⊄
   portfolio evidence); defensive parse (malformed → clamp to band midpoint +
   empty/safe reasoning, never crash, never fabricate). The model may NOT change the
   grade. (The band is the reproducibility guarantee; `temperature=0` is enforced at
   this seam's contract — no change to the shared `Runner`.)
4. A deterministic renderer (`fit/render.py`, reuse `portfolio.render._escape`): grade
   + score + the coverage% + Covered requirements (with grounded refs) + Gaps +
   grounded reasoning bullets + the transparent rubric table. No model call here.
5. `/fit` slash command (`.claude/commands/fit.md`) modeled on `resume.md`: argv-only
   invocation, hard-rule clause forbidding shell string assembly.
6. README `/fit` section: documents the hybrid (deterministic grade locks the band;
   agent refines within; reasoning grounded) and that it is a rubric assessment, not a
   holistic "you are N% qualified" judgment.

## Constraints / hard rules (see project-context + security-checklist)
- **The grade is deterministic and evidence-locked.** The model picks a score only
  *inside* the locked band and never changes the grade. Same grounded portfolio + JD
  → same grade + band, always (pinned in tests).
- **The agent's score is clamped; its reasoning is grounding-checked.** Out-of-range
  or malformed model output → clamp to the band, drop ungrounded reasoning. Never let
  the model escape the band or introduce an un-grounded fact.
- **`grader_runner` is a new, feature-local injectable seam whose signature takes
  `temperature` (default 0); `grade.py` always calls it with `temperature=0`.** Do NOT
  modify the shared `portfolio.narrative` `Runner` contract. Tests inject a fake that
  records the temperature. The deterministic band — not the model call — is the
  reproducibility guarantee.
- Do NOT modify `resume/select.py` or `portfolio/` internals. Import and reuse.
- **No shell string-building.** argv lists everywhere; never interpolate untrusted
  text into a command string.
- Stdlib-only engine; no new runtime dependency; no embeddings/semantic library.

## Out of scope
- The model judging or changing the **grade** (the grade is deterministic).
- Semantic/embedding similarity; JD-structure parsing (must-have vs nice-to-have);
  requirement weighting beyond flat keyword coverage (v1).
- A `rating` feature; PDF/HTML; live JD URL fetch (`--jd` is a path).
- Modifying `resume`/`portfolio` internals; new runtime dependency.

## Affected files
- `(new) fit/__init__.py`
- `(new) fit/__main__.py` — `python -m fit` entrypoint
- `(new) fit/cli.py` — argparse + pipeline → deterministic score/grade → agent grade → render; injectable extractor/runner/fetcher + grader_runner seams
- `(new) fit/score.py` — pure deterministic coverage + grade
- `(new) fit/grade.py` — bounded agent grader (clamp + grounding-check + defensive parse)
- `(new) fit/render.py` — Markdown report (reuse `portfolio.render._escape`)
- `(new) .claude/commands/fit.md` — `/fit` slash command
- `(new) tests/test_fit.py` — deterministic-grade + clamp + grounding tests (inject all seams; build Portfolio/Claim/Evidence directly; no live services)
- `README.md` — document `/fit`

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (inject seams incl. a fake `grader_runner`; no `gh`/`claude`/network) must
cover: the **grade + band are deterministic** (same portfolio+JD → identical grade
& band across calls; pin coverage%→grade); a covered keyword cites real evidence and
a hallucinated-ref claim is ignored (gap, not covered); the agent **score is clamped**
into the band (a fake runner returning a score above/below the band yields a score at
the band bound/midpoint — never outside); a reasoning bullet citing a non-evidence ref
is dropped and never appears in output; a malformed grader_runner response yields a
clamped score + safe reasoning (no crash, no fabricated fact); `--out` writes the file
and stdout stays clean; grounding summary on stderr only; bad/unsupported `--source`
exits non-zero without invoking the extractor; `.claude/commands/fit.md` passes user
values as separate argv tokens and forbids shell string assembly.

## Risks
- **Within-band non-determinism.** The final score may vary slightly run-to-run (the
  agent layer); the **grade/band is the reproducible guarantee**. Mitigated by temp=0
  + fixed prompt. Confirm this tradeoff is acceptable (it was approved at the gate).
- **coverage%→grade cutoffs.** The `≥90/75/55/35` cutoffs are a recommendation; pin
  exact values in `fit/score.py` and tests; human may tune at the gate.
- **Tokenizer reuse.** Replicate `resume.select`'s claim tokenizer rule in `fit/score.py`
  (don't make `_claim_tokens` public); keep it identical.
- **`verify.sh` does not lint the new package** (same as `resume`/`reference_check`).
