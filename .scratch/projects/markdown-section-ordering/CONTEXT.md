# Markdown Section Ordering — Context

## Status: COMPLETE

## What Was Done

Fixed Remora's markdown tree-sitter discovery pipeline with three changes:

### 1. `_collect_captures` dict-branch ordering (Phase 1)
**File**: `src/remora/core/discovery.py:200-208`

The dict branch now sorts flattened captures by `(start_point[0], start_point[1])`
after flattening, restoring document order.

### 2. `_extract_name` ancestor walk (Phase 2)
**File**: `src/remora/core/discovery.py:213-222` (new `_is_ancestor` helper at 213-220)

`_extract_name` now walks the ancestor chain instead of checking only the direct
parent. This correctly pairs `section.name` (inline) captures with `section.def`
(section) nodes even when the relationship is grandchild (section > atx_heading > inline).

### 3. Two-node-type query: sections AND headings (Phase 3)
**File**: `src/remora/queries/markdown/remora_core/section.scm`

Updated the query to capture:
- `(section)` → `section.def` with name from `(atx_heading > inline)` → `section.name`
- `(atx_heading)` → `heading.def` with name from `(inline)` → `heading.name`
- `(fenced_code_block)` → `code_block.def` (unchanged)

`discover()` now returns BOTH:
- `section` CSTNodes — full text including heading + paragraphs + subsections
- `heading` CSTNodes — just the heading line

## Test Results

14/14 tests pass in `tests/test_markdown_sections.py`.
Full test suite has no regressions (2 pre-existing failures unrelated to this work).

## Changed Files

| File | Change |
|------|--------|
| `src/remora/core/discovery.py` | Fixed `_collect_captures` sort + new `_is_ancestor` + updated `_extract_name` |
| `src/remora/queries/markdown/remora_core/section.scm` | Captures sections + headings + code blocks |
| `tests/test_markdown_sections.py` | 14 tests covering all three fixes |
