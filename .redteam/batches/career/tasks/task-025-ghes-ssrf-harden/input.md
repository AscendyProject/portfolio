+++
mode = "agent-pair"
+++

# Task: SSRF-harden GHES host parsing in --source-type github (codex IR-002 / IR-005, follows #46)

## Goal
PR #46 let `--source-type github` accept any dotted host (new `_HOST_RE`) and
delegated host *validity* to `gh`. That opens an SSRF / internal-network-probing
surface: `127.0.0.1`, `169.254.169.254` (cloud metadata), private-range IPs, and
attacker-controlled hosts all reach `gh --repo <host>/<owner>/<repo>`, which then
makes network requests to them. Harden `parse_github_source` so only safe, real
GHES hostnames are accepted. **github.com behavior is byte-identical.**

## Part A — reject SSRF / internal targets (IR-002)
`parse_github_source` (`portfolio/sources.py`) must REJECT with a clear
`ValueError` (BEFORE any `gh` call), never pass through:
- IP-literal hosts, IPv4 and IPv6 — so `127.0.0.1`, `10.x`, `192.168.x`,
  `169.254.169.254`, `[::1]` are refused. Use stdlib `ipaddress` to detect when
  the host parses as an IP and classify it.
- loopback / link-local / private / reserved / unspecified ranges (all rejected;
  any IP-literal host is rejected regardless of range, since GHES is addressed by
  DNS name, not a bare IP).
- github.com → bare `owner/repo` stays EXACTLY as today.
- A real GHES host (a DNS name, not an IP) still works → `host/owner/repo`.

## Part B — reject ambiguous / spoofable authority (IR-005)
- Reject userinfo in the authority: `https://github.com@evil.example/o/r` and
  `https://user@ghe.example.com/o/r` → `ValueError`. (Today the `github.com@evil`
  form silently targets `evil.example` despite *looking* like github.com — this
  is the spoofing risk; reject it explicitly.)
- Reject an explicit port (`https://ghe.example.com:8443/o/r`) → `ValueError`
  (today the port is silently discarded). Document this; nonstandard-port GHES is
  out of scope.
- Single-label hosts: keep the `_HOST_RE` "requires a dot" rule (intranet
  single-label GHES out of scope) but make the rejection explicit and tested.

## Hard rules
- Deterministic; stdlib only (`urllib.parse`, `ipaddress`, `re`); no new dependency.
- **github.com parsing + output BYTE-IDENTICAL** — every existing test in
  `tests/test_sources.py` (and the github.com paths in test_cli/test_fit/
  test_rating/test_reference_check/test_resume_cli) stays green.
- Reject-rather-than-guess: anything that is not a clean github.com URL or a safe
  external DNS GHES host raises `ValueError` before any `gh` invocation. No host
  string reaches `gh --repo` until it passed this validation.
- No `shell=True`; `gh` calls remain argv lists (unchanged).

## Out of scope
- A configured GHES host *allowlist* (possible follow-up). This task rejects
  IP/internal/spoofable forms but still accepts any well-formed external DNS GHES
  host; host *authenticity* beyond SSRF-safety stays delegated to `gh auth`.
- The `--mask-private` GHES gaps (codex IR-001 / IR-003 / IR-004) — separate task.
- IPv6 GHES support (rejected here as part of IP-literal rejection).
- Changing `gh` invocation, extraction, scoring, or any non-`sources.py` behavior.

## Affected files
- `portfolio/sources.py` — `parse_github_source` host validation: IP/internal
  rejection via `ipaddress`, userinfo + port rejection, single-label rejection
  made explicit; github.com path unchanged.
- `tests/test_sources.py` (and any sibling that exercises GHES parsing) — reject
  `127.0.0.1`, `169.254.169.254`, a private IP, `[::1]`, userinfo,
  `github.com@evil.example`, and `:port`; ACCEPT github.com (byte-identical) and a
  real GHES DNS host (`https://ghe.example.com/owner/repo` → `ghe.example.com/owner/repo`);
  assert the `ValueError` messages are clean (single-line, no traceback leak).
- `README.md` / `CHANGELOG.md` — narrow the documented GHES support to "external
  DNS hosts only; IP-literal / userinfo / port forms rejected".

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (especially PR #46's github.com and GHES DNS-host
tests); new tests cover the SSRF / authority rejections. Addresses codex IR-002
and IR-005.
