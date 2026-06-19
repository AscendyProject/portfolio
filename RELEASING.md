# Releasing

This project uses [Semantic Versioning](https://semver.org). `pyproject.toml`'s
`[project].version` is the **single source of truth**; `.claude-plugin/plugin.json`
and `portfolio.__version__` must match it (a test enforces this).

## Cut a release

1. **Pick the version** per SemVer (while `0.x`, breaking changes bump the minor):
   - new features → bump **minor** (`0.2.0` → `0.3.0`)
   - bug fixes only → bump **patch** (`0.2.0` → `0.2.1`)
2. **Bump the version in both files** (keep them identical):
   - `pyproject.toml` → `[project].version`
   - `.claude-plugin/plugin.json` → `version`
3. **Update `CHANGELOG.md`**: move items out of `[Unreleased]` into a new
   `## [X.Y.Z] — YYYY-MM-DD` section (Added / Changed / Fixed), and refresh the
   compare/tag links at the bottom.
4. **Verify**: `bash .redteam/scripts/verify.sh` (ruff + pytest; the version-sync
   test must pass).
5. **Commit** on a branch and open a PR; merge after CI is green.
6. **Tag and release** from `main` once merged:
   ```bash
   git checkout main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-from-tag
   ```
   (or paste the CHANGELOG section as the release notes).

## How users update

- **Claude Code plugin:** `/plugin update portfolio@ascendy-portfolio`
- **Source / editable install:** `git pull` (an editable install reflects the
  new code automatically; re-run `pip install -e ".[dev]"` only if dependencies
  changed).
