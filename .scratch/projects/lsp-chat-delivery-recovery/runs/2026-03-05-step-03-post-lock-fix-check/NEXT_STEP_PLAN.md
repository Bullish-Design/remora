# Next Step Plan — Step 03 (Post-Lock-Fix Check)

## Goal
Determine whether post-connect chat stalls are caused by blocking EventStore reads in command/agent-resolution paths.

## Change Set (single hypothesis)
1. Add per-call timing logs around EventStore reads in `cmd_get_agent_panel` and `cmd_chat` agent resolution.
2. Add bounded timeout for `_resolve_agent` query path with explicit timeout log and user-visible failure response.
3. Keep runner/workspace execution logic unchanged in this step.

## Expected Logs After Change
- For every command lookup:
  - start log
  - end log with duration in ms
  - or timeout log with duration
- If hypothesis is correct:
  - timeouts/long durations cluster during stalls.
- If hypothesis is wrong:
  - read durations stay low even when no `calling LLM` appears.

## Success Criteria for This Experiment
- Convert current silent hangs into explicit, timestamped read-latency or timeout signals.
