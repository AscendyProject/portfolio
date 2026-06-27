+++
mode = "agent-pair"
+++

# Task: real GitHub Enterprise Server masking for --mask-private (codex IR-004, follows #58/#68)

## Goal
#58/#68 made `--mask-private` FAIL CLOSED on non-github.com hosts (refuse rather
than risk emitting a private GHES repo unmasked). The real capability is to MASK
GHES private repos, not just refuse them, so a developer split across github.com +
a GHES instance can anonymize both. Teach the masking layer about enterprise hosts
end-to-end, keeping `assert_maskable` as a final fail-closed invariant for anything
still unmaskable.

## Background (current state)
`portfolio/mask.py` assumes github.com: `extract_repo_names` collects only
`_MASKABLE_HOSTS` ({github.com, www.github.com}) refs; `_gh_visibility_lookup` runs
`gh repo view OWNER/REPO`; relabel/rewrite operate on bare `owner/repo`. A GHES ref
is `host/owner/repo#n` (refs already carry the host — `_ref_host` extracts it), and
a GHES url is `https://host/owner/repo/...`. `assert_maskable` currently refuses any
non-github.com host. The task-026 invariant (mask before any model call) is in
`pipeline.resolve_and_optionally_mask`.

## Part A — host-qualified repo identity
`extract_repo_names` collects repo identities from github.com AND **any
non-github.com repo host** (a GHES host like `github.acme.com`, but also any other
DNS host that appears in a repo-shaped ref/url — GHES and e.g. `gitlab.com` are
INDISTINGUISHABLE as DNS hosts, so collection is host-agnostic; whether a host is
actually *maskable* is decided at runtime in Part D, not statically). Represent
each as a host-qualified key (e.g. `"host/owner/repo"`, with github.com keyed as
bare `"owner/repo"` for backward compatibility — OR a normalized
`(host, owner, repo)`; implementer's choice, documented). Reuse `_ref_host` /
`_parse_ref`. **Case-normalize** owner/repo (GitHub identity is case-insensitive)
so `Owner/Repo` and `owner/repo` map to one identity.

**Test impact (important):** the existing `test_extract_non_github_url_yields_nothing`
asserts a non-github host yields an EMPTY set. Under this task a non-github host IS
now collected (host-qualified) and instead refused later by `assert_maskable`
(Part D). UPDATE that test accordingly — the non-github host is collected by
`extract_repo_names` but refused by `assert_maskable`; do NOT keep expecting an
empty set from `extract_repo_names`.

## Part B — host-qualified visibility
`_gh_visibility_lookup` accepts a host-qualified repo and runs
`gh repo view [HOST/]OWNER/REPO --json isPrivate` so visibility is checked on the
correct server (github.com → bare; GHES → host-prefixed). Same fail-safe as today:
a lookup error / unparseable output → treat as PRIVATE (mask), never as public.

## Part C — host-aware relabel + rewrite
`_build_relabel_map` / `_rewrite_ref` / `_rewrite_text` relabel private repos
regardless of host, deterministically and case-insensitively, across refs, urls,
`detail`, `context`, and claim text. A mixed github.com + GHES portfolio gets
stable, collision-free `private-repo-N` labels.

## Part D — assert_maskable becomes a true final invariant
Once GHES is maskable, `assert_maskable` NO LONGER refuses a non-github.com host
outright. It stays the LAST-LINE fail-closed check: it refuses only when an
evidence identity cannot be resolved to a host-qualified repo the masking layer can
handle (e.g. a host the visibility lookup can't reach / unauthenticated), so the
masking guarantee still holds — no private repo (github.com OR GHES) is ever
emitted unmasked. Keep the `article` exemption.

## Part E — mask before model (preserved invariant)
The task-026 ordering (`assert_maskable` + mask BEFORE any narrate/synthesis model
call) is preserved: GHES masking runs in the same pre-narrate position.

## Hard rules
- Deterministic; stdlib + `gh` only; no new dependency.
- The masking GUARANTEE holds: on `--mask-private`, no private repo on ANY host is
  emitted unmasked — proven by tests (github.com, GHES, mixed) AND a fail-closed
  test when visibility can't be determined.
- **github.com masking stays BYTE-IDENTICAL** (existing `tests/test_mask.py` green).
- Refs already carry host provenance; do NOT bump `SCHEMA_VERSION` unless a stored
  field genuinely must change (justify if so) — prefer deriving host from ref/url.
- `gh` calls are argv lists; no `shell=True`; no secrets in error messages.

## Out of scope
- Multi-account auth / token juggling across hosts (the user supplies a `gh`
  authenticated to each host; `gh repo view HOST/...` uses it).
- Changing extraction, scoring, or any non-mask output.
- The SSRF host-syntax hardening (already shipped, #67) — reuse it; don't redo it.

## Affected files
- `portfolio/mask.py` — host-aware `extract_repo_names`, `_gh_visibility_lookup`,
  `_build_relabel_map` / `_rewrite_ref` / `_rewrite_text`, and the
  relaxed-but-still-fail-closed `assert_maskable`.
- `portfolio/pipeline.py` — only if the mask call site needs a host-aware argument
  (prefer no change).
- `tests/test_mask.py` — GHES private repo masked end-to-end; mixed github.com+GHES
  deterministic + collision-free labels; case-normalized identity; visibility-failure
  → fail-closed (never emitted unmasked); github.com byte-identical.
- `README.md` / `CHANGELOG.md` — `--mask-private` now masks GHES repos (no longer
  refuses them).

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (especially github.com masking byte-identical); new
tests cover GHES + mixed-host + fail-closed. Addresses codex IR-004.
