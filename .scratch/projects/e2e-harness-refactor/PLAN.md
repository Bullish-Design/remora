# E2E Harness Refactor — Implementation Plan

**Goal:** Fix all issues identified in E2E_HARNESS_UPDATES.md to make the test suite reliable.

**CRITICAL: NO SUBAGENTS. Do all work directly.**

---

## Phase 1: Harness Infrastructure (e2e/harness.py)

### 1.1 Add `wait_for_absent()` to TmuxDriver
- Add method after `wait_for_stable()` at line ~237
- Polls until pattern is NOT present
- Used for verifying errors cleared

### 1.2 Add chat state clearing to DemoProjectGuard
- Investigate where Remora stores EventStore data
- Add `.remora/` directory to restoration or add `clear_state()` method

## Phase 2: Keys API (e2e/keys.py)

### 2.1 Add `wait_for_lsp_ready()` method
- Wait for `[Remora]` indicator + settle time
- Replaces fixed `LSP_STARTUP_DELAY` sleep

### 2.2 Add `wait_for_chat_prompt()` method
- Wait for "Message to agent:" prompt after `leader_chat()`
- Prevents typing into wrong buffer

### 2.3 Add `focus_code_buffer()` method
- Reliably navigate to code window regardless of layout
- Tries multiple strategies: C-h, C-w p, window cycling

### 2.4 Add `assert_in_pane()` helper
- Convenience wrapper for capture + assert

### 2.5 Add `open_nvim_with_panel()` convenience method
- Combines open_nvim + wait_for_lsp_ready + leader_panel + focus cycle

## Phase 3: Scenario Fixes (12 scenarios)

### 3.1 startup.py — No changes needed (genuine pass)

### 3.2 chat.py — Fix false positive
- Add `wait_for_chat_prompt()` after `leader_chat()`
- Replace 5s hard sleep with `wait_for_stable()`
- Add meaningful assertion on panel content

### 3.3 rewrite.py — Fix false positive
- Add `wait_for_lsp_ready()` before `leader_rewrite()`
- Add assertion that "LSP not running" is NOT in content
- Use `lsp_delay=0` in open_nvim

### 3.4 proposal.py — Fix false positive
- Same LSP readiness fix as rewrite
- Add assertion that LSP is ready

### 3.5 cascade.py — Strengthen assertions
- Add assertion that edit persisted after save
- Verify panel shows agent info

### 3.6 reject.py — Fix false positive
- Add `wait_for_lsp_ready()` 
- Add assertion that rewrite actually fired
- Verify rejection completed

### 3.7 multi_file.py — Fix partial false positive
- Add `wait_for_lsp_ready()` before first chat
- Add `wait_for_chat_prompt()` before typing
- Ensure source file integrity

### 3.8 panel_nav.py — No major changes (genuine pass)
- Optionally strengthen assertions

### 3.9 golden_path.py — Major rework
- Add `wait_for_chat_prompt()` after `leader_chat()`
- Use `focus_code_buffer()` instead of `focus_window("h")`
- Add assertions throughout
- Fix the focus management bug

### 3.10 ext_discovery.py — Strengthen assertions
- Navigate to specific nodes and verify agent types
- Wait for agent discovery with specific patterns

### 3.11 ext_multi_file.py — Add assertions
- Wait for agent discovery on each file
- Add assertions for agent presence

### 3.12 ext_edit_cascade.py — Add assertions
- Assert edits persisted
- Assert panel shows agent info

---

## Acceptance Criteria

1. All 12 scenarios have at least one meaningful `assert` statement
2. No scenario uses unused `_content` variables
3. All rewrite/proposal/reject scenarios use `wait_for_lsp_ready()`
4. All chat scenarios use `wait_for_chat_prompt()` before typing
5. Tests can be run with `pytest e2e/` (dry run check)

---

**REMINDER: NO SUBAGENTS. Do all work directly.**
