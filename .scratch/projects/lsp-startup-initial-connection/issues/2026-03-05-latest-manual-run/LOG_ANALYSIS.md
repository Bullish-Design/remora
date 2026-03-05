# LOG ANALYSIS — 2026-03-05 Latest Manual Run

## Artifact Set
- Client log: `/home/andrew/Documents/Projects/remora/.remora/logs/client-2026-03-05_143359.log`
- Server log: `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_143406.log`
- LSP transport: `/home/andrew/.local/state/nvim/lsp.log`

## Timeline (Absolute)
1. `14:33:59.984` client `M.setup: COMPLETE`
2. `14:33:59.002` client first `kick_lsp_start(vimenter-autostart)` and `NO remora clients found`
3. `14:34:06.876` server `remora-lsp starting (pid=506539)`
4. `14:34:07.036` server `INITIALIZED received`
5. `14:34:07.662` client `ensure_autostart_connected: connected after 13 startup retries`
6. `14:34:22.707` server `cmd_chat: requestInput sent`
7. `14:34:26.312` client `$/remora/submitInput ... buf_notify sent`
8. No matching server `on_input_submitted` entry appears in this run log.

## Marker Counts
- Startup retries / no-client warnings:
  - `get_client: NO remora clients found!` = **15**
- Chat submit pipeline (server-side):
  - `cmd_chat: requestInput sent` = **1**
  - `on_input_submitted: params=` = **0**
  - `execute_turn: START` = **0**
- Panel responsiveness:
  - `panel.do_fetch_agent_data: TIMEOUT` (client) = **4**
- Scan contention signal:
  - `_background_scan: batch_append SLOW` (server) = **1**
  - Slow sample: `duration_ms=8663.8`

## High-Signal Evidence Snippets
- Startup delay evidence:
  - client repeatedly retries before attach (`client log` lines with `NO remora clients found`)
  - server only starts at `14:34:06.876`.
- Submit gap evidence:
  - client logs `HANDLER $/remora/requestInput ... sending $/remora/submitInput ... buf_notify sent`
  - server never logs `on_input_submitted` afterward.
- Panel stall evidence:
  - client logs repeated `panel.do_fetch_agent_data: TIMEOUT`
  - same window contains slow scan append event.

## Notable Detail
Client fallback input captured a control-prefixed message:
- `user input="\fDoes this work?"`
This may indicate key-sequence contamination in fallback input path; keep it as a secondary clue.

## Preliminary Inference
- Autostart hook is running, but startup attach is delayed by several seconds before the server process appears.
- During heavy scan writes, interactive paths (panel + submit delivery) can starve or be dropped.
- This run shows submit dispatch from client but no server receive marker, so transport/handler starvation remains unresolved.
