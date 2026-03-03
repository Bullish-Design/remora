# Markdown Section Ordering — Assumptions

## Context

Remora discovers code nodes via tree-sitter and turns them into agents. Markdown
files are already in the language extension map (`.md` -> `"markdown"`), and there
are existing queries in `queries/markdown/remora_core/`. The user wants to ensure
markdown sections and their child paragraphs maintain correct document order when
parsed, stored, and reconstructed.

## Key Invariants

1. **CSTNode identity** is `SHA256(file_path:name:start_line:end_line)[:16]`. Nodes
   without meaningful names (like paragraphs) need a stable identity strategy.

2. **AgentNode is the single model** — no subclasses. Any new fields must go on
   CSTNode, NodeDiscoveredEvent, AgentNode, and the `nodes` table.

3. **`discover()` sorts output by `(file_path, start_line)`** — this is the final
   ordering guarantee. Anything upstream of this sort is potentially unordered.

4. **The dict branch of `_collect_captures`** iterates by capture name, not by
   document position. Within each capture name group, nodes *appear* ordered but
   this is not guaranteed by the tree-sitter API.

5. **Markdown tree-sitter grammar** uses `section` nodes that contain headings +
   all child paragraphs/blocks. Sections nest: a `## H2` section is a child of
   the preceding `# H1` section.

## Constraints

- No isinstance in business logic (repo rule)
- Must be backward-compatible with existing Python/TOML parsing
- Must not break existing `node_id` determinism for code nodes
