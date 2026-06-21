---
description: Generate a grounded portfolio from a GitHub repo or a blog/article URL (runs python -m portfolio).
argument-hint: "[github <url> <author>] | [github-author <author>] | [web <url> <author>] | [portfolio <file.json>] | [merge <a.json> <b.json> --subject <name> --out <file>] [--lang en|ko] [--mask-private] [--out <file>]"
---

The user wants to generate a **grounded** portfolio — every claim traced to real
evidence — by running this repo's CLI (`python -m portfolio`). You are the
interactive front door; the CLI does the real work (extract → narrate → ground →
render). Do NOT write portfolio claims yourself and do NOT edit any code.

Arguments (may be empty): `$ARGUMENTS`

## Steps

1. **Gather the inputs** from `$ARGUMENTS`; ask the user for anything missing:
   - **source type / subcommand** — one of `github`, `web`, `github-author`, `portfolio`,
     or the `merge` subcommand. If it's unclear, ask the user to choose:
     - `github` → a GitHub repository, evidence is the author's merged PRs (via `gh`).
     - `web` → a blog/article URL, evidence is the fetched article.
     - `github-author` → author-wide: merged PRs across **all** repos the `gh` token
       can see. Only `--author` is required; `--source` is not used.
       > **Note:** output may include private repo names. Redact before sharing.
     - `portfolio` → re-render a previously saved grounded portfolio JSON file (no `gh`
       extraction, no LLM narration). `--source` must be the path to the saved `.json`
       file; `--author` is accepted but ignored (the file's subject wins).
     - `merge` → combine two or more saved Portfolio JSON files into one grounded
       Portfolio (no `gh`, no LLM). All inputs must use repo-qualified refs (produced
       by `github-author`). See "Merge subcommand" below.
   - **source URL** — `https://github.com/<owner>/<repo>` for github, or the
     article URL for web. Not required for `github-author`. Path to `.json` for `portfolio`.
   - **author** — the GitHub handle whose merged PRs are the evidence (github /
     github-author), or the subject the portfolio is for (web). Not used for `portfolio`.
   - optionally **--out <file>** if the user wants the Markdown written to a file
     instead of shown inline.
   - optionally **--emit-portfolio <file>** to save the grounded Portfolio as a JSON
     file that can later be reused with `--source-type portfolio`.
   - optionally **--mask-private** to anonymize private GitHub repo names in the output
     before sharing. Detected from structured fields only; semantic project names are
     NOT masked. A `masked N private repo(s)` summary is printed to stderr.
   - optionally **--lang `en`|`ko`** to set the output language for the rendered
     Markdown document (UI strings and LLM prose). Defaults to `en` when omitted.
     Supported: `en` (English), `ko` (Korean). Note: re-rendering a stored portfolio
     JSON in a new `--lang` re-translates UI strings only; the stored claim text is
     not re-translated (it stays as the model originally wrote it).
   - optionally **--show-refs** to include grounding evidence refs in the rendered
     Markdown document. By default refs are hidden (the internal grounding still runs;
     only the display is suppressed). Pass `--show-refs` to reveal Evidence blocks and
     ref citations. The stderr grounding summary is unaffected by this flag.

2. **Run the CLI** with exactly those values (pass each as a separate argument —
   never assemble a shell string from the user's input):

   ```
   python -m portfolio --source-type <type> --source <url> --author <author>
   ```

   Add `--out <file>` only if the user asked to save to a file.
   Add `--emit-portfolio <file>` only if the user asked to save the Portfolio JSON.
   Add `--mask-private` only if the user wants private repo names anonymized.
   Use `python` (not `python3`) on this host.

3. **On a non-zero exit**, show the CLI's stderr message and help the user fix the
   input — e.g. an invalid/unsupported `--source` URL, or an unknown
   `--source-type` (the CLI validates and reports these). Do NOT retry with a
   guessed URL, author, or source type.

4. **On success**, show the user:
   - the rendered Markdown portfolio (or, with `--out`, confirm the file path), and
   - the one-line **grounding summary** the CLI prints on stderr
     (`grounded: N  rejected: N  needs-confirmation: N`) so they can see how many
     drafted claims were dropped for lacking real evidence.

   The output now leads with a grounded headline blockquote, a stats line (merged-PR
   count · distinct repos · language stack), an optional `## Highlights` section
   (bullets citing grounded refs), and per-language `## <Group>` sections for the
   claims — `## Other` always appears last.

## Merge subcommand

When the user says "merge my portfolios" or supplies `merge` as the subcommand, run:

```
python -m portfolio merge <a.json> <b.json> [<c.json> ...] --subject "Canonical Name" --out merged.json
```

- `<a.json>`, `<b.json>`, … are **previously saved Portfolio JSON files** (at least 2 are required).
- `--subject` is the canonical name for the merged portfolio (required; authoritative — overrides
  each file's stored subject).
- `--out` is the output path for the merged Portfolio JSON (required).

**Bare-ref guard:** inputs must use repo-qualified evidence refs (e.g. `owner/repo#1`).
Bare refs like `PR#1` or bare file paths will cause a clear exit-2 error naming the
offending file. Use `--source-type github-author` (not `github`) when emitting portfolios
that you plan to merge later.

On success, exit 0 and the merged JSON is written to `--out`. On error, exit 2 with a
single-line stderr message (no traceback) naming the issue.

## Hard rules

- Use ONLY the source URL and author the user supplies. Never fabricate a repo,
  URL, PR, or author to make the command produce output.
- This command's only job is to invoke `python -m portfolio`. Never bypass it,
  never hand-write claims, and never modify `portfolio/` code to "make it work".
- If the CLI reports a source type is unsupported, relay that — don't try to
  implement it here.
