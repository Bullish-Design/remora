# PLAN: Verify E2E Live Scenarios (Remora Source Repo)

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do all work directly.**

## Objective

Run all 12 E2E scenarios against the real vLLM server, examine .cast output,
write structured test reports per scenario, and iterate on fixes to keys.py
and scenario code until scenarios reliably validate intended behavior.

## Scenario Execution Order

Ordered by dependency — simpler scenarios first, composite ones last.

1. **startup** — LSP startup + agent discovery (foundation for everything)
2. **chat** — Chat with an agent via `<leader>rc`
3. **rewrite** — Trigger `<leader>rr`, verify diagnostic
4. **proposal** — Trigger rewrite, accept with `<leader>ry`
5. **cascade** — Edit code, watch agent-to-agent cascade
6. **reject** — Trigger rewrite, reject with `<leader>rn`
7. **multi_file** — Navigate between files, chat with different agents
8. **panel_nav** — Open panel, navigate between functions, toggle tools
9. **golden_path** — Full demo flow (combines startup+chat+edit+cascade+accept)
10. **ext_discovery** — Custom extensions match different node types
11. **ext_multi_file** — Navigate across files, see extension diversity
12. **ext_edit_cascade** — Edit code in multiple files, watch extensions react

## Per-Scenario Process

For each scenario, follow the verification loop from `e2e-live-verification.md`:

1. Write pre-test expectations
2. Run: `devenv shell -- python -m e2e.run -s <name> --gif`
3. Note PASS/FAIL and duration
4. Read the .cast file — extract key frames and timestamps
5. Write post-test observations
6. Identify changes needed
7. Apply fixes to scenario / keys.py
8. Re-run and verify fix (max 5 iterations per scenario)
9. Write report to `<scenario>-report.md`

## Deliverables

- 12 test reports in this project directory
- Fixes to `e2e/scenarios/*.py` and `e2e/keys.py` as needed
- Updated PROGRESS.md with status per scenario
- CONTEXT.md updated for resumption after compaction

## Files

| File | Path |
|------|------|
| Harness | `e2e/harness.py` |
| Keys API | `e2e/keys.py` |
| Runner | `e2e/run.py` |
| Scenarios | `e2e/scenarios/*.py` |
| Demo project | `remora_demo/project/` |
| Skill reference | `.scratch/skills/e2e-live-verification.md` |

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do all work directly.**
