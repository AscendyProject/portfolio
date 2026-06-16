---
description: Generate a grounded resume from a GitHub repo or a blog/article URL and a job description (runs python -m resume).
argument-hint: "[github <repo-url> <author> <jd-path>] | [web <article-url> <author> <jd-path>] [--top-n N] [--out <file>]"
---

The user wants to generate a **grounded** resume — every bullet traced to real
evidence, filtered by a job description — by running this repo's CLI (`python -m resume`).
You are the interactive front door; the CLI does the real work (extract → narrate → ground
→ select → render). Do NOT write resume bullets yourself and do NOT edit any code.

Arguments (may be empty): `$ARGUMENTS`

## Steps

1. **Gather the inputs** from `$ARGUMENTS`; ask the user for anything missing:
   - **source type** — one of `github` or `web`. If unclear, ask:
     - `github` → a GitHub repository, evidence is the author's merged PRs (via `gh`).
     - `web` → a blog/article URL, evidence is the fetched article.
   - **source URL** — `https://github.com/<owner>/<repo>` for github, or the
     article URL for web.
   - **author** — the GitHub handle whose merged PRs are the evidence (github),
     or the subject the resume is for (web).
   - **jd path** — filesystem path to a plain-text job description file (required).
   - optionally **--top-n N** to cap the number of rendered bullets (default: 12).
   - optionally **--out <file>** if the user wants the Markdown written to a file
     instead of shown inline.

2. **Run the CLI** with exactly those values (pass each as a separate argument —
   never assemble a shell string from the user's input, never use command
   substitution or quoted interpolation of `$ARGUMENTS`):

   ```
   python -m resume --source-type <type> --source <url> --author <author> --jd <jd-path>
   ```

   Add `--top-n <n>` only if the user supplied it. Add `--out <file>` only if the
   user asked to save to a file. Use `python` (not `python3`) on this host.

3. **On a non-zero exit**, show the CLI's stderr message and help the user fix the
   input — e.g. an invalid/unsupported `--source` URL, a missing `--jd` file, or
   an unknown `--source-type` (the CLI validates and reports these).
   Do NOT retry with a guessed URL, author, source type, or JD path.

4. **On success**, show the user:
   - the rendered Markdown resume (or, with `--out`, confirm the file path), and
   - the one-line **grounding summary** the CLI prints on stderr
     (`grounded: N  rejected: N  needs-confirmation: N`) so they can see how many
     drafted claims were dropped for lacking real evidence.

## Hard rules

- Use ONLY the source URL, author, and JD path the user supplies. Never fabricate
  a repo, URL, PR, author, or file path to make the command produce output.
- This command's only job is to invoke `python -m resume`. Never bypass it,
  never hand-write resume bullets, and never modify `resume/` or `portfolio/` code
  to "make it work".
- **Never assemble a shell string from user input.** Pass each user-supplied value
  as a separate argv token to the CLI. No command substitution expansion, no shell string
  interpolation of `$ARGUMENTS` into a single command string.
- If the CLI reports a source type is unsupported, relay that — don't try to
  implement it here.
- The `--jd` flag accepts a filesystem path only — do not fetch the JD from a URL.
