# Test Report: Full E2E Run — 2026-03-03

## Run Info
- **Date**: 2026-03-03 22:30
- **Result**: PASS (12/12 scenarios)
- **Total Duration**: ~5 minutes (all 12 scenarios)
- **Verified**: 3 consecutive runs all pass

## Summary

After the e2e-harness-refactor project, ran all 12 scenarios and found 3 failures. Fixed all issues and verified with 3 consecutive successful runs.

## Failures Found & Fixed

### 1. golden_path — `wait_for_chat_prompt()` pattern mismatch

**Symptom**: `Timed out after 10.0s waiting for pattern: 'Message to agent:'`

**Root Cause**: The chat prompt text varies based on panel width:
- Narrow panel: `Message agent...` (truncated)
- Wide layout: `Message to agent:`

**Fix**: Updated `keys.py:wait_for_chat_prompt()` to use `"Message agent"` as the default pattern (matches both variants).

**File**: `e2e/keys.py:283-295`

### 2. chat — Chat requires panel to be open first

**Symptom**: `Timed out after 10.0s waiting for pattern: 'Message agent'`

**Root Cause**: The `<Space>rc` chat keybinding requires the Remora panel to be initialized first. The scenario was calling `leader_chat()` without opening the panel.

**Fix**: Added `leader_panel()` + focus cycle before attempting to chat.

**File**: `e2e/scenarios/chat.py:36-39`

### 3. multi_file — Same as chat, plus focus issue

**Symptom**: Two issues:
1. Chat prompt timeout (same as chat scenario)
2. After first chat, `:e merge.py` opened in wrong window

**Root Cause**: 
1. Missing panel initialization
2. After chat, focus was in panel; `:e` command ran in panel window

**Fix**: 
1. Added `leader_panel()` + focus cycle at start
2. Added `focus_code_buffer()` before switching files

**File**: `e2e/scenarios/multi_file.py:36-39, 58`

## Changes Made

### keys.py

```python
# Changed default prompt pattern from:
prompt_text: str = "Message to agent:"
# To:
prompt_text: str = "Message agent"
```

### chat.py

Added panel initialization before chat:
```python
# Open the agent panel first (required for chat to work)
nv.leader_panel()
nv.focus_right(delay=0.3)
nv.focus_left(delay=0.3)
```

### multi_file.py

1. Added panel initialization (same as chat.py)
2. Added focus management before file switch:
```python
# Focus back to code buffer before switching files
nv.focus_code_buffer(expected_text="def load_config")
```

## Final Results

All 12 scenarios pass reliably (3 consecutive runs):

| Scenario | Duration | Status |
|----------|----------|--------|
| startup | 6.8s | PASS |
| chat | 22.5s | PASS |
| rewrite | 14.5s | PASS |
| proposal | 20.5s | PASS |
| cascade | 18.5s | PASS |
| golden_path | 48.7s | PASS |
| reject | 20.5s | PASS |
| multi_file | 27.2s | PASS |
| panel_nav | 23.0s | PASS |
| ext_discovery | 30.0s | PASS |
| ext_multi_file | 38.8s | PASS |
| ext_edit_cascade | 38.9s | PASS |

## Lessons Learned

1. **Chat requires panel**: The Remora chat functionality (`<Space>rc`) depends on the panel being initialized. Scenarios that use chat must call `leader_panel()` first.

2. **Prompt text varies by width**: UI text can be truncated based on available space. Use the shortest unique prefix for pattern matching.

3. **Focus management matters**: When multiple windows are open (code + panel), explicit focus management is critical before file operations.
