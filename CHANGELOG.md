# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **IR-001 — refuse before the first model call:** `resolve_and_optionally_mask`
  now runs the masking guard (`assert_maskable`) on extracted evidence **before**
  any call to the narrate runner or synthesis runner. Previously the guard ran
  after `narrate`, meaning a private GHES repo's raw evidence could be sent to the
  model before the run was refused. The new ordering is:
  `extract → assert_maskable → narrate → ground → mask → synthesize`. When the
  guard raises `MaskingError` no model call has been made; verified by a
  counting-runner test that asserts call-count == 0 for both runners.
- **IR-003 — close the ref-based GHES bypass:** `assert_maskable` now also
  inspects the host label encoded in `ev.ref` in addition to `ev.url`. Evidence
  with an empty `url` but a GHES-style ref (`ghe.host.com/owner/repo#n` — three or
  more segments before `#` / `:`) is refused with `MaskingError`, so there is no
  url-less bypass of the fail-closed guard. The `article` exemption is preserved.
- **GHES host parsing hardened against IP-literal and authority-spoofing inputs**
  (IR-002 / IR-005) — `parse_github_source` now rejects IP-literal hosts in any
  notation (canonical IPv4, legacy short-form, octal, hex, mixed-base, and IPv6
  literals), userinfo in the authority (`user@host`, `github.com@evil.example`),
  and explicit ports (numeric, empty, nonnumeric, out-of-range), all with a
  `ValueError` before any `gh` invocation. Well-formed external DNS GHES hosts and
  all github.com URLs are unchanged. This is syntax-level hardening; a DNS name
  that resolves to an internal IP is not blocked here.

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
