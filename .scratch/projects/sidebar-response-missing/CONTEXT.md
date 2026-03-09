# Context

Follow-up deep investigation completed for the sidebar-missing-response issue.

What was completed in this pass:
- Re-validated runtime evidence against the fresh environment at:
  - `/home/andrew/Documents/Projects/remora-example-workspace/.remora/logs/`
  - `/home/andrew/Documents/Projects/remora-example-workspace/.remora/events/events.db`
- Reconfirmed causal chain:
  - panel closed during input routing
  - `AgentTextResponse` emitted successfully
  - panel history fetch returned only one event
  - DB evidence shows mismatch (`from_agent/to_agent` = 1 vs `payload.agent_id` = 9)
- Performed broader architecture impact scan across:
  - EventStore query/schema/serialization
  - LSP command + notify path
  - panel rendering/merge logic
  - `turn_context` and bootstrap `event_read` consumers
  - tests encoding current semantics
- Rewrote project plan and investigation report with a fundamental architecture recommendation:
  - split history APIs by intent
  - canonical envelope parity across live + replay
  - participant indexing/projection for timeline retrieval

Current status:
- INVESTIGATION_REVIEW.md written by second reviewer (independent pass).
- Analysis/documentation complete for architecture direction.
- No production code changes made in this pass.

Next likely step:
- Implement per IMPLEMENTATION_GUIDE.md (15 steps across 14 files).
- Follow execution order at the bottom of the guide.
- Run tests after each step as specified.

Key decisions locked in:
- `event_participants` table NOT needed — add `agent_id` column only
- `AgentTextResponseEvent` uses `payload: dict` sub-dict (not top-level `content`) to avoid Lua changes
- `event_type: str = "AgentTextResponse"` literal default preserves panel.lua icon/highlight keys
- `emit_agent_text_response` calls `emit_event` directly (no `_call_server_method` indirection)
- Both chat history paths (agent_runner correlation + turn_context timeline) include AgentTextResponse as assistant
