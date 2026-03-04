# Markdown Section Ordering — Plan

**CRITICAL: NO SUBAGENTS (Task tool). Do all work directly.**

## Problem Summary

Three issues prevent correct markdown parsing in Remora's discovery pipeline:

1. **Current query captures headings, not sections** — `section.scm` captures
   `atx_heading` (just the `# Heading` line) instead of `section` (heading +
   paragraphs + nested subsections). Paragraph content is invisible.

2. **`_collect_captures` dict branch doesn't preserve document order** — When
   tree-sitter returns captures as `dict[str, list[Node]]`, flattening iterates
   by capture name, not by position. The final `discover()` sort by `start_line`
   fixes ordering for the returned list, but `_extract_name` runs before that
   sort and relies on traversal order for pairing.

3. **`_extract_name` assumes `.name` capture's parent == `.def` capture node** —
   Works for `atx_heading > inline` but fails for `section > atx_heading > inline`
   (grandchild, not child).

## Design Decision: Two Node Types

**Both sections AND headings are captured as separate CSTNodes.**

- `section` nodes: Full containers (heading + paragraphs + subsections). `node_type = "section"`.
  Text includes the heading line and all paragraph content. Name is the heading text.
- `heading` nodes: Just the `# Heading` line. `node_type = "heading"`.
  Text is only the heading line. Name is the inline text.

Both types are nested — sections contain subsections and their headings.
`discover()` returns them all sorted by `(file_path, start_line)`.

For this markdown:
```markdown
# Intro

Paragraph.

## Details

More text.
```

`discover()` produces (in order):
1. `file` node — the whole file
2. `section` "Intro" (lines 1-7) — full text including paragraph + subsection
3. `heading` "Intro" (line 1) — just `# Intro`
4. `section` "Details" (lines 5-7) — subsection text
5. `heading` "Details" (line 5) — just `## Details`

### `heading` node_type

`heading` is a **new value** for `AgentNode.node_type`. Needs to be added to
any validation that restricts node_type values (if any exist).

## Implementation Steps

### Phase 1: Fix `_collect_captures` ordering (DONE)

1. ✅ Write failing test: dict-branch captures for markdown come out in wrong order
2. ✅ Fix `_collect_captures` to sort the flattened list by `(node.start_point[0], node.start_point[1])`
3. ✅ Verify test passes

### Phase 2: Fix `_extract_name` for nested name captures

4. Write/update failing test: section-level markdown capture gets name "unknown"
5. Fix `_extract_name` to walk up ancestors (not just direct parent) when checking
   `.name` captures against `.def` captures
6. Verify test passes

### Phase 3: Update markdown query to capture sections AND headings

7. Update `queries/markdown/remora_core/section.scm`:
   - Capture `(section)` with `.name` from `atx_heading > inline`
   - Capture `(atx_heading)` with `.name` from `inline`
8. Update/write tests for both section and heading CSTNodes
9. Verify sections have full text (including paragraphs), headings have just the line

### Phase 4: Integration verification

10. Run existing test suite to verify no regressions in Python/TOML parsing
11. End-to-end test with sample.md fixture

## Acceptance Criteria

- `discover()` on a markdown file returns BOTH:
  - `section` CSTNodes where `text` contains heading + paragraphs
  - `heading` CSTNodes where `text` is just the heading line
- Both types are ordered by document position
- Both report correct `name` (heading inline text)
- Existing Python and TOML discovery is unaffected
- All tests pass

**CRITICAL: NO SUBAGENTS (Task tool). Do all work directly.**
