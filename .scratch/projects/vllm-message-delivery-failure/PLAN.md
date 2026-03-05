# PLAN — vLLM Message Delivery Failure

## ABSOLUTE RULE
NO SUBAGENTS. All investigation and implementation is done directly in this session.

## Objective
Find and fix why user chat messages are not being delivered to the configured vLLM server.

## Steps
1. Reproduce and timestamp the failure.
2. Trace the full message path:
   - Neovim client submit
   - LSP `on_input_submitted`
   - `AgentRunner.execute_turn`
   - `execute_agent_turn`
   - LLM client request to `base_url`
3. Add targeted diagnostics at the model-call boundary if missing:
   - request start/end
   - timeout/error class
   - HTTP status / transport failure
4. Implement the smallest safe fix for the confirmed failure mode.
5. Validate with manual chat roundtrip and logs proving request reached vLLM.

## Acceptance Criteria
- At least one test/manual run shows a message crossing the model boundary successfully.
- Logs show no ambiguous gap between `execute_agent_turn` and model request dispatch.
- User-visible chat response is returned (or explicit actionable model error is surfaced).

## ABSOLUTE RULE (REPEATED)
NO SUBAGENTS.
