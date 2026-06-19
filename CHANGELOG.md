# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/AscendyProject/portfolio/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/AscendyProject/portfolio/releases/tag/v0.2.0
