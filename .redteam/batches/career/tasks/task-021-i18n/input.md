+++
mode = "agent-pair"
+++

# Task: multilingual output — `--lang` + JD auto-detect, full i18n (en + ko)

## Goal
Every command can produce output in a chosen language. `--lang <code>` sets it
explicitly; without it, `resume`/`fit` detect the **JD's language** (deterministic
heuristic) and use that; otherwise English. LLM-written text (claims / headline /
highlights / letter) is generated **in the target language**; deterministic UI text
(titles / headings / labels / placeholders) comes from a **per-language i18n table**.
Ship **en + ko**, structured so adding a language is one table entry.

## Part A — i18n table for deterministic UI strings
Add `portfolio/i18n.py` mapping a language code → every rendered UI string:
- titles (`# Resume`, `# Portfolio`, `# Capability Rating`, `# Fit …`,
  `# Recommendation Letter`), section headings (`## Experience`, `## Skills`,
  `## Contact`, `## Education`, `## Highlights`, `## Assessment`, `## Dimensions`,
  `## Rubric`, the `Other` stack group), and labels (Summary stat line wording,
  `Confidence`, `Evidence refs`, the Contact/Education placeholder fill-in lines,
  the "no grounded …" notices, rubric/band labels).
- `en` and `ko` to start. A test asserts that for `lang="ko"`, **no English UI
  string leaks** into rendered output (every UI string the renderers emit has a ko
  entry).
- The five renderers take a `lang` param and pull UI strings from the table.
  Determinism preserved: same `(input, lang)` → byte-identical output.

## Part B — LLM text in the target language
The narrate / synthesis / letter prompt builders take a language and instruct the
model to respond in it (e.g. append "Write all prose in Korean."). **Grounding is
unchanged** — claims still cite real refs (`owner/repo#n`), which are
language-neutral, and the grounding gate is unaffected by claim-text language.

## Part C — `--lang` flag on all 5 CLIs
- `--lang <code>` (choices = the i18n table's supported langs; default unset).
- Threaded into both the renderer (`lang`) and the prompt builders.

## Part D — JD language auto-detect (resume / fit, when `--lang` omitted)
- `portfolio/i18n.py` `detect_language(text) -> str`: a **deterministic** heuristic
  over Unicode ranges (Hangul syllables/jamo, Kana, CJK ideographs, Latin) returning
  a supported code, defaulting to `en` on ambiguity/empty. No model call, stdlib only.
- `resume`/`fit` call it on the loaded JD text when `--lang` is absent.
  `portfolio`/`rating`/`reference_check` default to `en` when `--lang` is absent
  (they have no JD). An explicit `--lang` always wins over detection.

## Hard rules
- **Grounding unchanged**: refs are language-neutral; the gate, `show_refs`,
  `--mask-private`, and selection scoring all behave identically regardless of lang.
- **Determinism**: renderers are byte-identical for the same `(input, lang)`;
  `detect_language` is deterministic (same text → same code).
- **Extensible**: a new language = one i18n table entry + its LLM prompt name; no
  other code changes. A test pins this (the table drives `--lang` choices).
- **en default** everywhere a language can't be resolved.
- stdlib only; no new dependency; argv-only.

## Out of scope
- Re-translating already-stored Portfolios (re-rendering a stored portfolio in a new
  `--lang` is fine; the stored claim text stays as the model originally wrote it —
  note this in the README).
- RTL languages, locale number/date formatting beyond the string table.
- Languages beyond en + ko in this task (structure must make adding them trivial).

## Affected files
- `portfolio/i18n.py` (new) — the per-language UI-string table, `detect_language`,
  and the supported-language list that drives `--lang` choices.
- `portfolio/render.py`, `resume/render.py`, `fit/render.py`, `rating/render.py`,
  `reference_check/render.py` — `lang` param, pull UI strings from the table.
- narrate / synthesis / letter prompt builders — language instruction.
- `portfolio/cli.py`, `resume/cli.py`, `fit/cli.py`, `rating/cli.py`,
  `reference_check/cli.py` — `--lang` flag; resume/fit JD detection when omitted.
- `tests/` — i18n table completeness (ko has every UI string; no English leak when
  lang=ko); `detect_language` on Korean / English / mixed / empty fixtures;
  `--lang` threads to render + prompt; explicit `--lang` overrides JD detection;
  determinism (same input+lang → identical render); grounding/show_refs/mask
  unaffected by lang.
- `README.md` + the five `.claude/commands/*.md` — document `--lang`, JD
  auto-detect, supported languages (en, ko), and the stored-portfolio note.

## Verification
```yaml
commands:
  - bash .redteam/scripts/verify.sh
```
All existing tests stay green (default lang=en keeps current output); new tests
cover the above.
