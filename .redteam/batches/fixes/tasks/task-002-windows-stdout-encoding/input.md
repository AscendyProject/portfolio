+++
mode = "agent-pair"
+++

# Task: make inline CLI output work on non-UTF-8 Windows (cp949) — fix the stdout `print(markdown)` encode crash

Refs #16 (third Windows bug). Follow-up to task-001 / PR #17, which fixed the two
**subprocess** bugs (cp949 decode + over-long `claude` argv). Validation then
showed the engine runs end-to-end (`grounded: 12 rejected: 0`), but the **inline
output** still crashes on a Korean (cp949) Windows host:

```
File ".../portfolio/cli.py", line 92, in run
    print(markdown)
UnicodeEncodeError: 'cp949' codec can't encode character '—' in position 12
```

`print(markdown)` writes to a stdout whose encoding is the locale default
(cp949), so non-ASCII markdown (e.g. the em-dash `—` the model emits) cannot be
encoded. The `--out <file>` path already writes UTF-8 via
`write_text(markdown, encoding="utf-8")` and is unaffected — only the inline
(stdout) path is broken.

## Goal
Running any product command **without `--out`** prints its grounded Markdown to
stdout successfully on a cp949 Windows host (non-ASCII characters like `—`, `→`,
`✅` survive), without the user setting `PYTHONUTF8`/`PYTHONIOENCODING`.
Behaviour on a host that already worked (UTF-8) is unchanged, and the `--out`
path is untouched.

## Bug to fix
Inline `print(markdown)` to a non-UTF-8 stdout raises `UnicodeEncodeError`.
Sites (one per CLI):
- `portfolio/cli.py:92`
- `resume/cli.py:103`
- `fit/cli.py:117`
- `rating/cli.py:127`
- `reference_check/cli.py:101`

## What to build
- Make the inline Markdown output emit UTF-8 regardless of the console's locale
  encoding. The exact mechanism is an implementer decision — e.g. write the
  encoded bytes via `sys.stdout.buffer.write(markdown.encode("utf-8"))` (+ a
  trailing newline), or reconfigure the stream
  (`sys.stdout.reconfigure(encoding="utf-8")`) before printing. Apply the **same**
  approach consistently across all five CLIs.
- Prefer a single shared helper over five copies if it can be done without new
  coupling or new dependencies (e.g. a small function in `portfolio/` that the
  others already-importing `portfolio.*` can reuse); otherwise keep the per-CLI
  edit minimal and identical.

## Constraints / hard rules (see project-context + security-checklist)
- Pure output-encoding compatibility fix: do NOT change the Markdown **content**,
  the grounding gate, extraction, or rendering. Behaviour on a UTF-8 host must be
  identical.
- Do NOT change the `--out` path — it already writes UTF-8 correctly.
- No new runtime dependencies. No `shell=True`. Do not touch `.redteam/`.
- Do not re-touch the subprocess call sites fixed in task-001 / PR #17
  (`portfolio/extract.py`, `portfolio/narrative.py`, `rating/cli.py`'s
  `_default_grader_runner`). In `rating/cli.py` this task changes only the
  `print(markdown)` site.

## Out of scope
- The two subprocess bugs (done in PR #17).
- The grounding summary / error messages on `stderr` (they are ASCII today); only
  fix those if the chosen mechanism naturally covers stderr too — do not expand
  scope to reword them.
- Any new feature, flag, or change to the rendered Markdown.

## Affected files
- `portfolio/cli.py`
- `resume/cli.py`
- `fit/cli.py`
- `rating/cli.py` (the `print(markdown)` site only)
- `reference_check/cli.py`
- `(new) tests/test_stdout_encoding.py` — regression test(s) for the inline output path.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
- `verify.sh` gates `ruff` + `pytest` over `portfolio/` + `tests/` **only**. The
  regression tests live under `tests/` and may import the other CLIs. `resume/`,
  `fit/`, `rating/`, `reference_check/` are outside the ruff scope, so keep those
  edits minimal and lint-clean by inspection.
- Suggested red-phase coverage (must fail against current code, pass after fix):
  simulate a non-UTF-8 stdout (e.g. a buffer whose text wrapper uses a cp949-like
  encoding, or monkeypatch the print/stream path) and assert that printing
  Markdown containing `—` does not raise and the UTF-8 bytes are emitted. One test
  per CLI's inline path, or a parametrized test across all five.

## Risks
- Stream reconfiguration (`sys.stdout.reconfigure`) mutates global state; ensure
  it only affects the program's own output and is a no-op / harmless on a stdout
  that is already UTF-8. Writing encoded bytes to `sys.stdout.buffer` avoids
  global mutation but must handle the case where `sys.stdout` has no `.buffer`
  (e.g. when captured) — the test harness must still work.
- Five near-identical edits risk drift; a shared helper (if added without new
  coupling) keeps them consistent. The tests should cover every CLI's inline path
  so a missed one is caught.
