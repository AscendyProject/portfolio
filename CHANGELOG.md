# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`--source-type bitbucket`** — Add Bitbucket Cloud REST API 2.0 evidence extraction (repo-scoped, stdlib `urllib`-based). Supports Bearer (`BITBUCKET_TOKEN`) and Basic (`BITBUCKET_USERNAME` + `BITBUCKET_APP_PASSWORD`) auth; best-effort per-PR diffstat with code-only line counts and per-file evidence; SSRF-guarded pagination; injectable fetcher seam for tests with no live network or credentials.
- **GitLab MR change-size + per-file evidence (best-effort)** — each merged MR
  now triggers one additional `glab api projects/<id>/merge_requests/<iid>/changes`
  call (N+1, bounded by `--limit`). When `glab` is authenticated the extractor
  counts code-only added/deleted lines (same denylist as the GitHub path) and
  emits one `kind="file"` Evidence per changed code file. When the call fails
  (no auth, 401, transport error), that MR silently falls back to
  `additions=0 / deletions=0` with no file evidence — no crash, no token/stderr
  leak. Pagination of the `changes` response and binary-file line stats remain
  follow-ups.
- **GitLab support: `--source-type gitlab` and `--source-type gitlab-author`** —
  both source types pull merged Merge Requests as grounded `Evidence` via the
  [`glab` CLI](https://gitlab.com/gitlab-org/cli) (the official GitLab CLI,
  analogous to `gh` for GitHub). `gitlab` is project-scoped (requires `--source`
  with a GitLab project URL and `--author`); `gitlab-author` is token-scoped
  (requires only `--author`, covering all projects the `glab` token can see).
  Nested namespaces (`group/subgroup/project`) are fully supported. Self-managed
  GitLab instances are supported via host-qualified URLs. `glab` is treated as an
  optional external CLI — not a pip dependency — and a missing or unauthenticated
  `glab` produces a clean, actionable error. The masking layer (`--mask-private`)
  uses the existing fail-safe for GitLab (visibility lookup via `gh repo view`
  fails → treated as private → masked); a `glab`-based precise lookup is a
  follow-up. v1 emits MR-level evidence only (no per-file diffs). Bitbucket and
  other SCMs are explicit follow-ups.
- **Optional `card` extra + `--out-card` PNG output** — `pip install 'portfolio[card]'`
  adds `cairosvg` as an optional dependency. Passing a `.png` path to `--out-card` now
  rasterizes the SVG card to PNG bytes via a lazy `cairosvg` import (mirroring the
  `pdf`/`pypdf` pattern). When `cairosvg` is absent, `svg_to_png` raises
  `CardExtraMissingError` and the CLI exits non-zero with a single clean install-hint
  line on stderr; no partial file is written. The `--share` path and `.svg` output are
  unchanged. The rasterizer is injectable (keyword-only `rasterizer=svg_to_png` on
  `rating.cli.run`) so the full test suite runs without `cairosvg` installed.
- **SVG capability card renderer (`portfolio/card.py`) + `rating --out-card`** — a
  deterministic, stdlib-only SVG card renderer (`render_card(profile_result,
  grade_result, *, subject, lang, verify_url)`) with no new runtime dependency. The
  card shows the grade letter, numeric score, up to three grounded strength bullets
  (from `grade_result.reasoning`), an i18n tagline
  (`LANGS[lang]["card_tagline"]` — en + ko), and an optional verify URL. Every
  interpolated value is XML-escaped via `xml.sax.saxutils.escape`/`quoteattr`; the
  card is byte-deterministic (same inputs → identical bytes) and self-contained (no
  external fonts, images, or scripts). Pass `--out-card <file>` to write the card to a
  local file (independent of `--share`); an OSError on write exits non-zero with a
  single clean stderr line.
- **Multi-file gist publish (`portfolio/share.py`)** — `Sharer.publish` and
  `GistSharer.publish` now accept a keyword-only `extra_files: dict[str, str] | None =
  None`. When `None` (default), behavior is byte-identical to the previous release.
  When non-None, all files (primary Markdown + each `extra_files` entry) are written
  into a `tempfile.TemporaryDirectory()` (auto-cleaned) and passed as argv file paths
  to `gh gist create` (no `shell=True`, no stdin, no named temp files). Added
  `gist_raw_url(gist_url, filename) -> str` — a pure string transform that derives
  `https://gist.githubusercontent.com/<user>/<id>/raw/<filename>` from
  `https://gist.github.com/<user>/<id>`.
- **`rating --share` publishes the SVG card as a second gist file and prints a README
  badge snippet** — under `--share`, the CLI renders the SVG card, passes it to
  `Sharer.publish` as `extra_files={f"{title}.svg": card_svg}` (alongside the primary
  Markdown), and — after a successful publish — prints a ready-to-paste README badge
  line (`![Capability rating](<raw_url>)`) after the existing gist URL + social links.
  Masking applies: the card body, subject, and `.svg` filename are all scrubbed with
  `_rewrite_text` against the same relabel map as the shared Markdown. The
  single-clean-stderr-line-on-failure contract (IR-003) is preserved; the badge snippet
  is NOT printed on the failure path.
- **`rating --share` — publish to GitHub Gist + social share links** — pass
  `--share` to publish the rendered rating to a secret GitHub Gist (via `gh gist
  create`) and print pre-filled LinkedIn and X (Twitter) intent URLs. `--share-public`
  makes the Gist public. Privacy-first by default: `--share` auto-enables masking of
  private repo names; pass `--no-mask-on-share` to opt out (explicit `--mask-private`
  always wins). The provenance footer (`LANGS[lang]["share_provenance_footer"]`) is
  appended to the published Markdown only; the non-share render path is byte-identical
  to the pre-change behavior.
- **GHES private repos are now MASKED end-to-end for `--mask-private`, not
  refused (IR-004)** — previously `assert_maskable` failed closed on any
  non-github.com host, so a developer split across github.com and a GitHub
  Enterprise Server instance could not anonymize the GHES half. Now well-formed
  GHES identities (URL or `host/owner/repo` ref) flow through discovery,
  visibility lookup, and relabeling exactly like github.com repos. The guard is
  relaxed to a true final invariant: it refuses **only a malformed identity** the
  masking layer cannot decompose (unparseable/absent URL host, a URL path with no
  `owner/repo`, or a host-qualified ref that does not yield a valid
  `host/owner/repo`). Visibility-lookup failure is not a refusal — the fail-safe
  treats it as private and masks. Free text is scrubbed of both the full
  `host/owner/repo` and the bare `owner/repo` form of a masked GHES repo, so a
  GHES name cannot leak via `detail` / `context` / `claim.text`.
- **GHES host-qualified discovery for `--mask-private` (IR-004)** —
  `extract_repo_names` now discovers repo identities from any DNS host, not
  just github.com.  Non-github.com repos are keyed as `host/owner/repo`
  (lowercase); github.com repos keep the existing bare `owner/repo` key for
  full backward compatibility — github.com masking output is byte-identical to
  the previous release for all existing tests.  The single changed expectation
  is `test_extract_non_github_url_yields_nothing`, which now asserts the
  host-qualified key is collected rather than an empty set.
- **Host-aware visibility lookup** — `_gh_visibility_lookup` now accepts both
  bare `OWNER/REPO` (github.com) and `HOST/OWNER/REPO` (GHES) keys; the
  `gh repo view` argv is the same shape, with the full host-qualified path for
  GHES repos.  The fail-safe (exception / non-zero exit / malformed JSON →
  treat as private) applies identically to GHES hosts.
- **Case-insensitive relabeling** — `_rewrite_ref`, `_rewrite_text`, and the
  URL rewrite pass in `mask_portfolio` now use case-insensitive matching, so
  mixed-case occurrences of a private repo name in `ref`, `url`, `detail`,
  `context`, `claim.text`, and `claim.evidence_refs` are all replaced.
  Owner/repo identity is normalized to lowercase, so `Owner/Repo` and
  `owner/repo` map to a single key per host.
- **#48 calibration spike, exit-(a) — criterion-referenced regression guards:** locked the
  spike conclusion ("the bars discriminate sanely") as permanent regression tests in
  `tests/test_rating_calibration.py` (monotonicity, trivial floor, top-reachable,
  no-collapse, and docs-framing checks). Added criterion-referenced / "not a percentile"
  framing to `rating/profile.py`, README, and CHANGELOG. No scoring behavior change.
- **PDF job-description files for `--jd`** (`resume` / `fit`) — a local `--jd` is now
  detected by its `%PDF-` signature (not the extension) and its text extracted, so a
  PDF JD works without converting first. Extraction uses `pypdf`, gated behind an
  optional `pdf` extra (`pip install 'portfolio[pdf]'`) and imported lazily so the
  core install stays dependency-free; without it, a PDF `--jd` gives a clear,
  actionable error. A scanned/image-only PDF (no extractable text) is rejected
  rather than silently producing an empty JD (#66).
- **`fit --jd-dir` reads PDFs too** — batch mode now globs `*.pdf` alongside
  `*.txt`/`*.md` and extracts each through the same `load_jd` path as single
  `--jd`, so a directory of PDF JDs is scored consistently (#70).

### Security
- **DR-004 rating output-gate guard:** enforced the no-percentile/population/ranking rule at the rating output gate by drop-filtering reasoning bullets containing banned percentile/ranking lexicons (closes #60).
- **IR-001 — refuse before the first model call:** `resolve_and_optionally_mask`
  now runs the masking guard (`assert_maskable`) on extracted evidence **before**
  any call to the narrate runner or synthesis runner. Previously the guard ran
  after `narrate`, meaning a private GHES repo's raw evidence could be sent to the
  model before the run was refused. The new ordering is:
  `extract → assert_maskable → narrate → ground → mask → synthesize`. When the
  guard raises `MaskingError` no model call has been made; verified by a
  counting-runner test that asserts call-count == 0 for both runners.
- **IR-003 — inspect the host label encoded in `ev.ref`:** `assert_maskable`
  inspects both `ev.url` and the host label encoded in `ev.ref`, so a url-less
  GHES-style ref (`ghe.host.com/owner/repo#n` — three or more segments before
  `#` / `:`) is never silently passed through. A **well-formed** such ref is now
  masked (see the GHES masking entry above); only a **malformed** host-qualified
  ref trips the fail-closed guard. The `article` exemption is preserved.
- **GHES host parsing hardened against IP-literal and authority-spoofing inputs**
  (IR-002 / IR-005) — `parse_github_source` now rejects IP-literal hosts in any
  notation (canonical IPv4, legacy short-form, octal, hex, mixed-base, and IPv6
  literals), userinfo in the authority (`user@host`, `github.com@evil.example`),
  and explicit ports (numeric, empty, nonnumeric, out-of-range), all with a
  `ValueError` before any `gh` invocation. Well-formed external DNS GHES hosts and
  all github.com URLs are unchanged. This is syntax-level hardening; a DNS name
  that resolves to an internal IP is not blocked here.
- **PDF `--jd` input limits** (codex IR-001) — a PDF/file job description is now
  bounded against resource exhaustion: file size ≤ 20 MiB (checked via `stat`
  before the bytes are read), ≤ 500 pages, ≤ 2M extracted characters (each page
  rejected immediately if it would exceed the cap, before accumulation), and
  encrypted PDFs are refused. A malicious or malformed local PDF can no longer
  drive memory/CPU exhaustion. (`pypdf`'s `extract_text()` is not streamable, so a
  single page is still materialized before measurement; full subprocess/timeout
  isolation is a documented follow-up.)

### Changed
- **`fit --jd-dir` validates every JD before building** (codex IR-002) — batch mode
  now reads/validates all JD files up front, so a bad / encrypted / oversized JD
  fails fast with exit 2 instead of after the expensive portfolio build; the loaded
  text is reused for scoring (no double read).
- **Rating stack-diversity taxonomy expanded; `.h` no longer double-counts C/C++**
  (codex IR-006) — added common languages previously dropped to `other` (Vue,
  Svelte, Objective-C, F#, Solidity, Zig, Julia, Perl, Groovy, Erlang, Nim, OCaml,
  Elm, Crystal), so real work in them now counts toward diversity instead of
  scoring zero. Header extensions (`.h`/`.hpp`/`.hh`/`.hxx`) are excluded from the
  diversity COUNT (a header follows its companion source), so a `.cpp`+`.h`
  project is C++ once, not C + C++; headers still resolve to a display language via
  `language_for_ref`. Extension-precedence only — no content detection.

## [0.5.0] — 2026-06-24

A rating that finally discriminates at the top: the grade now comes from a single
continuous capability score, so two strong developers no longer collapse to the
same number — plus `--limit` to pull more of a prolific author's history.

### Changed
- **Rating grade is now derived from a single continuous capability score** —
  replaces the discrete points→grade (4 dims × 0/1/2). Each metric is mapped
  through a piecewise curve toward absolute, product-defined anchors, weighted
  into a 0–100 score (shown to one decimal); the grade is the band that score
  falls in. This fixes a clustering the points model still had: strong developers
  who maxed volume/breadth/diversity all landed on the *same* score (~92) — the
  curves now keep large values separated, so a 200-PR and a 100-PR developer
  differ. A **substance cap** (median changed lines/PR) stops a high-volume bot of
  trivial PRs from reaching a top grade, and an **S guard** keeps S rare (genuinely
  all-around-substantial work only). Per-dimension `points` are gone from the
  scorecard (the grade is no longer their sum); dimensions still show value + band.
  Designed and validated on real portfolios via an adversarial Claude↔codex review
  (#48).

### Added
- **`--limit` flag on `python -m portfolio`** — control how many merged PRs the
  `github` / `github-author` sources pull (default 100, unchanged). Raise it to
  capture more of a prolific author's history when 100 truncates the evidence;
  threaded through the source dispatcher to the `gh` extractors.

## [0.4.0] — 2026-06-24

Wider reach and a de-saturated rating: evaluate GitHub Enterprise Server repos,
and a rating that actually discriminates — config/doc files no longer inflate the
score, change size counts, and the score is a deterministic, metric-driven number
instead of everyone landing on 98.

### Added
- **GitHub Enterprise Server support** — `--source-type github` now accepts a
  GHES repo URL (e.g. `https://ghe.example.com/<owner>/<repo>`); the host is
  passed through to `gh` as `[HOST/]OWNER/REPO` so the call routes to that server
  (requires `gh auth login --hostname <host>`). github.com URLs are unchanged
  (#45).
- **Rating change-scale dimension** — the rating now scores the **median changed
  lines (additions + deletions) per PR**, counting code files only (generated,
  vendored, lockfile, and config/doc files excluded so a reformat or regenerated
  lockfile can't inflate it). `Evidence` gained `additions`/`deletions` fields
  (populated by the `gh` extractors, serialized in portfolio JSON with backward-
  compatible defaults). The grade is now four dimensions (max 8 pts) with a
  re-tuned points→grade table, so **S requires substantial typical change size in
  addition to volume/breadth/diversity** — it is no longer reachable on PR/file/
  language counts alone (#50, toward de-saturating the rating, #48).
- **Rating sub-tier suffix** — each letter grade now carries a `+`/flat/`-` suffix
  (e.g. `B+`, `B`, `B-`) from the deterministic score's position within its band
  (top third → `+`, middle → flat, bottom → `-`). Refines the grade without
  changing it, so two same-grade developers are visibly ordered (#48).
- **Rating "How to Improve" section** — the scorecard now explains, per dimension,
  why the score is what it is and what would raise it: each dimension is either
  marked maxed or shows the next band and the exact raw delta needed (e.g.
  `Volume: Steady → High (≥20, +12)`). Deterministic rubric arithmetic over the
  developer's own metrics — no model, no population comparison (localized en/ko)
  (#55).

### Changed
- **Rating stack diversity counts programming languages only** — config, data,
  markup, and documentation files (YAML, JSON, Markdown, HTML, CSS) no longer
  count as distinct "languages", so a repo's ubiquitous README/CI/manifest files
  can't inflate the diversity dimension (and thus the grade). Real code languages
  (Python, Go, SQL, Shell, …) are unchanged (#49).
- **Rating stack diversity no longer counts the "other" bucket** — files with an
  unmapped extension (`.toml`, `.ini`, `.lock`, `Dockerfile`, `Makefile`, and any
  truly-unknown extension) collapsed to the single literal `other` language, which
  let config/build/junk files inflate the diversity dimension for free. They are
  now excluded from the count (we do not credit what we cannot name); `language_for_ref`
  still reports `other` for display (#59).
- **Rating score is now deterministic and continuous** — the precise 0–100 score
  within the locked grade band is computed as a continuous function of the
  dimension metrics (each normalized against a pinned ceiling, interpolated within
  the band), instead of being picked by the agent. Two developers in the same band
  now get different, metric-driven scores rather than clustering on the band
  midpoint (the "everyone gets 98" problem). The agent is consulted only for the
  grounding-checked reasoning and can change neither the grade nor the score (#52).

## [0.3.0] — 2026-06-21

Readability and reach: output is cleaner by default, resume gets a standard
layout, portfolios merge across accounts, and every command can speak Korean.

### Added
- **Multilingual output** — `--lang en|ko` on all five commands; both LLM-written
  prose and deterministic UI strings are localized. When `--lang` is omitted,
  `resume`/`fit` auto-detect the JD's language; a Unicode-aware JD tokenizer makes
  non-ASCII (e.g. Korean) JDs produce real keywords. Grounding is unchanged —
  refs stay language-neutral (#33).
- **`portfolio merge`** — union two or more saved Portfolio JSONs (e.g. corporate
  + personal accounts) into one grounded Portfolio, re-grounded on merge, with a
  guard against silently coalescing bare cross-source refs (#32, issue #30).

### Changed
- **Grounding refs hidden by default** — rendered output omits inline `[refs]` for
  readability; pass `--show-refs` to reveal them (#29).
- **Resume standard layout** — `/resume` renders a Summary stat line, Experience
  grouped by stack, and a Skills section instead of a flat claim list (#31).

## [0.2.0] — 2026-06-19

First tagged release. The grounded engine now backs five commands, gathers
evidence across all of a developer's repos, reuses a saved portfolio, and can
anonymize private repos before sharing.

### Added
- **Five grounded commands** over one evidence engine: `/portfolio` (#1, #6),
  `/resume` (#2, #9), `/reference-check` (#10), `/fit` (#12), `/rating` (#11).
  Every rendered claim traces to real evidence; un-grounded claims are dropped.
- **`github-author` source** — gather merged-PR evidence across *all* repos a
  token can see, not just one, with cross-repo-unique refs (#14).
- **Pluggable web/article source** alongside GitHub (#4, #5, #7).
- **`--jd` accepts an http(s) URL** (not just a file path) for `resume` and `fit`,
  fetched through the SSRF-guarded web layer (#22).
- **Grounded synthesis** — `/portfolio` renders a finished document (headline +
  stats + stack grouping + highlights) instead of a flat claim list (#23).
- **Save & reuse** — `portfolio --emit-portfolio` writes a grounded Portfolio as
  JSON; `--source-type portfolio` loads it (re-grounded, no re-narration) so
  `resume`/`fit`/`rating`/`reference-check` reuse the same evidence (#25).
- **`--mask-private`** — anonymize private-repo names in any output before
  sharing, with grounding preserved and a fail-safe on unknown visibility (#26).
- **Installable Claude Code plugin** (`portfolio@ascendy-portfolio`) (#15).
- **OSS hygiene** — CI (ruff + pytest on 3.11/3.12), `SECURITY.md`,
  `CONTRIBUTING.md`, Dependabot (#13, #20).

### Fixed
- **Non-UTF-8 Windows (cp949)** — decode child-process output as UTF-8, pass
  prompts via stdin, and force UTF-8 Markdown on stdout, across all CLIs (#17, #19).

### Changed
- Dropped the `ascendy-` prefix; the harness/repo is now `portfolio` (#8).
- Upgraded the vendored redteam harness to 0.4.0 (#21).

[Unreleased]: https://github.com/AscendyProject/portfolio/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/AscendyProject/portfolio/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/AscendyProject/portfolio/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/AscendyProject/portfolio/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/AscendyProject/portfolio/releases/tag/v0.2.0
