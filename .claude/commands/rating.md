---
description: Assess a developer's capability with a grounded grade and rubric score from their real work. Does NOT produce an absolute percentile or comparison to any population.
argument-hint: "[github <repo-url> <author>] | [web <article-url> <author>] [--out <file>]"
---

The user wants a **grounded capability assessment** — a deterministic grade (S/A/B/C/D)
and rubric score derived from real evidence — by running this repo's CLI (`python -m rating`).
You are the interactive front door; the CLI does the real work (extract → narrate → ground
→ profile → grade → render). Do NOT write assessment bullets yourself and do NOT edit any code.

**This command does NOT produce an absolute percentile, global comparison, or any claim
about the developer's standing relative to a population. The grade is deterministic from
evidence; the score is a rubric assessment bounded by that grade — nothing more.**

Arguments (may be empty): `$ARGUMENTS`

## Steps

1. **Gather the inputs** from `$ARGUMENTS`; ask the user for anything missing:
   - **source type** — one of `github` or `web`. If unclear, ask:
     - `github` → a GitHub repository, evidence is the author's merged PRs (via `gh`).
     - `web` → a blog/article URL, evidence is the fetched article.
   - **source URL** — `https://github.com/<owner>/<repo>` for github, or the article URL for web.
   - **author** — the GitHub handle (github) or subject name (web) the assessment is for.
   - optionally **--out <file>** if the user wants the Markdown written to a file instead of
     shown inline.

2. **Run the CLI** with exactly those values (pass each as a separate argument —
   never assemble a shell string from the user's input, never use command
   substitution or quoted interpolation of `$ARGUMENTS`):

   ```
   python -m rating --source-type <type> --source <url> --author <author>
   ```

   Add `--out <file>` only if the user asked to save to a file.
   Use `python` (not `python3`) on this host.

3. **On a non-zero exit**, show the CLI's stderr message and help the user fix the
   input — e.g. an invalid/unsupported `--source` URL, an unknown `--source-type`
   (the CLI validates and reports these).
   Do NOT retry with a guessed URL, author, or source type.

4. **On success**, show the user:
   - the rendered Markdown scorecard (grade + score + per-dimension metrics + rubric), and
   - the **grounding summary** the CLI prints on stderr
     (`grounded: N  rejected: N  needs-confirmation: N`) so they can see how many
     claims were dropped for lacking real evidence.

## Hard rules

- Use ONLY the source URL and author the user supplies. Never fabricate a repo, URL,
  PR, or author handle.
- This command's only job is to invoke `python -m rating`. Never bypass it, never
  hand-write assessment bullets, and never modify `rating/` or `portfolio/` code.
- **Never assemble a shell string from user input.** Pass each user-supplied value
  as a separate argv token to the CLI. No command substitution expansion, no shell string
  interpolation of `$ARGUMENTS` into a single command string.
- **This command does not produce an absolute percentile or comparison to any population.**
  Do not add wording that claims a developer is "top X%" or compares them to an external
  baseline — no such data exists here.
- If the CLI reports a source type is unsupported, relay that — don't try to implement it here.
