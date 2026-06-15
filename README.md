# portfolio

Turn a developer's real GitHub work into a **grounded** portfolio — every claim
traced to evidence, never invented.

> Part of the Ascendy harness catalog (`/portfolio`). Status: early scaffold.

## Why it's different

AI portfolio/resume generators are easy to write and hard to trust — they
overclaim, hallucinate, and stuff keywords. This one inverts that: the **evidence
is deterministic** (pulled from `gh`) and a model may only write narrative that
**cites evidence that actually exists**. A grounding gate rejects any claim that
cites nothing, or cites a PR/commit/file the extractor never produced.

> **Every claim must be grounded.**

## How it works (three layers)

```
1. extract   (deterministic)  gh → real merged PRs, changed files → Evidence
2. narrate   (LLM, next)      a model writes contribution claims — over the
                              evidence it is given, citing refs by id
3. ground    (deterministic)  every claim is checked: does each cited ref exist
                              in the extracted Evidence set? un-grounded → dropped
                              or sent for human confirmation, never shipped
```

The split mirrors the harness principle *deterministic checks before AI
judgment*: a model writes the story; code verifies the citations.

## Status / what exists

- `portfolio/model.py` — `Evidence`, `Claim`, `Portfolio` (the grounding contract).
- `portfolio/extract.py` — `gh`-based merged-PR extraction → `Evidence` (argv, no shell).
- `portfolio/grounding.py` — the gate: `check_claims(claims, evidence)` partitions
  into grounded / rejected / needs-confirmation.
- Tests cover the deterministic core (grounding + PR parsing).

Next: the narrative layer (shell out to `claude`/`codex` to draft claims over the
extracted evidence), then rendering, then the `/resume` harness that consumes a
portfolio + a job description.

## Dev

```bash
python3 -m venv venv && source venv/bin/activate
pip install ruff pytest
ruff check . && pytest -q
```

## License

Apache License 2.0 (`LICENSE`).
