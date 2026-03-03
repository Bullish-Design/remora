# CONTEXT: Verify E2E Live Scenarios

## Current State

**PROJECT EXTENDED (Updated 2026-03-03).** Now 17 scenarios covering agent-agent communication.

## Latest Session (2026-03-03) — Extended

Added 5 new agent communication scenarios and enhanced assertions:

### New Scenarios Created
1. **`agent_message`** — Direct agent-to-agent messaging via `send_message` tool
2. **`agent_broadcast`** — Broadcast to siblings/children via `broadcast` tool
3. **`agent_subscribe`** — Dynamic event subscription via `subscribe` tool
4. **`swarm_monitor`** — Meta-observation via SwarmMonitor extension
5. **`query_agents`** — Agent discovery via `query_agents` tool

### Enhanced Assertions
Updated agent scenarios to verify tool execution success:
- `agent_message`: Asserts "message/queued/send" appears in response
- `agent_broadcast`: Asserts "broadcast/siblings/sent" appears in response
- `agent_subscribe`: Asserts "subscri/register" appears in response

### Files Modified
- `e2e/scenarios/agent_message.py` — Added tool result assertion
- `e2e/scenarios/agent_broadcast.py` — Added tool result assertion
- `e2e/scenarios/agent_subscribe.py` — Added tool result assertion
- `e2e/scenarios/query_agents.py` — NEW: agent discovery scenario
- `e2e/scenarios/__init__.py` — Registered 5th scenario

## Previous Session (2026-03-03)

Ran full E2E evaluation loop after the e2e-harness-refactor project. Found 3 issues and fixed them:

1. **`wait_for_chat_prompt()` pattern**: Changed from `"Message to agent:"` to `"Message agent"` to handle both truncated and full prompt text variants.

2. **Chat requires panel**: The `<Space>rc` keybinding requires the panel to be initialized first. Added `leader_panel()` + focus cycle to `chat.py` and `multi_file.py`.

3. **Focus before file switch**: Added `focus_code_buffer()` call in `multi_file.py` before switching to the second file.

## Key Paths

- Harness: `e2e/harness.py`
- Keys: `e2e/keys.py`
- Scenarios: `e2e/scenarios/`
- Swarm tools: `src/remora/core/tools/swarm.py`

## Scenario Inventory (17 total)

### Core Scenarios (12)
startup, chat, rewrite, proposal, cascade, golden_path, reject, multi_file, panel_nav, ext_discovery, ext_multi_file, ext_edit_cascade

### Agent Communication Scenarios (5)
agent_message, agent_broadcast, agent_subscribe, swarm_monitor, query_agents

## Run Commands

```bash
# Run all scenarios
devenv shell -- python -m e2e.run --no-record

# Run single scenario
devenv shell -- python -m e2e.run -s query_agents --no-record
```
