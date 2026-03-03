# Assumptions — Playwright Web Clipper

## Project Scope
- Standalone package in `browser_demo/`, not integrated into main remora src
- Self-contained with its own pyproject.toml and test suite
- No coupling to remora core — this is a standalone tool

## Technical Constraints
- Python 3.13+ (matching remora's requirement)
- Uses uv for package management (matching repo convention)
- Playwright for JS-rendered content (not just HTTP fetch)
- SQLite for clip index (lightweight, no server)
- Clips stored as markdown files on disk (not just in DB)

## User Scenarios
- Developer clips a docs page while working in terminal
- Developer searches previously clipped content
- Developer exports clip content for pasting into agent context
- Tags used for organizing clips by topic/project

## Design Decisions
- Clip files use YAML frontmatter for metadata portability
- SQLite index is the query layer; files are the source of truth
- CSS selector support for targeted scraping
- Async Playwright for non-blocking fetches
- Configurable clip storage directory (default: `.clips/` relative to CWD)
