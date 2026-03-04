# Plan — Notes and Todos

**CRITICAL: NO SUBAGENTS (Task tool). Do all work directly.**

## Phase 1: Note Nodes (frontmatter)

### 1a. Write failing tests
- `.md` with YAML frontmatter produces a `note` CSTNode
- `name` = frontmatter `title` value
- `text` = entire file content (frontmatter included)
- `start_line` = 1, `end_line` = last line of file (file-spanning node)
- `.md` WITHOUT frontmatter does NOT produce a `note` node
- Frontmatter with no `title` key falls back to filename

### 1b. Implement
- Add `frontmatter.scm` query: `(minus_metadata) @frontmatter.def`
- In `_parse_file`, after collecting captures, detect `frontmatter` captures for markdown
- Parse YAML content with `yaml.safe_load()`
- Create a `note` CSTNode spanning the whole file, with `name` from frontmatter title
- The file-level node should still be created (note is additional, or replaces file node — TBD based on test design)

### 1c. Verify tests pass

## Phase 2: Todo Checkbox Items

### 2a. Write failing tests
- `- [ ] First task` produces a `todo` CSTNode with `name="First task"`
- `- [x] Done task` also produces a `todo` CSTNode with `name="Done task"`
- `text` contains the full list item text (e.g. `- [ ] First task`)
- Both checked and unchecked items are captured

### 2b. Implement
- Add todo query to `.scm` file:
  ```
  (list_item
    [(task_list_marker_unchecked) (task_list_marker_checked)]
    (paragraph (inline) @todo.name)) @todo.def
  ```
- This uses standard tree-sitter capture → CSTNode pipeline (no special post-processing)

### 2c. Verify tests pass

## Phase 3: Todo Note (frontmatter type)

### 3a. Write failing tests
- Note with `type: todo` in frontmatter gets `node_type = "todo"` instead of `"note"`
- Note with `type: note` (or no type) stays as `"note"`

### 3b. Implement
- In the frontmatter post-processing, check for `type` key
- If `type == "todo"`, set `node_type = "todo"` on the file-spanning node

### 3c. Verify tests pass

## Phase 4: Polish

- Add `"note"` and `"todo"` entries to `AgentNode.to_document_symbol()` kind_map
- Full regression test run (all existing tests must still pass)
- Update PROGRESS.md and CONTEXT.md

**CRITICAL: NO SUBAGENTS (Task tool). Do all work directly.**
