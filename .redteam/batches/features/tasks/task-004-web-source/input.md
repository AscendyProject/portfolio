# Task: web/blog article source — the second extractor behind the dispatcher

## Goal
Implement a `web` source type so a developer's blog/article URL can be turned
into grounded Evidence, plugged in behind the task-003 dispatcher. This makes
the dispatcher's "register a handler, no CLI change" seam real with a second
source, and delivers the blog branch of the original vision (github → `gh`,
blog → crawl the article).

## What to build
- A new module `portfolio/web.py`:
  - `parse_web_source(url) -> str` — validate and normalize an article URL:
    require `http(s)`, a non-empty host, reject obviously-internal hosts
    (`localhost`, and private/loopback/link-local **IP literals** like
    `127.0.0.1`, `10.x`, `192.168.x`, `169.254.x`), drop any fragment. Raise
    ValueError otherwise (reject rather than guess).
  - `fetch_html(url) -> str` — the network seam: fetch the page with stdlib
    `urllib.request`, a request timeout, a response **size cap** (truncate, don't
    read unbounded), and a User-Agent. Raises `RuntimeError` on transport/HTTP
    failure.
  - `extract_article_evidence(url, html) -> list[Evidence]` — **pure** parser:
    pull the `<title>` (stdlib `html.parser`), return a single
    `Evidence(kind="article", ref=url, url=url, detail=<title>)`. No title → a
    clear fallback detail (e.g. empty), never invent one. Do not escape here —
    the renderer already escapes Markdown-significant text.
- Add `"article"` to `EVIDENCE_KINDS` in `portfolio/model.py`.
- Register a `web` handler in `portfolio/sources.py`:
  - `SourceRequest` gains a `fetcher` seam (default `fetch_html`) alongside
    `extractor`; the `web` handler validates the URL + author now and defers the
    fetch+parse to `extract()` using `request.fetcher`.
  - Retire the `others` placeholder: `_UNIMPLEMENTED_SOURCE_TYPES` becomes empty;
    `known_source_types()` now yields `("github", "web")`. Unknown types still
    raise `UnsupportedSourceError`.
- Wire `portfolio/cli.py`: `run()` gains a `fetcher` seam (default `fetch_html`)
  passed through on the `SourceRequest`, so a `web` run is unit-testable without
  the network. `--source` help text generalized (URL, not "GitHub repo URL").

## Constraints / hard rules (see project-context + security-checklist)
- Grounding unchanged: the article becomes Evidence; the model may only cite it;
  the grounding gate still drops anything citing a non-existent ref. The CLI
  renders grounded claims only.
- The fetch is the only network. It must be an **injectable seam** (`fetcher` on
  `SourceRequest`/`run`) so no test hits the network (per test-conventions).
- SSRF guard is best-effort and offline: scheme + IP-literal/localhost checks
  only. Full DNS-resolution / redirect-target SSRF (and DNS rebinding) is
  **out of scope** for this CLI (the user supplies their own URL) — note it, do
  not half-build it.
- stdlib only (`urllib`, `html.parser`, `ipaddress`, `socket` if needed). No new
  deps, no HTML/markdown libraries.
- Behavior preserving for `github`: the github path is untouched.

## Out of scope
- DNS-based SSRF / redirect-target validation / rebinding protection.
- Multi-page crawling, JS rendering, readability/main-content extraction beyond
  the `<title>` (a richer body extractor can be a later task).
- The `/portfolio` slash command (task-005).
- Changing narrate / grounding / render behaviour.

## Affected files
- `(new) portfolio/web.py`
- `(modified) portfolio/model.py` — add `"article"` to `EVIDENCE_KINDS`
- `(modified) portfolio/sources.py` — `web` handler, `fetcher` seam on
  `SourceRequest`, retire `others`
- `(modified) portfolio/cli.py` — `fetcher` seam, generalized help
- `(new) tests/test_web.py`
- `(modified) tests/test_sources.py` / `tests/test_cli.py` — web dispatch + a
  web CLI run with an injected fetcher; drop the obsolete `others` test

## Verification

```yaml
commands:
  - bash .redteam/scripts/verify.sh
```

### Notes
Tests (inject a fake `fetcher`; build objects directly; no network):
- `parse_web_source` accepts a normal `https://blog.example.com/post`; rejects
  `file://...`, `http://localhost/x`, `http://127.0.0.1/x`,
  `http://192.168.0.1/x`, empty host, non-http scheme.
- `extract_article_evidence` turns canned HTML with `<title>X</title>` into one
  `Evidence(kind="article", ref=url, detail="X")`; HTML without a title yields a
  clear fallback (no invented title); a hostile `<title>` is passed through raw
  (renderer escapes).
- dispatcher: `resolve_source("web", req with fake fetcher)` defers fetch until
  `extract()`; the fetcher is not called until then.
- CLI: `--source-type web --source <url> --author alice` with an injected fetcher
  + fake runner renders a portfolio whose grounded claim cites the article ref;
  `known_source_types()` == `("github", "web")`.

## Risks
- SSRF scope creep — keep the guard offline + documented; don't attempt DNS
  resolution (it would also force tests onto the network).
- `EVIDENCE_KINDS` is currently informational (not enforced by grounding/render);
  adding `"article"` must not change existing behaviour for `pr`/`file`.
- Seam plumbing: `fetcher` must thread `SourceRequest` -> `run()` cleanly without
  disturbing the `extractor` seam or the github path.
