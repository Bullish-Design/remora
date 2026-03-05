# Hypothesis Report

## Run Metadata
- Date: 2026-03-05
- Run directory: `.scratch/projects/lsp-chat-delivery-recovery/runs/2026-03-05-step-04-post-instrumentation-check/`
- Input logs:
  - `.remora/logs/client-2026-03-05_122744.log`
  - `.remora/logs/server-2026-03-05_122755.log`
  - `~/.local/state/nvim/lsp.log`
- Simplified outputs:
  - `simplified-logs/client-2026-03-05_122744.simplified.log`
  - `simplified-logs/server-2026-03-05_122755.simplified.log`
  - `simplified-logs/simplify_summary.json`

## Observed Symptoms
- LSP connected, but only after a long retry window in the client.
- This run was panel navigation only (no chat submit), so chat pipeline (`on_input_submitted -> execute_turn -> calling LLM`) was not exercised.
- New step-03 instrumentation is active and emitting timing logs for panel EventStore reads.

## Stage Counters
Client (`client-2026-03-05_122744`):
- `connected after`: 1
- `NO remora clients found`: 33
- `kick_lsp_start(...)`: 5
- `panel.do_fetch_agent_data: requesting`: 2

Server (`server-2026-03-05_122755`):
- `cmd_get_agent_panel: get_node_at_position START/END`: 2 / 2
- `cmd_get_agent_panel: get_recent_events START/END`: 2 / 2
- `_resolve_agent ... START/END/TIMEOUT`: 0 / 0 / 0
- `on_input_submitted: params=`: 0
- `execute_turn: START`: 0
- `calling LLM`: 0
- `append: database locked`: 0
- `batch_append: database locked`: 0

Measured panel read timings:
- `get_node_at_position END duration_ms`: 1.5ms, 0.9ms
- `get_recent_events END duration_ms`: 14.1ms, 13.2ms

Transport context:
- `~/.local/state/nvim/lsp.log` at `2026-03-05 12:27:58` still shows:
  - `Another remora-lsp instance is already active for this workspace (pid=326259)`

## Assessment
- The new instrumentation is working and proves low-latency EventStore reads for `cmd_get_agent_panel` in this run.
- This run does **not** validate/falsify the chat-stall hypothesis yet, because `_resolve_agent` and chat submission paths were not exercised.
- Startup/client attach instability remains visible (33 no-client checks before connect + duplicate-instance transport warning).

## Updated Hypothesis
Primary unresolved issue is now likely split:
1. **Startup/attach instability** (slow client attach + duplicate start attempts) is still present.
2. **Chat stall root cause** remains unknown because this run did not hit chat submit path; panel read path appears healthy.

## Recommendation
Run a targeted chat-submit experiment with current instrumentation enabled, then evaluate:
- If `_resolve_agent` shows timeout/long duration during stall, continue EventStore read-path investigation.
- If `_resolve_agent` remains fast but `calling LLM` is still absent, shift focus to runner `execute_turn` internals (workspace init / event fetch path).
