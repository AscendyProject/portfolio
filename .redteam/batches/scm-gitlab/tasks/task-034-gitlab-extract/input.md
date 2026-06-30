+++
mode = "agent-pair"
+++

# Task: GitLab evidence extraction via `glab` — first non-GitHub SCM (issue #47)

## Goal
Let a developer on **GitLab** use the toolchain. Add `--source-type gitlab` and
`gitlab-author` that extract a developer's **merged Merge Requests** as grounded
`Evidence` via the `glab` CLI (mirroring how `github` uses `gh`), so resume / fit /
rating / reference-check work on GitLab work — not just GitHub. This is the first
non-GitHub SCM adapter; it formalizes the existing source-handler seam. **Bitbucket and
other SCMs are explicit follow-ups** (Bitbucket has no first-class CLI and needs
different plumbing).

## Why (issue #47)
Evidence extraction is GitHub-only (`portfolio/extract.py::extract_merged_prs` shells
`gh`). `portfolio/sources.py` already has a handler registry ("register a handler and it
becomes CLI-usable with no CLI change"), so adding GitLab is mostly a new extractor + new
handlers. `glab` is GitLab's official CLI and mirrors `gh`:
`glab mr list --author <user> --merged --output json` lists a user's merged MRs.

## Part A — GitLab source handlers (`portfolio/sources.py`)
- Register `gitlab` and `gitlab-author` handlers in the existing `SourceHandler` map so
  they become CLI-usable with no per-CLI change (mirror `_github_handler` /
  `_github_author_handler`).
- `gitlab`: requires `--source` (a GitLab project URL) and `--author`; `gitlab-author`:
  requires only `--author` (all projects the `glab` token can see).
- Parse/SSRF-harden the GitLab project URL the same way `parse_github_source` does
  (reject IP-literal hosts, userinfo `user@host`, explicit ports — reuse the existing
  hardening helper, do not weaken it). GitLab namespaces can be **nested**
  (`group/subgroup/project`), so the parser must accept ≥2 path segments as the project
  path (unlike GitHub's exactly-`owner/repo`). gitlab.com and self-managed GitLab hosts
  are both supported; the host is carried for masking (same host-aware model as GHES).

## Part B — GitLab extractor (`portfolio/extract.py` or `(new) portfolio/extract_gitlab.py`)
- `extract_merged_mrs(project, author, limit=100) -> list[Evidence]` and an
  author-wide variant, shelling `glab` as an **argv list** via `subprocess.run`
  (no `shell=True`), with an injectable runner seam (mirror `_run_gh` so tests pass a
  fake and no live `glab` is required). Use
  `glab mr list --author <author> --merged --output json` (+ project scoping via
  `--repo <host>/<project>` or cwd, as glab requires).
- Parse the JSON into `Evidence`: one `kind="pr"` per merged MR with
  `ref` = a stable project-qualified MR identity (GitLab uses `!<iid>` for MRs, e.g.
  `group/subgroup/project!42` — pick a representation and DOCUMENT it), `url` = the MR
  web URL, `detail` = title + change size, `additions`/`deletions` from the MR if
  available. **File-level fidelity:** if `glab mr list` JSON does not carry per-file
  diffs, MR-level evidence (no `kind="file"` records) is acceptable for v1 — do NOT make
  N extra per-MR calls just to mirror GitHub's file evidence; note the reduced fidelity.
  Reuse the task-022 generated/vendored denylist + code-only line counting only if file
  paths are actually available.
- Deterministic given fixed `glab` output; pure parsing split from the subprocess call
  (unit-testable with a fake), exactly like `parse_pr_evidence` / `extract_merged_prs`.

## Part C — masking interaction (`--mask-private`) for GitLab
- The host-aware masking layer (task-028) already discovers + relabels non-github hosts.
  For GitLab the gh-based visibility lookup (`gh repo view`) cannot resolve a GitLab repo,
  so the existing **fail-safe treats it as private → masks it**. That means under
  `--mask-private` GitLab repos are masked (possibly over-masked) — safe, never leaked.
  v1 RELIES on this fail-safe; a `glab`-based precise visibility lookup is OUT OF SCOPE
  (follow-up). Verify with a test that a GitLab private repo name is masked end-to-end
  (no raw GitLab project name in output under `--mask-private`). Ensure the GitLab MR ref
  form (`!<iid>`, nested namespace) is representable and does not break the masking
  layer's ref parsing (extend `mask.py` minimally ONLY if a GitLab ref shape would
  otherwise leak — keep github.com + GHES behavior byte-identical).

## Hard rules
- **Deterministic**; stdlib + `glab` only; no new pip dependency. `glab` is an optional
  external CLI (like `gh`); a missing/un-authed `glab` yields a clean, actionable error
  (mirror the `gh` failure message), not a traceback.
- **No `shell=True`**; `glab` args are an argv list; the extractor runner is injectable so
  the full suite stays green WITHOUT `glab` installed (tests use a fake runner / fake
  extractor; any real-`glab` test is guarded by skip-if-not-installed).
- **github / GHES behavior byte-identical** — existing `gh` extraction, source dispatch,
  and masking tests stay green unchanged.
- No secrets/tokens logged; `glab` stderr not echoed raw.
- Grounding, scoring, rubric, and the masking relabel algorithm are untouched (only a new
  source + extractor; minimal mask ref-parse extension only if strictly needed).

## Out of scope (explicit — follow-ups)
- **Bitbucket** and any other SCM (no first-class CLI; different plumbing) — separate task.
- A **`glab`-based visibility lookup** for precise GitLab `--mask-private` (v1 uses the
  fail-safe = mask). Separate task.
- GitLab **issues / commits / reviews** as evidence (v1 mirrors GitHub: merged MRs only).
- File-level evidence parity with GitHub when `glab` doesn't provide per-file diffs in the
  list call (no N+1 fetches in v1).
- Any CLI flag rename or output-format change for existing sources.

## Affected files
- `portfolio/sources.py` — `gitlab` + `gitlab-author` handlers registered in the map;
  GitLab URL parse/SSRF-hardening (nested-namespace aware), host carried for masking.
- `portfolio/extract.py` or `(new) portfolio/extract_gitlab.py` — `glab`-based merged-MR
  extractor (argv subprocess + injectable runner) + pure JSON→Evidence parser.
- `tests/` — source dispatch for `gitlab`/`gitlab-author`; URL parse + SSRF rejection for
  GitLab (IP-literal/userinfo/port rejected; nested namespace accepted); JSON→Evidence
  parsing with a fake `glab` payload (merged MRs → grounded Evidence, ref/url/detail
  correct); `--mask-private` masks a GitLab private project end-to-end; missing-`glab`
  clean error; github/GHES tests unchanged.
- `README.md` / `CHANGELOG.md` — document `--source-type gitlab` / `gitlab-author`, the
  `glab` requirement, and the v1 limitations (MR-level fidelity, fail-safe masking,
  Bitbucket follow-up).

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (especially github/GHES extraction, source dispatch, and
masking); new tests cover GitLab dispatch + extraction + masking with a fake `glab`. No new
pip dependency; `glab` is an optional external CLI exercised only via injected fakes in CI.
