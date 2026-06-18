+++
mode = "agent-pair"
+++

# Task: make the product CLIs run on non-UTF-8 Windows (cp949) — fix subprocess decode + over-long argv

Fixes #16. Two distinct Windows-compatibility bugs make every product command
(`/portfolio`, `/resume`, `/reference-check`, `/fit`, `/rating`) fail before
producing output on a Korean (cp949) Windows host. Both are bug classes the
vendored `.redteam/` harness already fixed (it pins `encoding="utf-8"`
everywhere — see `.redteam/workflows/phase_runners/_base.py:184`); the product
packages never got the same treatment.

## Goal
The product CLIs run end-to-end on a Windows host whose default code page is
**not** UTF-8 (cp949), without requiring the user to set `PYTHONUTF8=1`:

1. Child-process output (from `gh` and from the narrative model) is decoded as
   **UTF-8**, so non-ASCII (e.g. Korean PR titles) no longer crash the run.
2. The narrative prompt is **not** passed as a command-line argument, so a large
   grounded-evidence prompt no longer exceeds the Windows command-line length
   limit (`WinError 206`).

## Bugs to fix

### Bug 1 — `subprocess.run(text=True)` without `encoding=`
Decodes child stdout/stderr with the locale default (cp949), not UTF-8. On the
first non-ASCII byte the reader thread raises
`UnicodeDecodeError: 'cp949' codec can't decode byte 0xed ...`; stdout then comes
back `None` and the caller fails with the confusing
`the JSON object must be str, bytes or bytearray, not NoneType`.

Sites (no `encoding=`):
- `portfolio/extract.py:22` — `subprocess.run(["gh", *args], capture_output=True, text=True, check=False)`
- `portfolio/narrative.py:92` (`run_claude`) and `:108` (`run_codex`)
- `rating/cli.py:33` (`default_grader_runner`)

### Bug 2 — full prompt passed as an argv element (`WinError 206`)
`run_claude` passes the entire prompt as a `-p <prompt>` argv element, which
exceeds Windows' ~32 KB command-line limit for a real grounded prompt:
- `portfolio/narrative.py:93` — `["claude", "-p", prompt, "--permission-mode", "plan", "--output-format", "json"]`
- `rating/cli.py:34` — same `claude -p <prompt>` shape

The codex runner (`portfolio/narrative.py:108`) already feeds the prompt via
**stdin** (`input=prompt`) and is the pattern to follow.

## What to build
- Add `encoding="utf-8"` (and `errors="replace"`) to every product-code
  `subprocess.run(..., text=True)` listed above.
- Change the `claude` runner(s) to deliver the prompt via **stdin** instead of a
  `-p <prompt>` argv element (e.g. `claude --output-format json --permission-mode plan -`
  with `input=prompt`), preserving the existing output contract (still parses the
  same JSON result the callers expect). Keep the model/flags otherwise unchanged.
- Because `fit`, `reference-check`, and `resume` all import
  `portfolio.narrative.run_claude`, fixing `portfolio/narrative.py` fixes them
  too; only `rating/cli.py` carries its own copy of both bugs.

## Constraints / hard rules (see project-context + security-checklist)
- Pure compatibility fix: do **not** change extraction logic, the grounding gate,
  the narrative prompt content, rendering, or any command behaviour on a host
  that already worked. Behaviour on a UTF-8 host must be unchanged.
- Keep all subprocess calls **argv-based / shell-free** (no `shell=True`, no
  string assembly from user input).
- No new runtime dependencies.
- Do not touch the vendored harness under `.redteam/` (it is already correct).

## Out of scope
- Refactoring the runner indirection or model selection.
- Any new source type, feature, or output change.
- Fixing the confusing secondary error message text
  (`...not NoneType`) beyond what falls out of fixing the decode.

## Affected files
- `portfolio/extract.py` (Bug 1)
- `portfolio/narrative.py` (Bug 1 + Bug 2)
- `rating/cli.py` (Bug 1 + Bug 2)
- `(new) tests/test_subprocess_encoding.py` — regression tests (see below)

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
- `verify.sh` gates `ruff` + `pytest` over `portfolio/` + `tests/` only. The new
  regression tests live under `tests/` (in scope) and may import `rating` to
  cover its copy of the bug; `rating/` itself is outside the ruff scope, so keep
  the `rating/cli.py` edit minimal and lint-clean by inspection.
- Suggested red-phase tests (must fail against current code, pass after the fix):
  1. The `gh` runner decodes non-ASCII child output as UTF-8 — e.g. monkeypatch /
     fake a `subprocess.run` (or a stub `gh`) emitting a UTF-8 byte sequence and
     assert no `UnicodeDecodeError` and the bytes round-trip. Assert the call was
     made with `encoding="utf-8"`.
  2. The `claude` runner passes the prompt via **stdin** (`input=`), not as a
     `-p <prompt>` argv element — assert the prompt string is not in the argv and
     is supplied as stdin, so a large prompt can't hit `WinError 206`.
  3. Same two assertions for `rating/cli.py`'s grader runner.

## Risks
- Changing the `claude` invocation could break JSON-result parsing if the stdin
  form emits a different envelope — keep `--output-format json` and verify the
  callers still parse the same shape.
- `errors="replace"` could mask genuinely corrupt output; acceptable here since
  the alternative is a hard crash, and grounding still validates refs downstream.
- Under-scoping: if a product subprocess call is missed, one command still
  crashes on Windows. The tests should assert `encoding=` on each runner the
  commands actually use.
