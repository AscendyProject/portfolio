# Contributing

Thanks for your interest in `portfolio`. It's early-stage, so the most useful
contributions are small, well-tested, and faithful to the one rule below.

## The one rule: every claim must be grounded

This project's whole point is that generated output never invents anything. The
architecture enforces it as three layers:

1. **extract** (deterministic) — `gh`/web → `Evidence`. No model.
2. **narrate** (model) — writes claims, citing evidence refs by id.
3. **ground** (deterministic) — drops any claim citing a ref the extractor never
   produced.

When you add a feature, keep model output on the narrate layer and keep
verification deterministic. A change that lets an un-grounded claim reach the
rendered output is a bug, not a feature — even if tests pass.

## Dev setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"     # ruff + pytest
ruff check . && pytest -q
```

Requires Python 3.11+. The runtime engine is stdlib-only; model calls are
isolated to the narrate layer.

## Before opening a PR

- `ruff check .` is clean and `pytest -q` is green (CI runs both on 3.11 and 3.12).
- New behavior has a test that would fail without your change.
- Keep changes surgical — match the surrounding style, don't refactor unrelated code.
- Never assemble a shell string from user input; pass values as argv tokens.
- Don't weaken the grounding gate to make something easier. If the gate is in your
  way, that's usually the design working as intended — open an issue to discuss.

## Reporting security issues

See [SECURITY.md](SECURITY.md) — please report privately, not in a public issue.
