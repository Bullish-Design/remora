# PROGRESS: Verify E2E Live Scenarios

## Status: EXTENDED (Updated 2026-03-03)

Now 17 scenarios (12 core + 5 agent communication).

## Phase 2: Agent Communication Scenarios (2026-03-03)

### New Scenarios Added

| # | Scenario | Tool Tested | Description |
|---|----------|-------------|-------------|
| 13 | agent_message | send_message | Direct agent-to-agent messaging |
| 14 | agent_broadcast | broadcast | Broadcast to siblings/children |
| 15 | agent_subscribe | subscribe | Dynamic event subscriptions |
| 16 | swarm_monitor | (extension) | Meta-observation of agent activity |
| 17 | query_agents | query_agents | Agent discovery and listing |

### Enhanced Assertions

Updated scenarios 13-15 to verify tool execution results appear in chat panel:
- `agent_message`: Checks for "message/queued/send"
- `agent_broadcast`: Checks for "broadcast/siblings/sent"
- `agent_subscribe`: Checks for "subscri/register"

### Files Created/Modified
- `e2e/scenarios/agent_message.py` — Enhanced with tool result assertion
- `e2e/scenarios/agent_broadcast.py` — Enhanced with tool result assertion
- `e2e/scenarios/agent_subscribe.py` — Enhanced with tool result assertion
- `e2e/scenarios/swarm_monitor.py` — Meta-observation scenario
- `e2e/scenarios/query_agents.py` — NEW: agent discovery scenario
- `e2e/scenarios/__init__.py` — Registered all 5 new scenarios

---

## Phase 1: Core Scenarios (2026-03-03)

All 12 original scenarios pass reliably (verified with 3 consecutive runs).

### Results

| # | Scenario | Duration | Status |
|---|----------|----------|--------|
| 1 | startup | 6.8s | PASS |
| 2 | chat | 22.5s | PASS |
| 3 | rewrite | 14.5s | PASS |
| 4 | proposal | 20.5s | PASS |
| 5 | cascade | 18.5s | PASS |
| 6 | golden_path | 48.7s | PASS |
| 7 | reject | 20.5s | PASS |
| 8 | multi_file | 27.2s | PASS |
| 9 | panel_nav | 23.0s | PASS |
| 10 | ext_discovery | 30.0s | PASS |
| 11 | ext_multi_file | 38.8s | PASS |
| 12 | ext_edit_cascade | 38.9s | PASS |

### Issues Fixed

1. **`wait_for_chat_prompt()` pattern mismatch** (keys.py)
   - Changed default from `"Message to agent:"` to `"Message agent"` 
   - Handles both truncated and full prompt text

2. **Chat requires panel initialization** (chat.py, multi_file.py)
   - Added `leader_panel()` + focus cycle before chat operations

3. **Focus management before file switch** (multi_file.py)
   - Added `focus_code_buffer()` before `:e` commands
