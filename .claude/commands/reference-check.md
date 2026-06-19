---
description: Generate a grounded recommendation letter from a GitHub repo or a blog/article URL (runs python -m reference_check).
argument-hint: "[github <url> <author>] | [github-author <author>] | [web <url> <author>] | [portfolio <file.json>] [--mask-private] [--out <file>]"
---

The user wants to generate a **grounded** recommendation letter — every paragraph
traced to real evidence — by running this repo's CLI (`python -m reference_check`).
You are the interactive front door; the CLI does the real work (extract → narrate →
ground → build letter → render). Do NOT write recommendation letter content yourself
and do NOT edit any code.

Arguments (may be empty): `$ARGUMENTS`

## Steps

1. **Gather the inputs** from `$ARGUMENTS`; ask the user for anything missing:
   - **source type** — one of `github`, `web`, `github-author`, or `portfolio`. If unclear, ask:
     - `github` → a GitHub repository, evidence is the author's merged PRs (via `gh`).
     - `web` → a blog/article URL, evidence is the fetched article.
     - `github-author` → merged PRs across all repos the `gh` token can see.
     - `portfolio` → reuse a previously saved grounded portfolio JSON (no extraction,
       no LLM narration for the portfolio step; letter composition still uses the model).
       `--source` must be the path to the saved `.json` file.
   - **source URL** — `https://github.com/<owner>/<repo>` for github, the article URL
     for web, or the path to a `.json` file for portfolio.
   - **author** — the GitHub handle of the developer being recommended (github /
     github-author), or the subject the letter is for (web). Not used for `portfolio`.
   - optionally **--out <file>** if the user wants the Markdown written to a file
     instead of shown inline.
   - optionally **--mask-private** to anonymize private GitHub repo names in the output
     before sharing. Detected from structured fields only; semantic project names are
     NOT masked. A `masked N private repo(s)` summary is printed to stderr.

2. **Run the CLI** with exactly those values (pass each as a separate argument —
   never assemble a shell string from the user's input, never use command
   substitution or quoted interpolation of `$ARGUMENTS`):

   ```
   python -m reference_check --source-type <type> --source <url> --author <author>
   ```

   Add `--out <file>` only if the user asked to save to a file.
   Add `--mask-private` only if the user wants private repo names anonymized.
   Use `python` (not `python3`) on this host.

3. **On a non-zero exit**, show the CLI's stderr message and help the user fix the
   input — e.g. an invalid/unsupported `--source` URL, or an unknown
   `--source-type` (the CLI validates and reports these).
   Do NOT retry with a guessed URL, author, or source type.

4. **On success**, show the user:
   - the rendered Markdown recommendation letter (or, with `--out`, confirm the
     file path), and
   - the **grounding summary** the CLI prints on stderr
     (`grounded: N  rejected: N  needs-confirmation: N`) so they
     can see how many claims were dropped for lacking real evidence.

## Hard rules

- Use ONLY the source URL and author the user supplies. Never fabricate a repo,
  URL, PR, author, or file path to make the command produce output.
- This command's only job is to invoke `python -m reference_check`. Never bypass
  it, never hand-write recommendation letter content, and never modify
  `reference_check/` or `portfolio/` code to "make it work".
- **Never assemble a shell string from user input.** Pass each user-supplied value
  as a separate argv token to the CLI. No command substitution expansion, no shell
  string interpolation of `$ARGUMENTS` into a single command string.
- If the CLI reports a source type is unsupported, relay that — don't try to
  implement it here.
- The letter the CLI produces is grounded: every paragraph cites real evidence
  from the developer's actual work. Do not supplement or rewrite it.
