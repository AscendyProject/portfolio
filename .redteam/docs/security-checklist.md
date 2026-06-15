# Security checklist — portfolio

The code-security-reviewer applies this to every diff. Each item is a **hard
line**: a confirmed HIT escalates to `REVIEW_DECISION: CHANGES_REQUESTED`. Don't
relax it for "small" changes.

## 1. The grounding boundary (this product's core trust gate)
- [ ] **No un-grounded claim can ship.** Any code path that produces a portfolio/
      resume `Claim` for output must pass it through the grounding check; a claim
      citing no evidence, or citing a ref not in the extracted `Evidence` set, must
      be rejected — never shipped or silently "fixed".
- [ ] **The grounding check stays deterministic.** It verifies that cited refs
      exist in the evidence corpus; it must NOT ask a model whether a claim is
      "true", and must NOT be weakened to accept partial/looser matches.
- [ ] **A hallucinated ref poisons the whole claim.** If a claim cites several
      refs and any one is not real, the claim is rejected (no "keep the good refs").

## 2. Deterministic vs LLM separation
- [ ] **`extract` and `grounding` never call a model.** Only `narrative` may shell
      out to `claude`/`codex`. A model call leaking into the deterministic layers
      is a HIT.
- [ ] **Evidence is only produced by extraction.** Narrative/render code must not
      synthesize `Evidence` records.

## 3. Model output is untrusted input
- [ ] **Parse model output defensively.** Malformed/partial output → drop, never
      fabricate a claim or a ref. The grounding gate is the guard, not model honesty.
- [ ] **No model output reaches a shell/path/command** via string interpolation.

## 4. Subprocess / shell
- [ ] **No `shell=True`; all `gh`/`claude`/`codex` calls are argv lists.** No
      interpolation of untrusted text (handles, repo names, JD text) into a command
      string. Repo/author args go as separate argv items.
- [ ] **Non-zero subprocess exit is handled** (raise/῾report), not silently treated
      as success.

## 5. Secrets and logs
- [ ] **No secrets in logs, commits, or error output** (tokens, `.env*`, keys). `gh`
      auth tokens must never be printed or written.
- [ ] **No PII beyond what the user supplied** is persisted or logged.

## 6. Input handling
- [ ] **Path/ref handling is safe.** A file path or ref coming from `gh` output is
      used as data (compared, rendered-escaped), never executed or joined into a
      filesystem write without bounding.
- [ ] **Render escaping.** Any claim/evidence text rendered into Markdown/HTML output
      is escaped appropriately (a malicious repo/PR title must not break the output).

## 7. Tooling
- [ ] **No weakening of tests / ruff** to pass the gate (`# noqa`, `xfail`, `skip`,
      deleted assertions) without an explicit per-line justification.
- [ ] **No new runtime dependency** (engine is stdlib-only) without a stated reason.
