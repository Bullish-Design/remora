# Context — Notes and Todos

## Status: COMPLETE

All work done. 20 new tests passing, 0 regressions.

## What Was Done

### New files created:
- `src/remora/queries/markdown/remora_core/frontmatter.scm` — captures `minus_metadata` (YAML frontmatter)
- `src/remora/queries/markdown/remora_core/todo.scm` — captures checkbox list items (`- [ ]` / `- [x]`)
- `tests/test_notes_todos.py` — 20 tests covering notes, todos, todo-notes, and integration

### Modified files:
- `src/remora/core/discovery.py`:
  - Added `import yaml`
  - Added `_POSTPROCESS_CAPTURES` set to skip frontmatter from generic pipeline
  - Modified `_parse_file` to skip postprocess captures and call `_postprocess_markdown`
  - Added `_postprocess_markdown()` function that parses frontmatter YAML, creates note/todo-note CSTNode
- `src/remora/core/agent_node.py`:
  - Added `"note"` (SymbolKind.File) and `"todo"` (SymbolKind.Event) to `kind_map`

### Design:
- Frontmatter is captured by tree-sitter (`minus_metadata`) but processed in Python post-processing
- YAML parsed with `yaml.safe_load()`, extracts `title` (name) and `type` (node_type)
- Todo checkboxes flow through the standard capture pipeline via `todo.scm`
- Note/todo-note spans the entire file (start_line=1, end_line=last, text=full content)
