# Outcome — GitLab evidence extraction via `glab` (issue #47)

## Goal
A developer on GitLab can run the same `portfolio` / `resume` / `fit` / `rating` /
`reference-check` flows on their merged Merge Requests by passing
`--source-type gitlab` (project-scoped) or `--source-type gitlab-author`
(token-scoped, all visible projects). Evidence is pulled deterministically from the
`glab` CLI (mirroring how `gh` is used for GitHub), with no live `glab` required to
run the test suite and no change in github / GHES behavior.

## Done-when
- [ ] `portfolio.sources.known_source_types()` includes `"gitlab"` and `"gitlab-author"`,
      and `portfolio.sources._HANDLERS` contains a handler for each — i.e. both names
      become CLI-usable choices for `--source-type` without any change to `cli.py`.
- [ ] `resolve_source("gitlab", SourceRequest(source=<gitlab URL>, author=<handle>))`
      returns a `ResolvedSource` whose `subject == author` and whose `extract()` is
      deferred (no network call until invoked); a missing `--source` or missing
      `--author` raises `ValueError` before any extraction.
- [ ] `resolve_source("gitlab-author", SourceRequest(source=None, author=<handle>))`
      returns a `ResolvedSource` whose `subject == author` and whose `extract()` is
      deferred; `--source` is optional and ignored for this type.
- [ ] A new pure parser in `portfolio/extract.py` (or `portfolio/extract_gitlab.py`)
      converts a fake `glab mr list --output json` payload into `list[Evidence]`
      containing exactly one `Evidence(kind="pr", ...)` per merged MR, with:
      - `ref` = a stable, project-qualified MR identity using GitLab's `!<iid>` form
        (e.g. `group/subgroup/project!42`); the exact format is documented in the
        module/function docstring and is consistent for both `gitlab` and
        `gitlab-author` sources.
      - `url` = the MR web URL from the payload.
      - `detail` = MR title plus the change size (e.g. `+A/-D`), mirroring the
        `parse_pr_evidence` shape.
      - `additions` / `deletions` populated when the JSON carries them (0 when absent —
        graceful degradation, never a crash).
- [ ] The new GitLab extractor functions (one project-scoped, one author-wide) shell
      `glab` as an argv list via `subprocess.run` with `shell=False`, capture text
      with `encoding="utf-8"`, and accept an injectable `runner` parameter (default a
      module-private `_run_glab` that mirrors `_run_gh`) so unit tests run without a
      real `glab` binary.
- [ ] A missing `glab` binary (`FileNotFoundError` from `subprocess.run`) and a
      non-zero `glab` exit produce a clean `RuntimeError` (or equivalent caught
      exception) with an actionable message; the message does NOT echo `glab` stderr
      raw beyond a bounded slice (mirror the existing `_run_gh` truncation) and does
      not include any token value. No traceback reaches the CLI top level: the existing
      `cli.run` error boundary turns it into a non-zero exit with a single stderr line.
- [ ] A `parse_gitlab_source(url)` helper validates a GitLab project URL with the same
      hardening as `parse_github_source` — rejects non-http(s) schemes, userinfo
      (`user@host`), explicit ports (including IPv6 bracketed forms), IP-literal hosts
      (canonical + `inet_aton` legacy forms), invalid hostnames, query/fragment, and
      empty/`.`/`..` segments — and accepts ≥2-segment project paths (nested
      namespaces like `group/subgroup/project`). For `gitlab.com` and `www.gitlab.com`
      the result is bare `<owner>/<project-path>`; for any other host the result is
      host-qualified `<host>/<owner>/<project-path>` (carried for masking, same
      host-aware model as GHES).
- [ ] `tests/test_sources.py` (or a new `tests/test_sources_gitlab.py`) covers
      gitlab / gitlab-author dispatch, deferred extraction, URL parse acceptance for a
      nested namespace, and SSRF rejection for IP-literal host, userinfo, and explicit
      port on a GitLab URL.
- [ ] A new test module under `tests/` exercises the JSON→Evidence parser against a
      hand-built `glab mr list` payload (no `glab` invocation), asserting `kind`,
      `ref`, `url`, `detail`, `additions`, and `deletions` are populated as specified
      above, and that the parser is pure (same input → same output, no side effects).
- [ ] A test covers the missing-`glab` path: the extractor's `runner` raises
      `FileNotFoundError`, and the public extractor surface raises a clean exception
      whose message names `glab` and does not contain a traceback frame string.
- [ ] An end-to-end masking test asserts that under `--mask-private` a GitLab private
      project name does not appear in the rendered output: the `gh repo view`
      fail-safe (visibility lookup raises → treat as private → mask) relabels the
      GitLab project, and no raw `<owner>/<project-path>` substring leaks through any
      `Evidence.ref`, `Evidence.url`, `Evidence.detail`, `Claim.text`, or
      `Claim.evidence_refs` field.
- [ ] The GitLab MR ref shape (`<owner>/<project-path>!<iid>`, including nested
      namespaces) does not trigger `assert_maskable` to raise `MaskingError`, and any
      additions to `portfolio/mask.py` (if needed to recognize the `!` separator or
      multi-segment GitLab project keys) leave every existing github.com and GHES
      masking test green byte-for-byte.
- [ ] `bash .redteam/scripts/verify.sh` passes end-to-end (ruff check, ruff format
      check, full pytest with `-x`) with no live `glab` installed on the runner.
- [ ] `README.md` gains a row/section documenting `--source-type gitlab` and
      `--source-type gitlab-author`, the `glab` requirement, and the v1 limitations
      (MR-level fidelity only, fail-safe masking, Bitbucket follow-up).
      `CHANGELOG.md`'s `[Unreleased] / ### Added` section gains an entry describing
      the new source types and `glab` dependency.
- [ ] No new entry is added to the project's pip dependency manifest
      (`pyproject.toml` / `requirements*.txt`); the engine remains stdlib-only and
      `glab` is treated as an optional external CLI (same status as `gh`).

## Out of scope
- Bitbucket and any other SCM beyond GitLab — separate task per the brief.
- A `glab`-based precise visibility lookup for GitLab `--mask-private`; v1 deliberately
  relies on the existing fail-safe (lookup fails → masked).
- GitLab issues, commits, reviews, comments, pipelines, or any non-MR evidence kind.
- Per-MR `glab mr view` (or equivalent) calls to fetch per-file diffs for `kind="file"`
  evidence parity with GitHub — MR-level evidence only in v1.
- Any change to the existing `gh` extraction, source dispatch for `github`/
  `github-author`/`web`/`portfolio`, or `--mask-private` behavior on github.com /
  GHES URLs.
- Any CLI flag rename, removal, or output-format change for existing sources.
- Translation strings (`portfolio/i18n.py`) and rendered Markdown layout changes.

## Affected files
- `portfolio/sources.py` — add `_gitlab_handler` and `_gitlab_author_handler`,
  register both in `_HANDLERS`; add `parse_gitlab_source` (and a
  `_validate_gitlab_author` helper or reuse of the existing GitHub-handle validator
  with a Risk note if reused as-is).
- `(new) portfolio/extract_gitlab.py` — `_run_glab`, `extract_merged_mrs`, the
  author-wide variant, and the pure JSON→Evidence parser; mirrors the seam shape of
  `extract.py::_run_gh` / `extract_merged_prs` / `extract_authored_prs` /
  `parse_pr_evidence`. (Implementer may instead extend `portfolio/extract.py` if the
  diff stays surgical; either path is in budget.)
- `portfolio/mask.py` — minimal extension ONLY if the GitLab MR ref shape
  (`!<iid>`, multi-segment project key) would otherwise leak or trip
  `assert_maskable`; github.com + GHES ref handling must remain byte-identical.
- `(new) tests/test_sources_gitlab.py` — dispatch + URL parse + SSRF rejection +
  nested-namespace acceptance for the gitlab / gitlab-author handlers.
- `(new) tests/test_extract_gitlab.py` — JSON→Evidence parser with a fake `glab`
  payload, injected-runner extractor calls, missing-`glab` clean-error path.
- `(new) tests/test_mask_gitlab.py` — end-to-end masking of a GitLab private project
  under `--mask-private` via the fail-safe.
- `README.md` — document the two new source types, the `glab` requirement, and the
  v1 limitations.
- `CHANGELOG.md` — `[Unreleased] / ### Added` entry for the new source types.

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Existing (must continue to pass)
- `bash .redteam/scripts/verify.sh` — full ruff + ruff-format + pytest suite must
  pass with `-x` and no live `glab` installed.
- `pytest tests/test_sources.py tests/test_extract.py tests/test_mask.py tests/test_mask_ghes.py tests/test_subprocess_encoding.py -x --tb=short`
  — existing github / GHES extraction, source dispatch, masking, and subprocess
  encoding tests must remain green byte-identically.

### To be created (test-author will define exact test names)
- Tests under `tests/` for `portfolio.sources` covering: `gitlab` dispatch resolves
  subject and defers extraction; `gitlab-author` dispatch resolves subject and
  defers extraction; missing `--source` / `--author` raises `ValueError`;
  `parse_gitlab_source` accepts `https://gitlab.com/owner/repo`,
  `https://gitlab.com/group/subgroup/project`, and a self-managed host; rejects
  IP-literal host, `user@host` userinfo, explicit port, non-http(s) scheme,
  query/fragment, and empty/`.`/`..` segments; the host-qualified return form
  matches the GHES pattern for non-`gitlab.com` hosts.
- Tests under `tests/` for the GitLab extractor covering: the pure JSON→Evidence
  parser turns a fake merged-MR payload into one `kind="pr"` Evidence per MR with
  the documented `ref`, `url`, `detail`, `additions`, `deletions`; an injected
  runner is called with a `shell=False`-compatible argv list whose first element is
  `glab` and whose flags include `mr`, `list`, `--author`, `--merged`,
  `--output`/`-F` `json` (whichever the implementer picks — assert the JSON-output
  flag is present); a `FileNotFoundError` from the runner surfaces as a clean
  caught exception naming `glab`; a non-zero exit surfaces as a clean caught
  exception that does not include any token-shaped string from a fake stderr.
- A test under `tests/` for end-to-end masking that runs the pipeline with a fake
  GitLab extractor and an injected `visibility_lookup` that raises (the production
  fail-safe path), then asserts the GitLab private project name appears nowhere in
  the resulting Portfolio's `Evidence.ref` / `Evidence.url` / `Evidence.detail` /
  `Claim.text` / `Claim.evidence_refs` fields.

## Risks
- **Author validation reuse.** GitHub handles are `[A-Za-z0-9-]+`. GitLab usernames
  legally include `.` and `_`. Reusing `_validate_github_author` as-is would reject
  valid GitLab handles. The implementer must decide between (a) a GitLab-specific
  validator with a wider charset, or (b) relaxing the shared validator (would change
  GitHub behavior — not acceptable here). Default: (a). Human gate should confirm.
- **MR ref format.** The brief asks the implementer to "pick a representation and
  document it." Proposed default: `<owner>/<project-path>!<iid>` (matches GitLab's
  conventional `!iid` notation, supports nested namespaces). Confirm at gate.
- **`mask.py` extension scope.** Today `_PR_REF_RE` / `_FILE_REF_RE` and
  `_parse_ghes_ref` only recognize `#<n>` (PR) and `:<path>` (file) separators with
  exactly 2- or 3-segment prefixes. A GitLab ref like `g/sg/p!42` uses `!` and has
  ≥3 prefix segments — without an extension it would (a) not be discovered by
  `extract_repo_names` from `Evidence.ref`, and (b) possibly trip `assert_maskable`
  for unusual shapes. The brief permits minimal extension; the implementer must
  verify discovery still works via `Evidence.url` alone (which is host-agnostic
  today and would catch the GitLab URL), and add ref-side support only if a test
  proves leakage. Risk to flag: the line between "minimal extension" and "weakening
  the masking layer" needs the security reviewer's eye.
- **`glab` JSON field names.** The brief specifies the command
  (`glab mr list --author <user> --merged --output json`) but not the exact JSON
  field names (`iid` vs `number`, `web_url` vs `url`, `title`, `additions`,
  `deletions`, `project` / `references.full`, …). Tests use a fake payload, so
  whatever field names the implementer parses must match what real `glab` actually
  emits — the implementer should cite the `glab` version they verified against, or
  human-gate confirms an authoritative reference.
- **Project scoping flag for `gitlab` (not `gitlab-author`).** `glab` supports
  `--repo <host>/<project>` or running in a project's git working directory. Using
  cwd would be a hidden side-effect; `--repo` is the safer choice. Implementer
  should default to `--repo` and surface this in the docstring.
- **Self-managed GitLab + `--mask-private` over-masking.** The brief explicitly
  accepts the fail-safe behavior (GitLab projects always masked). End users on
  self-managed GitLab who want a public project surfaced unmasked must pass
  `--no-mask-private` (i.e. omit `--mask-private`). Documented as a v1 limitation in
  README.
