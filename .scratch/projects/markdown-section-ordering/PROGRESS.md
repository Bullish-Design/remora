# Markdown Section Ordering — Progress

- [x] Phase 1: Fix `_collect_captures` ordering
  - [x] Write failing test for dict-branch ordering
  - [x] Fix `_collect_captures` to sort by position
  - [x] Verify test passes
- [x] Phase 2: Fix `_extract_name` for nested captures
  - [x] Write failing test for section name extraction
  - [x] Add `_is_ancestor` helper, update `_extract_name` ancestor walk
  - [x] Verify test passes
- [x] Phase 3: Update markdown query to capture sections AND headings
  - [x] Update `section.scm` to capture `(section)` and `(atx_heading)` as two node types
  - [x] Write tests for both section and heading CSTNodes (14 total)
  - [x] Verify section text includes paragraphs, heading text is just the line
- [x] Phase 4: Integration verification
  - [x] Run existing test suite — no regressions
  - [x] All 14 markdown tests pass
