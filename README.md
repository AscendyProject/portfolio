# portfolio

Turn a developer's real GitHub work into a **grounded** portfolio — every claim
traced to evidence, never invented.

> Part of the Ascendy harness catalog. Status: **v0.2.0** — five grounded commands (`/portfolio` · `/resume` · `/reference-check` · `/fit` · `/rating`). See [CHANGELOG](CHANGELOG.md).

## Quickstart

Prerequisites: **Python 3.11+** and the **GitHub CLI (`gh`) authenticated**
(`gh auth login`) — evidence is pulled from `gh`.

```bash
git clone https://github.com/AscendyProject/portfolio
cd portfolio
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# Render a grounded portfolio from a developer's merged PRs:
python -m portfolio --source-type github \
  --source https://github.com/<owner>/<repo> --author <handle>
```

Five commands share the same grounded engine: `/portfolio`, `/resume`,
`/reference-check`, `/fit`, `/rating` — each documented below.

### As a Claude Code plugin (recommended)

This repo doubles as a single-plugin marketplace, so two commands install all
five slash commands without a manual checkout:

```text
/plugin marketplace add https://github.com/AscendyProject/portfolio
/plugin install portfolio@ascendy-portfolio
```

> The HTTPS URL works everywhere, including behind firewalls that block SSH
> (port 22). The `AscendyProject/portfolio` shorthand also works if you have
> GitHub SSH keys configured.

Installed, the commands are namespaced under the plugin —
`/portfolio:portfolio`, `/portfolio:resume`, `/portfolio:reference-check`,
`/portfolio:fit`, `/portfolio:rating`. Each one shells out to the matching
`python -m …` CLI, so the **Python 3.11+ and authenticated `gh`** prerequisites
above still apply on the host that runs them.

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
2. narrate   (LLM)            a model writes contribution claims — over the
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

### `/portfolio` command

Run `python -m portfolio --source-type github --source <url> --author <handle>` (or
`--source-type web`) to render a grounded portfolio as Markdown. The `/portfolio`
slash command is the interactive front door.

The rendered document leads with a grounded headline blockquote (model-authored, or a
deterministic fallback when grounding fails), followed by a stats line showing merged-PR
count, distinct repo count, and the detected language stack. When the model returns
synthesis highlights that cite only already-grounded claim refs, an optional
`## Highlights` section lists them with their cited refs in parentheses. The remaining
claims are grouped under `## <Language>` headings by majority file-extension language,
with `## Other` always last.

### `/resume` command

Run `python -m resume --source-type <type> --source <url> --author <handle> --jd <path-or-url>`
to render a grounded **resume** filtered by a job description. `--jd` accepts either a
local filesystem path to a plain-text file **or** an `http(s)` URL to a job posting page
(the page is fetched via an offline-SSRF-guarded layer and its article text is used as the
JD). Every bullet traces to a real evidence ref already present in the grounded portfolio —
hallucinated refs are rejected by `resume.select.enforce_grounding` and never appear in the
output. The `/resume` slash command is the interactive front door; `--top-n` (default 12)
caps rendered bullets; `--out <file>` writes to a file instead of stdout.

### `/reference-check` command

Run `python -m reference_check --source-type <type> --source <url> --author <handle>`
to render a grounded **recommendation letter** for the developer. The letter is composed
from the grounded portfolio only — every paragraph cites real evidence refs and is
re-grounded after generation; hallucinated paragraphs are dropped by the grounding gate
and never appear in the output. The `/reference-check` slash command is the interactive
front door; `--out <file>` writes to a file instead of stdout.

### `/fit` command

Run `python -m fit --source-type <type> --source <url> --author <handle> --jd <path-or-url>`
to render a grounded **JD fit assessment** for the developer. `--jd` accepts either a
local filesystem path to a plain-text file **or** an `http(s)` URL to a job posting page
(fetched via the same SSRF-guarded layer as `--source-type web`). The assessment uses a
**two-tier hybrid**:

1. **Deterministic grade (S/A/B/C/D)** — JD-coverage% is computed by matching
   grounded portfolio claim tokens against JD keywords. The coverage% maps to a
   grade and locks a score band (`S=96–100`, `A=85–95`, `B=70–84`, `C=55–69`,
   `D=0–54`). This step involves no model call and is fully reproducible for the
   same portfolio + JD.

2. **Bounded agent score** — An agent picks an integer score *inside* the locked
   band and provides grounded reasoning bullets. The score is clamped to the band;
   any reasoning bullet citing a ref not in the portfolio evidence is dropped by
   the grounding gate.

> **Important:** `/fit` is a **rubric assessment** (keyword coverage of the JD),
> NOT a holistic "you are N% qualified" judgment. It reflects how well the
> developer's grounded evidence covers the JD's keywords; depth of experience,
> years, or domain judgment are not modeled.

The `/fit` slash command is the interactive front door; `--out <file>` writes to
a file instead of stdout.

### `/rating` command

Run `python -m rating --source-type <type> --source <url> --author <handle>` to produce
a grounded **capability assessment** — a deterministic grade (S/A/B/C/D) and rubric score
(0–100) — from the developer's real evidence. The grade is computed deterministically from
evidence-derived metrics (volume of merged PRs, breadth of changed files, stack diversity)
and locks a score band; a temperature-0 agent grader then picks the precise score within
that band and writes grounding-checked reasoning. Every metric cites the exact evidence
refs it was computed from; un-grounded reasoning is dropped. **This command does NOT
produce an absolute percentile, global comparison, or any claim about the developer's
standing relative to a population.** The `/rating` slash command is the interactive front
door; `--out <file>` writes to a file instead of stdout.

## Source types

All five commands accept `--source-type` to select the evidence source:

| `--source-type` | `--source` | `--author` | Evidence scope |
|---|---|---|---|
| `github` | GitHub repo URL (required) | handle (required) | merged PRs in one repo |
| `web` | article URL (required) | name (required) | fetched article |
| `github-author` | _(not used)_ | handle (required) | merged PRs across **all** repos the `gh` token can see |
| `portfolio` | path to a saved `.json` file (required) | _(ignored; subject from file)_ | re-uses a previously saved grounded portfolio |

### Save-then-reuse two-step

Run `python -m portfolio` once with `--emit-portfolio <file>` to save the grounded
Portfolio as a JSON file. Then pass that file to any of the five CLIs via
`--source-type portfolio --source <file>` to skip extraction and LLM narration
entirely — only the downstream step (resume selection, fit scoring, etc.) runs.

```bash
# Step 1: build and save
python -m portfolio --source-type github \
  --source https://github.com/<owner>/<repo> --author <handle> \
  --emit-portfolio portfolio.json

# Step 2: reuse across CLIs (no gh, no LLM narration call)
python -m portfolio  --source-type portfolio --source portfolio.json
python -m resume     --source-type portfolio --source portfolio.json --jd jd.txt
python -m fit        --source-type portfolio --source portfolio.json --jd jd.txt
python -m rating     --source-type portfolio --source portfolio.json
python -m reference_check --source-type portfolio --source portfolio.json
```

The grounding gate is re-applied on load: any claim whose cited evidence ref is
absent from the saved evidence list is dropped. `--author` is accepted but ignored
for `--source-type portfolio`; the subject stored in the JSON file always wins.

### `github-author` — author-wide evidence

```bash
python -m rating --source-type github-author --author <handle>
python -m portfolio --source-type github-author --author <handle>
```

Runs `gh search prs --author <handle> --merged` to pull the developer's merged PRs
across every repo the authenticated `gh` token can access (public and private), then
enriches each PR with its changed files via `gh pr view`. All five commands support
this source type with no additional flags.

> **Private-repo names:** `gh search prs` may return PRs in private repos the token
> can access. That is intentional — it gives the most honest self-assessment. If you
> share the output, **use `--mask-private` or redact private repo names before distributing.**

### `--mask-private` — anonymize private repos

All five CLIs accept `--mask-private` to replace private GitHub repo names in the output
before the rendered Markdown is written, so a shared artifact never leaks a private repo name.

```bash
python -m portfolio --source-type github-author --author <handle> --mask-private
python -m resume    --source-type github-author --author <handle> --jd jd.txt --mask-private
python -m fit       --source-type github-author --author <handle> --jd jd.txt --mask-private
python -m rating    --source-type github-author --author <handle> --mask-private
python -m reference_check --source-type github-author --author <handle> --mask-private
```

When `--mask-private` is set:

1. The full extract → narrate → ground pipeline runs first (no synthesis yet).
2. Every `owner/repo` found in structured evidence fields (`ref`, `url`) and claim
   `evidence_refs` is looked up via `gh repo view --json isPrivate`.
3. Private repos are relabeled `private-repo-1`, `private-repo-2`, … (sorted by name
   for determinism). Every occurrence in `ref`, `url`, `detail`, `context`, `claim.text`,
   and `claim.evidence_refs` is rewritten using the same map.
4. Synthesis (if enabled) runs on the already-masked portfolio; the model's output text is
   scrubbed again after synthesis so any private name the model emitted on its own is removed.
5. A summary line `masked N private repo(s)` is printed to stderr.

**Scope limit:** only literal `owner/repo` substrings are masked — detected from structured
fields only (`evidence.ref`, `evidence.url`, `claim.evidence_refs`). Semantic project names
a model wrote into claim text (e.g. "billing service") are **not** masked. Free text in
`evidence.detail`, `evidence.context`, and `claim.text` is a *substitution target* (already-
discovered private repo names are replaced in them), but never a *discovery source*.

To avoid masking ordinary file paths, a candidate whose repo segment ends in a common
source-file extension (e.g. `app/auth.py`) is treated as a path, not a repo, and is **not**
discovered. Trade-off: a real repository literally named `*.py` / `*.js` / etc. would be
skipped — vanishingly rare in practice.

### `--show-refs` — reveal grounding refs in rendered output

By default, all five CLIs hide grounding evidence refs from the rendered Markdown document.
The internal grounding pipeline runs unchanged — every claim is still traced to real evidence
before render — but the rendered document shows only claim text (and confidence for portfolio).
Pass `--show-refs` to restore the full reference display (Evidence blocks, inline `[refs]`,
`*(refs)*` citation lines, etc.):

```bash
python -m portfolio     --source-type github --source <url> --author <handle> --show-refs
python -m resume        --source-type github --source <url> --author <handle> --jd jd.txt --show-refs
python -m fit           --source-type github --source <url> --author <handle> --jd jd.txt --show-refs
python -m rating        --source-type github --source <url> --author <handle> --show-refs
python -m reference_check --source-type github --source <url> --author <handle> --show-refs
```

The stderr `grounded: N  rejected: N  needs-confirmation: N` summary is emitted on every run
regardless of `--show-refs`. The two flags compose: `--show-refs --mask-private` shows refs in
their anonymized `private-repo-N` form.

## Dev

```bash
python3 -m venv venv && source venv/bin/activate
pip install ruff pytest
ruff check . && pytest -q
```

## License

Apache License 2.0 (`LICENSE`).
