---
description: Assess how well a developer's grounded portfolio matches a job description (runs python -m fit).
argument-hint: "[github <url> <author>] | [github-author <author>] | [web <url> <author>] | [portfolio <file.json>] --jd <path-or-url> | --jd-dir <dir> [--lang en|ko] [--mask-private] [--out <file>]"
---

The user wants a **grounded JD fit assessment** — a deterministic grade (S/A/B/C/D)
locked by JD-coverage%, with a bounded agent score inside the grade's band and
grounded reasoning — by running this repo's CLI (`python -m fit`).
You are the interactive front door; the CLI does the real work (extract → narrate →
ground → score → grade → render). Do NOT write fit analysis yourself and do NOT edit
any code.

Arguments (may be empty): `$ARGUMENTS`

## Steps

1. **Gather the inputs** from `$ARGUMENTS`; ask the user for anything missing:
   - **source type** — one of `github`, `web`, `github-author`, or `portfolio`. If unclear, ask:
     - `github` → a GitHub repository, evidence is the author's merged PRs (via `gh`).
     - `web` → a blog/article URL, evidence is the fetched article.
     - `github-author` → merged PRs across all repos the `gh` token can see.
     - `portfolio` → reuse a previously saved grounded portfolio JSON (no extraction,
       no LLM narration). `--source` must be the path to the saved `.json` file.
   - **source URL** — `https://github.com/<owner>/<repo>` for github, the article URL
     for web, or the path to a `.json` file for portfolio.
   - **author** — the GitHub handle whose merged PRs are the evidence (github /
     github-author), or the subject the assessment is for (web). Not used for `portfolio`.
   - **jd input — exactly one of:**
     - `--jd <path-or-url>` — filesystem path to a plain-text job description file, or
       an `http(s)` URL to a job posting page. When a URL is supplied the page is fetched
       and its article text is used as the JD.
     - `--jd-dir <dir>` — **batch mode**: score the same portfolio against every `*.txt`
       and `*.md` file (top-level only; case-sensitive suffix match) found in `<dir>`.
       Files are processed in sorted order (Python `sorted()` on basename). The output is
       a ranked Markdown table (`JD | Grade | Score | Coverage% | Top Gaps`) sorted
       best-first (Score ↓, Coverage% ↓, JD basename ↑). The portfolio is built ONCE
       regardless of how many JDs are in the directory. `--jd` and `--jd-dir` are
       **mutually exclusive**; supplying both or neither exits with code 2.
       If the directory contains no matching files, the CLI exits with code 2 (no crash).
   - optionally **--lang `en`|`ko`** to set the output language.
     - **Single JD (`--jd`)**: when omitted, the language is auto-detected from the JD
       text (Hangul-dominant → `ko`, Latin-dominant → `en`).
     - **Batch (`--jd-dir`)**: when omitted, the default is **`en`**. There is no
       auto-detection from JD contents in batch mode. An explicit `--lang` always wins.
     Supported: `en` (English), `ko` (Korean).
   - optionally **--out <file>** if the user wants the Markdown written to a file
     instead of shown inline. In batch mode, the single ranked table is written to this
     file.
   - optionally **--mask-private** to anonymize private GitHub repo names in the output
     before sharing. Detected from structured fields only; semantic project names are
     NOT masked. A `masked N private repo(s)` summary is printed to stderr.
   - optionally **--show-refs** to include grounding evidence refs in the rendered
     Markdown fit assessment (single-JD mode only). By default refs are hidden (grounding
     still runs; only display is suppressed). The stderr grounding summary is unaffected
     by this flag.

2. **Run the CLI** with exactly those values (pass each as a separate argument —
   never assemble a shell string from the user's input, never use command
   substitution or quoted interpolation of `$ARGUMENTS`):

   ```
   python -m fit --source-type <type> --source <url> --author <author> --jd <jd-path>
   ```

   Add `--out <file>` only if the user asked to save to a file.
   Add `--mask-private` only if the user wants private repo names anonymized.
   Use `python` (not `python3`) on this host.

3. **On a non-zero exit**, show the CLI's stderr message and help the user fix the
   input — e.g. an invalid/unsupported `--source` URL, a missing `--jd` file, or
   an unknown `--source-type` (the CLI validates and reports these).
   Do NOT retry with a guessed URL, author, source type, or JD path.

4. **On success**, show the user:
   - the rendered Markdown fit assessment (or, with `--out`, confirm the file path), and
   - the one-line **grounding summary** the CLI prints on stderr
     (`grounded: N  rejected: N  needs-confirmation: N`) so they can see how many
     drafted claims were dropped for lacking real evidence.

## How the assessment works

The `/fit` command uses a **two-tier hybrid**:

1. **Deterministic grade** — JD-coverage% is computed by matching grounded portfolio
   claim tokens against JD keywords (same tokenizer as `/resume`). The coverage%
   maps to a grade (S/A/B/C/D) and locks a score band. This step involves no model
   call and is fully reproducible.

2. **Bounded agent score** — An agent picks an integer score *inside* the locked
   band and provides grounded reasoning bullets. The score is clamped to the band;
   any reasoning bullet citing a ref not in the portfolio evidence is dropped.

**Important:** `/fit` is a **rubric assessment** (how well does the developer's
grounded work cover the JD's keywords?), NOT a holistic "you are N% qualified"
judgment. It reflects keyword coverage only; depth of experience, years, or
domain judgment are not modeled.

## Hard rules

- Use ONLY the source URL, author, and JD path the user supplies. Never fabricate
  a repo, URL, PR, author, or file path to make the command produce output.
- This command's only job is to invoke `python -m fit`. Never bypass it,
  never hand-write fit bullets, and never modify `fit/` or `portfolio/` code
  to "make it work".
- **Never assemble a shell string from user input.** Pass each user-supplied value
  as a separate argv token to the CLI. No command substitution expansion, no shell string
  interpolation of `$ARGUMENTS` into a single command string.
- If the CLI reports a source type is unsupported, relay that — don't try to
  implement it here.
- The `--jd` flag accepts a filesystem path **or** an `http(s)` URL. When a URL is supplied the CLI fetches the page through an offline-SSRF-guarded layer and uses the extracted article text as the JD. Pass the URL as a separate argv token — never assemble it into a shell string.
