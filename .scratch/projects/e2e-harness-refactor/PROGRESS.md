# E2E Harness Refactor — Progress

## Phase 1: Harness Infrastructure
- [x] 1.1 Add `wait_for_absent()` to TmuxDriver
- [x] 1.2 Add state clearing to DemoProjectGuard

## Phase 2: Keys API
- [x] 2.1 Add `wait_for_lsp_ready()` 
- [x] 2.2 Add `wait_for_chat_prompt()`
- [x] 2.3 Add `focus_code_buffer()`
- [x] 2.4 Add `assert_in_pane()`
- [x] 2.5 Add `open_nvim_with_panel()`
- [x] 2.6 Add `assert_not_in_pane()` (bonus)

## Phase 3: Scenario Fixes
- [x] 3.1 startup.py — updated to use wait_for_lsp_ready
- [x] 3.2 chat.py — added wait_for_chat_prompt, fixed assertions
- [x] 3.3 rewrite.py — added wait_for_lsp_ready, assertions
- [x] 3.4 proposal.py — added wait_for_lsp_ready, assertions
- [x] 3.5 cascade.py — added assertions for edit and panel
- [x] 3.6 reject.py — added wait_for_lsp_ready, assertions
- [x] 3.7 multi_file.py — added wait_for_lsp_ready, wait_for_chat_prompt
- [x] 3.8 panel_nav.py — added wait_for_lsp_ready, final assertion
- [x] 3.9 golden_path.py — major rework with focus_code_buffer
- [x] 3.10 ext_discovery.py — added node-specific assertions
- [x] 3.11 ext_multi_file.py — added assertions for all agents
- [x] 3.12 ext_edit_cascade.py — added assertions for edits

## Phase 4: Testing
- [x] 4.1 Create e2e/tests/ directory
- [x] 4.2 Add test_harness.py with TmuxDriver and DemoProjectGuard tests (9 tests)
- [x] 4.3 Add test_keys.py with NvimKeys tests (14 tests)
- [x] 4.4 All 23 tests pass

## Final Verification
- [x] All 12 scenarios have meaningful assertions
- [x] No scenario uses unused `_content` variables
- [x] All rewrite/proposal/reject scenarios use `wait_for_lsp_ready()`
- [x] All chat scenarios use `wait_for_chat_prompt()` before typing
- [x] Syntax check passes on all files
- [x] Import check passes
- [x] Unit tests pass (23/23)

## COMPLETE ✓
