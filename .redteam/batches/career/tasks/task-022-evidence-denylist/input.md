+++
mode = "agent-pair"
+++

# Task: exclude generated/IDE/vendored files from evidence (issue #35)

## Goal
Build artifacts, IDE metadata, and vendored dependencies must not count as
authored work. They currently inflate `/rating`'s **Breadth** and
**Stack-Diversity** dimensions because `kind="file"` Evidence is built in
`portfolio/extract.py` with **no path filtering**. Fix at the SOURCE (option B
from issue #35): drop these paths when building `Evidence(kind="file")` so they
never become evidence anywhere — which cleans Breadth/Stack-Diversity AND every
other command's output (portfolio / resume / fit / reference-check).

## Why
`rating/profile.py` counts DISTINCT `kind="file"` refs for Breadth and derives
Stack-Diversity languages from the same set. A repo that commits `target/`,
`.settings/`, `.classpath`, `pom.properties`, etc. gets a free Breadth boost.
Real dogfooding case: `jsj0345` → Grade **B (74)** driven by **Breadth value 50 →
"Wide" → 2 pts**, but of those ~50 file refs only **4** are authored source; the
other ~46 are Eclipse/Maven scaffolding/build output. The metric rewards poor repo
hygiene. Filtering in `extract.py` removes the paths for ALL commands, not just
rating.

## Part A — single shared denylist constant
Add ONE pinned denylist constant (in the same "pinned in code, a model never
contributes" spirit as `_EXT_TO_LANG`). It must be a single shared, tested
constant — NOT duplicated between extract and rating. Match on **path segments /
directory prefixes**, NOT substring. Classes to cover:
- **Build output dirs:** `target/`, `build/`, `dist/`, `out/`, `bin/`, `.next/`,
  `__pycache__/`
- **Vendored deps:** `node_modules/`, `vendor/`, `.venv/`
- **IDE / tooling metadata:** `.settings/`, `.idea/`, `.vscode/`, and the exact
  metadata filenames `.classpath`, `.project`, `.springBeans`, `*.iml`
- **Generated manifests under build dirs:** `META-INF/maven/**`, `m2e-wtp/**`

## Part B — filter in `portfolio/extract.py`
`extract.py` builds `Evidence(kind="file")` in TWO places, with DIFFERENT ref
shapes — both must be filtered through the same matcher:
- single-repo path: `ref = "<path>"` (bare, e.g. `src/App.jsx`)
- github-author path: `ref = "<owner>/<repo>:<path>"` (e.g.
  `Anna-Seo/TeamTestRepository:teamTest/target/classes/log4j.xml`)
The matcher must extract the path component (strip an optional `"<owner>/<repo>:"`
prefix, splitting on the FIRST `:`) and test its `/`-separated segments against the
denylist. `kind="pr"` evidence is unaffected.

## Hard rules
- **Single shared denylist constant**; not duplicated between `extract.py` and
  `rating/profile.py`.
- **Segment / directory matching, not substring.** A real source file whose name
  merely contains a denied word must NOT be over-excluded:
  - `src/components/target.ts` → KEPT (`target` is a filename, not a dir segment
    equal to `target/`)
  - root-level authored build configs `build.gradle`, `pom.xml`, `Makefile` →
    KEPT (they are authored config at repo root, not under a denied dir). Only
    paths WITH a denied directory segment, or matching an exact metadata filename
    / `*.iml`, are dropped. The implementer must decide and document this boundary.
- **Deterministic, stdlib only, no new dependency.**
- **Grounding unchanged:** dropping build-artifact evidence only removes those
  refs; the existing grounding gate already drops claims whose refs all disappear.
  Do not modify the grounding gate.
- **Rubric unchanged:** only the input file set changes; `rating/profile.py` bands
  and points logic stay as-is (Breadth/Stack-Diversity just receive a cleaner set).

## Out of scope
- Reading each repo's actual `.gitignore` at extraction time (network/complexity).
  A pinned denylist is deterministic and matches the existing design.
- Changing the rating rubric, bands, or any scoring math.

## Affected files
- `portfolio/extract.py` — the denylist constant + filtering at BOTH
  `Evidence(kind="file")` sites (single-repo and github-author).
- `tests/` — unit tests per denylist class (build output, vendored, IDE metadata,
  generated manifest); a regression test reproducing the `jsj0345`-style case (file
  evidence mostly `target/`/`.settings/` paths yields Breadth counting only the
  authored source files, and the resulting band/points reflect that); an
  over-match guard (`src/.../target.ts` and root `build.gradle`/`pom.xml` are
  KEPT). Update any existing golden/extract tests whose fixtures legitimately
  contained now-excluded build-artifact paths.
- `README.md` and/or the relevant command doc IF evidence semantics are documented
  there (note that generated/IDE/vendored paths are not counted as evidence).

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

All existing tests stay green (golden outputs updated only where build-artifact
refs were legitimately removed); new tests cover the Done-when above. Closes #35.
