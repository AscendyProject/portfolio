## What
A developer on GitLab can run the same `portfolio` / `resume` / `fit` / `rating` /
`reference-check` flows on their merged Merge Requests by passing
`--source-type gitlab` (project-scoped) or `--source-type gitlab-author`
(token-scoped, all visible projects). Evidence is pulled deterministically from the
`glab` CLI (mirroring how `gh` is used for GitHub), with no live `glab` required to
run the test suite and no change in github / GHES behavior.

## Why
Issue #47: evidence extraction was GitHub-only (`portfolio/extract.py::extract_merged_prs`
shells `gh`). The existing handler registry in `portfolio/sources.py` was designed to
"register a handler and it becomes CLI-usable with no CLI change," so adding GitLab is
mostly a new extractor + new handlers. `glab` is GitLab's official CLI and mirrors `gh`
(`glab mr list --author <user> --merged --output json`), making it the natural first
non-GitHub SCM adapter. Bitbucket and other SCMs are explicit follow-ups (no first-class
CLI; different plumbing).

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

## Verification
- Tests: `tests/test_sources_gitlab.py` (21 tests — dispatch, deferred extraction, nested-namespace URL parse, SSRF rejection, author-handle validation); `tests/test_extract_gitlab.py` (27 tests — pure JSON→Evidence parser, injected-runner argv assertions, missing-`glab` clean error, non-zero exit handling, token-redaction on `_run_glab`); `tests/test_mask_gitlab.py` (18 tests — `_extract_repo_names` GitLab-URL coverage, `assert_maskable` GitLab-ref shapes, end-to-end fail-safe masking across `Evidence.ref`/`.url`/`.detail` and `Claim.text`/`.evidence_refs`, github/GHES byte-identical regression).
- Verify command: `bash .redteam/scripts/verify.sh` ✅ (ruff check, ruff format check, full pytest `-x`: 1099 passed, 2 skipped — no live `glab`).

## Code review summary
- Diff: `portfolio/sources.py` (+130, gitlab/gitlab-author handlers + `parse_gitlab_source` + handle validator), new `portfolio/extract_gitlab.py` (+211, `_run_glab`, `extract_merged_mrs`, `extract_authored_mrs`, pure parser), `portfolio/mask.py` (+39/−12, minimal `!iid` + nested-namespace ref recognition), `README.md` and `CHANGELOG.md` doc updates, three new test files (+1074).
- Done-when met: both source types CLI-usable with no `cli.py` change; deferred extraction; nested-namespace URL acceptance + SSRF hardening matched to `parse_github_source`; stable `<owner>/<project-path>!<iid>` ref documented; argv subprocess with injectable runner; bounded stderr + token redaction in error path; end-to-end fail-safe masking verified.
- `_run_glab` sanitizes a bounded stderr slice before raising — no raw GitLab token-shaped values reach the CLI error boundary (`portfolio/extract_gitlab.py:54-82`); `tests/test_extract_gitlab.py:375-398` patches the real `subprocess.run` with token-bearing stderr and asserts the token is absent from the raised message.
- github / GHES extraction, source dispatch, and masking tests remain byte-identical; no runtime dependency manifest changes; grounding/scoring/rubric layers untouched.
- No HIGH findings from the project security scanner; both prior IR items (IR-001 token-leak, IR-002 insufficient test) resolved.
- Independent reviewer (codex) `REVIEW_DECISION: APPROVED`.

## Generated by
redteam / batch scm-gitlab / task task-034-gitlab-extract
