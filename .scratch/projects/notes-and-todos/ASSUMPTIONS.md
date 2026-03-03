# Assumptions — Notes and Todos

## Project Audience
- Remora users working with Obsidian-style markdown vaults
- Notes have YAML frontmatter delimited by `---`
- Todos are `- [ ]` / `- [x]` checkbox items in markdown

## Constraints
- **No CSTNode schema changes** — metadata lives in `text`, title in `name`. YAGNI.
- **No subclasses** — repo rule. AgentNode is the only model, specialization is data-driven.
- **PyYAML available** — `yaml` v6.0.3 installed in the environment.
- **Tree-sitter markdown parser** — `tree_sitter_markdown` is available and working.
- **TDD** — failing tests first, then implement.

## Design Decisions
1. Frontmatter parsing is a **post-processing step** in `_parse_file` for markdown files.
2. `minus_metadata` tree-sitter node captures the YAML frontmatter block.
3. The `name` field for a note comes from frontmatter `title` key, fallback to filename.
4. A note with `type: todo` in frontmatter becomes `node_type = "todo"` instead of `"note"`.
5. Checkbox items (`- [ ]` / `- [x]`) become individual `todo` CSTNodes regardless of file type.
6. No new `.scm` file for notes — frontmatter is handled in Python post-processing. Todo checkboxes get a query added to the existing `section.scm` (or a new `todo.scm`).

## Invariants
- Existing markdown section/heading/code_block discovery must not regress.
- `discover()` output is always sorted by `(file_path, start_line)`.
- `node_id` = `SHA256(file_path:name:start_line:end_line)[:16]`.
- File-level node is always included (unless filtered by node_types).
