+++
mode = "agent-pair"
+++

# Task: mask/refuse private evidence BEFORE any model call + close the ref-bypass (codex IR-001 / IR-003, follows #58)

## Goal
PR #58 added `assert_maskable` to fail closed on non-github.com hosts under
`--mask-private`, but two gaps remain:

- **IR-001 (model leak — the critical one):** `resolve_and_optionally_mask`
  (`portfolio/pipeline.py`) orders work as `extract → narrate(MODEL) → ground →
  mask → synthesize`. Both the refusal check (`assert_maskable`) and masking happen
  AFTER narrate, so a private GHES repo's raw evidence is sent to the model BEFORE
  the run is refused/anonymized. The masking guarantee must hold before ANY model
  call.
- **IR-003 (ref bypass):** `assert_maskable` (`portfolio/mask.py`) inspects only
  `ev.url`. Evidence with no `url` but a non-github.com host encoded in `ev.ref`
  (a GHES `host/owner/repo…` ref) passes the guard, so a private GHES identifier
  can survive.

## Part A — refuse before the first model call (IR-001)
On the `mask_private=True` path in `resolve_and_optionally_mask`, call
`assert_maskable` on the EXTRACTED evidence (the `resolved.extract()` output)
BEFORE narrate / `resolve_to_build_result` and before any synthesis. A
non-maskable host must raise `MaskingError` with **zero prior model invocations**.
The github.com path is unchanged (assert_maskable passes, then the existing
`extract → narrate → ground → mask → synthesize` order runs as today).
- Assert with a **counting fake runner**: when `assert_maskable` raises, the
  runner (and synthesis_runner) were never called.

## Part B — check structured ref provenance, not just url (IR-003)
`assert_maskable` must reject a non-github.com host found in `ev.ref` too, not only
`ev.url`. Parse the ref's host the same way the masking layer already derives repo
names (a GHES ref is `host/owner/repo…`; a github.com-origin ref is a bare
`owner/repo…` with no leading host label). Evidence whose ref carries a
non-github.com host is refused even when `ev.url` is empty. Keep the
`kind == "article"` exemption (web articles are public content, not repos).
- Tests: a url-less evidence with a GHES ref is refused; a bare `owner/repo#1`
  github.com ref passes; existing github.com masking is byte-identical.

## Hard rules
- Deterministic; stdlib only; no new dependency.
- **The masking guarantee:** on `--mask-private`, NO private / non-github.com
  evidence reaches a model runner — proven by a counting-runner test that the
  runner is never called when the guard refuses.
- github.com portfolios mask EXACTLY as today (existing `tests/test_mask.py`
  assertions stay green / byte-identical).
- Do not change the rubric/scoring; do not weaken grounding; `assert_maskable`
  stays a hard fail-closed (refuse, never best-effort).

## Out of scope
- **Real GHES masking end-to-end** (host-qualified discovery + `gh repo view`
  visibility + relabel + stored-schema migration) — that is codex IR-004, a
  separate larger task. This task only (a) moves the refusal before the model and
  (b) closes the ref-based bypass of the existing fail-closed guard.
- Free-text-only GHES identifiers in `detail` / `context` / `claim.text` that have
  no structured `ref`/`url` — covered by the IR-004 real-masking work; leave a
  code comment marking this residual.
- SSRF host parsing (IR-002 / IR-005) — separate task (PR #67).

## Affected files
- `portfolio/pipeline.py` — `resolve_and_optionally_mask`: invoke `assert_maskable`
  on the extracted evidence before narrate / synthesis (before any runner call) on
  the mask_private path.
- `portfolio/mask.py` — `assert_maskable`: also inspect the host encoded in
  `ev.ref` (not only `ev.url`); refuse url-less GHES refs; keep the article exemption.
- `tests/test_mask.py` — (1) runner never called when assert_maskable raises
  (model-leak guard, counting runner); (2) url-less GHES ref refused; (3) bare
  github.com ref passes; (4) existing github.com masking unchanged.
- `README.md` / `CHANGELOG.md` — document the "refuse before model" ordering and
  the ref-provenance check.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green; new tests cover the model-leak ordering (Part A)
and the ref-bypass (Part B). Addresses codex IR-001 and IR-003 (IR-004 real GHES
masking is a separate task).
