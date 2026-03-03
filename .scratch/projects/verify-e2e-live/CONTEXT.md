# CONTEXT: Verify E2E Live Scenarios

## Current State

**PROJECT COMPLETE.** All 12 scenarios verified against live vLLM server. All reports written. PROGRESS.md updated.

## What Happened

Ran all 12 E2E scenarios against a real vLLM server (`http://remora-server:8000/v1` with model `Qwen/Qwen3-4B-Instruct-2507-FP8`). Each scenario's `.cast` file was analyzed frame-by-frame using ANSI-stripped text extraction. Structured reports written for each scenario.

### Key Findings

- Only 3 of 12 scenarios are genuine passes (startup, panel_nav, and arguably ext_edit_cascade)
- 4 scenarios are outright false positives (chat, rewrite, proposal, reject)
- 3 scenarios have zero assertions and literally cannot fail
- The "LSP not running" error on `<leader>rr` is the single biggest blocker (affects 3 scenarios)
- Focus management after opening chat panel is broken (affects golden_path, multi_file)
- No scenario verifies that the LLM actually responded to a prompt
- Chat state leaks between runs (no isolation)
- Backend `to_llm_tool` serialization bug discovered

## Next Project

Results feed into the `e2e-harness-review` project, which will consolidate all findings into an actionable `E2E_HARNESS_UPDATES.md` document.

## Key Paths

- Reports: `.scratch/projects/verify-e2e-live/*-report.md` (12 files)
- Harness: `e2e/harness.py`
- Keys: `e2e/keys.py`
- Scenarios: `e2e/scenarios/`
