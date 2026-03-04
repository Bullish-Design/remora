# Context — Playwright Web Clipper

## Current State
Project is **complete**. All source code, tests, and NixOS compatibility fix are implemented.

## Final Results
- **79 unit tests** + **4 integration tests** = **83 total**, all passing
- Main repo tests verified: 988 passed, no regressions from browser_demo
- NixOS shared library issue resolved via `_find_system_chromium()` auto-detection

## What Was Built
A standalone Playwright-based web clipper in `browser_demo/` with:
- Pydantic models for clip metadata, records, fetch results
- SQLite-backed clip store with FTS5 full-text search
- HTML-to-markdown converter using BeautifulSoup + markdownify
- Async Playwright fetcher with system chromium auto-detection
- Clipper orchestrator composing the fetch → convert → store pipeline
- Typer CLI with commands: clip, list, show, search, delete, export, tags

## Key Files
- Source: `browser_demo/src/browser_demo/{models,store,converter,fetcher,clipper,cli}.py`
- Tests: `browser_demo/tests/test_{models,store,converter,clipper,cli,integration}.py`
- Config: `browser_demo/pyproject.toml`

## NixOS Fix
`PlaywrightFetcher` accepts `executable_path` param. `"auto"` uses `_find_system_chromium()` 
which checks PATH for chromium/chromium-browser/google-chrome. `clip_url()` defaults to `"auto"`.

## What Remains
- Commit and push the implementation
