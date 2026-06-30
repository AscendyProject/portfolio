+++
mode = "agent-pair"
+++

# Task: GitLab MR change-size + per-file evidence (best-effort), follows #47 / task-034

# Goal
Bring GitLab MR evidence to GitHub-level fidelity: real `additions`/`deletions` (code-only
line counts) and per-changed-file `Evidence(kind="file")` records, instead of the current
`(+0/-0)` with no file evidence. `glab mr list` does NOT carry diff stats, so enrich each
merged MR by fetching its diff via `glab` per-MR. This is **best-effort**: the diff endpoint
needs an authenticated `glab`; when it is unavailable the MR gracefully keeps `0/0` (today's
behavior) — never a crash.

## Why
Verified against real `glab 1.105.0`: `glab mr list --output json` returns `iid`,
`web_url`, `title`, `references.full` (all correct) but NO `additions`/`deletions`, so every
GitLab MR currently scores as a 0-line change and produces no `kind="file"` evidence. That
weakens rating/fit signals for GitLab users vs GitHub (where `gh pr list --json files` gives
per-file line stats in one call). GitLab needs a per-MR diff fetch to recover this.

Verified facts (real glab):
- `glab mr list` (public, unauthenticated) → MR objects WITH `project_id`, `iid`,
  `references.full`, `web_url`, `title`; WITHOUT line stats.
- `glab api projects/<id>/merge_requests/<iid>/changes` and `glab mr diff <iid>` require
  **auth** (401 Unauthorized when unauthenticated). Real users (esp. `gitlab-author` /
  private projects) are authenticated, so the enrichment works for them.

## Part A — per-MR diff fetch (best-effort)
- For each merged MR returned by the list call, fetch its changes via `glab` as an argv
  list through the existing injectable `_run_glab` seam (no `shell=True`). Use the
  GitLab changes API:
  `glab api "projects/<project_id>/merge_requests/<iid>/changes"`, where `<project_id>`
  comes from the MR's `project_id` field already present in the list payload, and `<iid>`
  from `iid`. (The documented response is `{"changes": [{"new_path", "old_path", "diff",
  "new_file", "deleted_file", "renamed_file", ...}]}` where each `diff` is that file's
  unified-diff text.)
- **Best-effort / graceful:** if the changes fetch for an MR errors (auth 401, 404, a
  non-JSON body, or any `glab`/parse failure), that MR keeps `additions=deletions=0` and
  yields no `kind="file"` records — the overall extraction does NOT fail. A failure for one
  MR must not abort the others. Tokens / raw `glab` stderr are never echoed in any message.
- The N extra calls are bounded by the same `limit` that bounds the MR list. Document the
  N+1 cost in the docstring/README.

## Part B — code-only line counting + per-file evidence (reuse task-022)
- Parse each file's unified `diff`: count lines starting with `+` (excluding `+++`) as
  additions and `-` (excluding `---`) as deletions; ignore `@@` hunk headers, context
  lines, and `\ No newline at end of file` markers.
- **Reuse the existing task-022 code-only filter** from `portfolio/extract.py`
  (`_counts_toward_change_size` / the generated-vendored denylist) on the file's
  `new_path` (fall back to `old_path` for deletions) — do NOT reimplement the denylist.
  Only code files contribute to the MR's summed `additions`/`deletions`, exactly like the
  GitHub `_change_size` path.
- Emit one `Evidence(kind="file", ref=<path>, detail="changed in <mr-ref>")` per changed
  CODE file (same denylist), mirroring `parse_pr_evidence`'s file records for GitHub. The
  MR's `Evidence(kind="pr")` gets the summed code-only `additions`/`deletions`, and its
  `detail` shows the real `(+A/-D)`.

## Part C — wire into the GitLab extractor
- `extract_merged_mrs` / the author-wide variant call the per-MR enrichment after the list
  parse, populating real change-size + file evidence. Keep the pure parser layer testable:
  the diff-counting and per-file-evidence building must be PURE functions over a fake
  changes payload (no `glab` call), and the per-MR fetch goes through the injectable runner
  so the full suite stays green WITHOUT `glab` installed or authenticated.

## Hard rules
- **Deterministic** given fixed `glab` output; stdlib + `glab` only; no new pip dependency.
- **No `shell=True`**; argv lists; injectable runner; CI green with no live/authenticated
  `glab` (tests inject fake list + fake changes payloads).
- **github / GHES extraction byte-identical**; only the GitLab path changes. Reuse the
  task-022 denylist from `extract.py` (shared, single source of truth).
- **Masking unaffected**: new `kind="file"` GitLab refs (bare file paths) and the MR refs
  must not leak under `--mask-private`; the file ref is a bare path (no host/owner/repo) so
  it is not a maskable repo identity — confirm a test that a private GitLab project's file
  evidence does not expose the raw project name.
- Best-effort: a diff-fetch failure degrades to `0/0` + no file evidence for that MR only;
  no crash, no token/stderr leak.
- Grounding, scoring, rubric untouched.

## Out of scope (follow-ups)
- Pagination of MR changes beyond GitLab's default page (very large MRs may truncate the
  `changes` list; note the limitation, do not paginate in v1).
- Bitbucket; a `glab`-based visibility lookup for precise GitLab masking (separate tasks).
- Binary-file line stats (skip binary diffs — they have no `+`/`-` text lines).
- Caching diffs across runs.

## Affected files
- `portfolio/extract_gitlab.py` — per-MR changes fetch via `glab api …/changes` (injectable
  runner), a pure `parse_mr_changes(...)`/diff-line-counter, code-only counting (reusing
  `extract.py`'s denylist), per-file `Evidence`, and wiring into `extract_merged_mrs` +
  the author-wide variant; best-effort error handling.
- `portfolio/extract.py` — only if the code-only denylist helper needs to be exposed for
  reuse (prefer importing the existing `_counts_toward_change_size`; no behavior change).
- `tests/test_extract_gitlab.py` (extend) — pure diff-line-counter over a fake unified diff
  (code-only respected, `+++`/`---`/`@@` excluded); per-file evidence emitted for code files
  only; MR `additions`/`deletions` summed correctly; a fake changes-fetch failure degrades
  one MR to `0/0` without aborting others or leaking stderr/token; no live `glab`.
- `README.md` / `CHANGELOG.md` — update the GitLab fidelity note: real change-size + file
  evidence when `glab` is authenticated; `0/0` fallback otherwise; N+1 cost; remaining
  limitations (pagination, binary).

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (especially github/GHES extraction and the task-034 GitLab
tests); new tests cover diff-line counting, per-file evidence, code-only reuse, and
best-effort failure — all with fake `glab` payloads (no live/authenticated `glab`). No new
pip dependency.
