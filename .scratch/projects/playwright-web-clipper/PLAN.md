# Playwright Web Clipper — Implementation Plan

> **ABSOLUTE RULE — NO SUBAGENTS. Do all work directly.**

## Overview

Standalone Python package in `browser_demo/` that implements the Playwright Web Clipper
from the Neovim Expansion Brainstorm. Headless browser fetches URLs, converts HTML to
clean markdown, stores clips with metadata in SQLite, provides CLI for search/manage.

## Directory Structure

```
browser_demo/
  pyproject.toml
  src/
    browser_demo/
      __init__.py
      models.py        # Pydantic models: ClipMetadata, ClipRecord, FetchResult
      store.py          # ClipStore: SQLite index for clips
      converter.py      # HTML-to-markdown conversion
      fetcher.py        # Playwright headless browser fetch
      clipper.py        # Orchestrator: fetch -> convert -> store pipeline
      cli.py            # Typer CLI: clip, search, list, show, delete, export
  tests/
    __init__.py
    conftest.py
    test_models.py
    test_store.py
    test_converter.py
    test_clipper.py
    test_cli.py
    test_integration.py  # Live Playwright tests (marked integration)
```

## Implementation Order (TDD)

1. Models (Pydantic) — pure data, no deps
2. ClipStore — SQLite CRUD, test first
3. Converter — HTML-to-markdown, test with fixtures
4. Fetcher — Playwright wrapper, mockable
5. Clipper — orchestrator composing fetcher+converter+store, test with mocks
6. CLI — Typer commands wiring everything together
7. Integration tests — live browser fetch

## Dependencies

- playwright (browser automation)
- beautifulsoup4 (HTML parsing/cleaning)
- markdownify (HTML-to-markdown)
- pydantic (models)
- typer (CLI)
- rich (output formatting)
- sqlite3 (stdlib, clip index)

## Acceptance Criteria

- `remora-clip <url>` fetches a page and saves clean markdown with YAML frontmatter
- `remora-clip <url> --select "article"` clips only CSS-selected content
- `remora-clip <url> --tag foo --tag bar` adds tags
- `remora-clip search <query>` fuzzy searches clips by title/tag/content
- `remora-clip list` shows all clips with metadata
- `remora-clip show <id>` displays a clip's content
- `remora-clip delete <id>` removes a clip
- `remora-clip export <id>` outputs raw markdown to stdout
- All clips stored as `.md` files with YAML frontmatter in configurable directory
- SQLite index tracks URL, title, tags, timestamp, file path, content hash
- All unit tests pass, integration tests pass when Playwright browsers installed

> **ABSOLUTE RULE — NO SUBAGENTS. Do all work directly.**
