# Task: /resume core — match a grounded Portfolio to a job, with honesty checks

## Goal
Add a `resume` module that takes an already-grounded `Portfolio` (from the
`/portfolio` pipeline) plus a target job description (JD) and produces a
**tailored, evidence-grounded resume draft** — selecting and ordering the
portfolio's grounded claims to fit the JD, WITHOUT introducing any un-grounded or
exaggerated claim. This is the first, deterministic-first slice of `/resume`; the
LLM tailoring layer comes in a later task.

## Why this matters (hard constraint, not a nicety)
A resume is exactly where overclaiming happens. The product's value is that every
resume bullet still traces to real evidence. So this slice builds the
**deterministic selection + honesty gate**, not the prose generation:
- a resume may ONLY include claims that are already on `portfolio.claims` (the
  grounded set). It must never invent a claim, never add evidence, never raise a
  claim's confidence.
- the JD is used to SELECT and RANK existing grounded claims (by keyword/skill
  overlap), not to fabricate new ones.

## What to build
Add `resume/` as a new package (with `__init__.py`), or a `resume.py` module —
implementer's choice, but it must NOT modify anything under `portfolio/`.

1. A small JD model: parse a plain-text JD into a set of normalized keywords/skills
   (a deterministic tokenizer is fine — lowercase, split on non-alphanumerics,
   drop a small stopword set). Pure function, e.g. `jd_keywords(jd_text) -> set[str]`.
2. A selection function:
   `select_claims(portfolio, jd_keywords, top_n) -> list[ScoredClaim]` that scores
   each grounded claim by overlap between the JD keywords and the claim's own
   text/evidence tokens, returns them ranked, highest first, capped at `top_n`.
   Deterministic and pure. Ties broken stably (e.g. by original order).
3. A `ResumeDraft` dataclass: subject + the selected `ScoredClaim`s + the JD
   keywords matched. Each selected claim must still carry its original
   `evidence_refs` (grounding is preserved end to end).
4. An honesty/grounding re-check: a function that verifies every claim chosen for
   the resume is present in `portfolio.claims` AND its evidence_refs are a subset
   of the portfolio's evidence refs — i.e. the resume cannot smuggle in a claim or
   ref that wasn't grounded. If any chosen claim fails, it is dropped (fail
   closed), never included.

## Constraints / hard rules (see project-context + security-checklist)
- Deterministic and **stdlib only** — this slice calls NO model, NO `gh`, NO
  network, NO subprocess. (The LLM tailoring layer is a separate later task.)
- Do NOT modify `portfolio/extract.py`, `narrative.py`, `grounding.py`,
  `pipeline.py`, `model.py`, or `render.py`. Import from `portfolio.model` /
  `portfolio.grounding` as needed; reuse, don't duplicate.
- The grounding invariant is the security boundary: a resume claim that is not in
  the grounded portfolio set, or cites a ref not in the portfolio's evidence, must
  be rejected — never shipped.

## Out of scope
- LLM-based rewriting/tailoring of bullet wording (later task).
- Rendering the resume to Markdown/PDF (later task — can reuse the render approach).
- Cover letters, interview questions, gap analysis.
- Live JD fetching from a URL.

## Affected files
- `(new) resume/__init__.py`
- `(new) resume/select.py` (JD keywords + selection + ResumeDraft + honesty re-check)
- `(new) tests/test_resume_select.py`

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (build `Portfolio`/`Claim`/`Evidence` directly, no live services) must cover:
JD keyword extraction; selection ranks claims by JD overlap and caps at top_n with
stable tie-breaking; a claim NOT in `portfolio.claims` can never appear in the
resume; a claim whose evidence_refs are not a subset of the portfolio's evidence
is dropped by the honesty re-check; selection preserves each claim's evidence_refs.

## Risks
- Keyword overlap scoring is a simple heuristic; keep it deterministic and tested,
  don't over-engineer (no TF-IDF/embeddings in this slice).
- Stopword list and tokenization are small design choices — pick simple, pin in tests.
