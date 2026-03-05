# Next Step Plan — Step 04 (Post-Instrumentation Validation)

## Goal
Exercise the chat submit path under current instrumentation and convert any remaining stall into explicit stage timing evidence.

## Change Set (single hypothesis)
1. Add timing logs around runner `execute_turn` pre-LLM stages:
   - node fetch
   - correlation event fetch
   - workspace/service initialization
2. Add bounded timeout + explicit error log around the most likely pre-LLM blocking call in `execute_turn`.
3. Keep behavior unchanged except for timeout guard + diagnostics.

## Expected Logs After Change
- For each `execute_turn`:
  - stage start/end with durations
  - explicit timeout marker if blocked
- If hypothesis is correct:
  - we see a high-latency/timeout stage before `calling LLM` when chat stalls.
- If hypothesis is wrong:
  - all pre-LLM stages stay fast; stall occurs later or outside runner.

## Success Criteria for This Experiment
- A chat-stall reproduction yields a concrete blocked stage (or clean falsification), replacing the current silent pre-LLM gap.
