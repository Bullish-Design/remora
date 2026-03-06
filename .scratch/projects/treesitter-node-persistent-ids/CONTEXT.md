# Context

## Current State
A complete template scaffold now exists at `.scratch/projects/treesitter-node-persistent-ids/template/` for implementing persistent inline Tree-sitter IDs.

A detailed concept overview now exists at:
- `.scratch/projects/treesitter-node-persistent-ids/identity-resolver-sidecar-concept.md`

This document reframes implementation around a centralized `NodeIdentityResolver` + SQLite sidecar anchor store, with inline IDs as optional input (not default save-time mutation).

## What Was Added
- Project tracking docs required by the scratch project convention.
- Python package skeleton with modules for:
  - ID parsing/encoding
  - line mapping
  - extractor interfaces
  - SQLite schema + store wrapper
  - indexing pipeline
  - writeback stub
- Query placeholders for Python and Markdown.
- Starter tests + fixtures.
- Architecture note for implementation sequence.

## Next Logical Steps
1. Decide acceptance of the sidecar resolver concept as the authoritative direction.
2. If accepted, implement resolver library + sidecar schema in runtime code (`src/remora`), not only template.
3. Replace core/LSP identity assignment logic with resolver output and enable delta-based event emission.
4. Disable default save-time ID injection and gate annotation behind explicit CLI commands.
