# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Rating "How to Improve" section** — the scorecard now explains, per dimension,
  why the score is what it is and what would raise it: each dimension is either
  marked maxed or shows the next band and the exact raw delta needed (e.g.
  `Volume: Steady → High (≥20, +12)`). Deterministic rubric arithmetic over the
  developer's own metrics — no model, no population comparison (localized en/ko)
  (#55).
- **Rating sub-tier suffix** — each letter grade now carries a `+`/flat/`-` suffix
  (e.g. `B+`, `B`, `B-`) from the deterministic score's position within its band
  (top third → `+`, middle → flat, bottom → `-`). Refines the grade without
  changing it, so two same-grade developers are visibly ordered (#48).

### Changed
- **Rating score is now deterministic and continuous** — the precise 0–100 score
  within the locked grade band is computed as a continuous function of the
  dimension metrics (each normalized against a pinned ceiling, interpolated within
  the band), instead of being picked by the agent. Two developers in the same band
  now get different, metric-driven scores rather than clustering on the band
  midpoint (the "everyone gets 98" problem). The agent is consulted only for the
  grounding-checked reasoning and can change neither the grade nor the score (#48).

### Added
- **Rating change-scale dimension** — the rating now scores the **median changed
  lines (additions + deletions) per PR**, counting code files only (generated,
  vendored, lockfile, and config/doc files excluded so a reformat or regenerated
  lockfile can't inflate it). `Evidence` gained `additions`/`deletions` fields
  (populated by the `gh` extractors, serialized in portfolio JSON with backward-
  compatible defaults). The grade is now four dimensions (max 8 pts) with a
  re-tuned points→grade table, so **S requires substantial typical change size in
  addition to volume/breadth/diversity** — it is no longer reachable on PR/file/
  language counts alone (#50, toward de-saturating the rating, #48).

### Changed
- **Rating stack diversity counts programming languages only** — config, data,
  markup, and documentation files (YAML, JSON, Markdown, HTML, CSS) no longer
  count as distinct "languages", so a repo's ubiquitous README/CI/manifest files
  can't inflate the diversity dimension (and thus the grade). Real code languages
  (Python, Go, SQL, Shell, …) are unchanged. First step toward de-saturating the
  rating, which currently maxes out at S for most active developers.

### Added
- **GitHub Enterprise Server support** — `--source-type github` now accepts a
  GHES repo URL (e.g. `https://ghe.example.com/<owner>/<repo>`); the host is
  passed through to `gh` as `[HOST/]OWNER/REPO` so the call routes to that server
  (requires `gh auth login --hostname <host>`). github.com URLs are unchanged
  (#45).

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

[Unreleased]: https://github.com/AscendyProject/portfolio/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/AscendyProject/portfolio/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/AscendyProject/portfolio/releases/tag/v0.2.0
