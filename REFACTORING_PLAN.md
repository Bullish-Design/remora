# Remora Refactoring Plan

## Overview
This document outlines the refactoring plan for the Remora codebase, based on the `CODE_REVIEW.md` document. Each recommendation has been carefully evaluated against the actual codebase for accuracy. For each item, I have provided an assessment of the reviewer's claims, my own suggestions for improvement, and an overview of the required refactoring work.

---

## 1. Architecture - Layer Separation

### Reviewer's Recommendation
Extract responsibilities from `analyzer.py` (which is becoming a "god object"), specifically separating workspace management and result presentation.

### My Assessment & Opinion
**Accurate**. `analyzer.py` is over 500 lines long and handles discovery coordination, `Cairn` workspace merging/discarding (`_cairn_merge`, `_cairn_discard`), and contains the `ResultPresenter` class. This violates the Single Responsibility Principle.

### Suggestion for Improvement
Extract `ResultPresenter` into a entirely new file (`presenter.py`). Similarly, extract the workspace management logic (the `_cairn_merge`, `_cairn_discard`, error-handling related to them) into a `workspace_bridge.py` or similar helper class, keeping `RemoraAnalyzer` strictly focused on analysis orchestration.

### Refactoring Work Overview
1. Create `src/remora/presenter.py` and move `ResultPresenter`.
2. Create `src/remora/workspace_bridge.py` and move the Cairn merge/discard/retry tracking logic.
3. Update `analyzer.py` to instantiate and use these new classes, reducing its size significantly.

---

## 2. Architecture - Orchestrator Context

### Reviewer's Recommendation
The `_build_initial_context` method in `orchestrator.py` at line ~180 constructs messages directly rather than using a template system.

### My Assessment & Opinion
**Inaccurate**. There is no `_build_initial_context` method in `orchestrator.py`. Context and message building actually happens in `kernel_runner.py` via `self.bundle.build_initial_messages()`, which is a robust part of the `structured-agents` library. 

### Suggestion for Improvement
The current templating approach using `structured-agents` bundles is already effective. No immediate refactoring is needed here, and the intern's claim should be disregarded.

### Refactoring Work Overview
None required.

---

## 3. Architecture - KernelRunner Error Handling

### Reviewer's Recommendation
Provide more granular error handling in `kernel_runner.py` instead of wrapping everything broadly in `ExecutionError` or returning generic `AgentResult(status=FAILED)`.

### My Assessment & Opinion
**Accurate**. `kernel_runner.py` catches `Exception` globally in the `run()` method and wraps it generically. This makes it difficult for the orchestrator to distinguish between a transient model timeout and a fatal configuration error.

### Suggestion for Improvement
Introduce specific exception types (e.g., `KernelTimeoutError`, `ToolExecutionError`, `ContextLengthError`) and catch them explicitly before falling back to a general `Exception`.

### Refactoring Work Overview
1. Define granular exception classes in `errors.py`.
2. Update `KernelRunner.run()` to catch these specific exceptions and populate the `AgentResult` with more descriptive error codes and details.

---

## 4. Code Quality - ".pym" Grail Scripts

### Reviewer's Recommendation
Grail `.pym` scripts (like `run_linter.pym`) use brittle string parsing because the standard library `json` is unavailable in the sandbox. This causes tests to fail and makes errors hard to debug.

### My Assessment & Opinion
**Highly Accurate**. Upon inspecting `agents/lint/tools/run_linter.pym`, I found a hand-rolled JSON parser (`_split_json_objects`, `_parse_string`, etc). This is extremely brittle, unmaintainable, and the root cause of the script test failures.

### Suggestion for Improvement
Instead of forcing the sandboxed scripts to parse strings manually, we should leverage Remora's ability to inject external functions. We can add a new external function (e.g., `run_json_command`) to `src/remora/externals.py`. This function will run outside the sandbox, use the standard Python `json` module to parse the process output natively, and return the structured Python dictionary directly to the `.pym` script.

### Refactoring Work Overview
1. Update `src/remora/externals.py` with `run_json_command(cmd, args) -> dict | list`.
2. Completely remove the hand-rolled parsing logic from `run_linter.pym` and any other `.pym` tools.
3. Replace the calls to `run_command` with `run_json_command` where structured output from a CLI tool is expected.

---

## 5. Security - External Dependencies

### Reviewer's Recommendation
Pin the Git-sourced core libraries (grail, cairn, fsdantic, structured-agents) to specific commits to remove a single point of failure.

### My Assessment & Opinion
**Accurate & Necessary**. Relying on floating branch references for security sandboxing layers is a significant risk. 

### Suggestion for Improvement
Pin all Git dependencies to specific commit SHAs. In addition, setup an automated dependency update workflow to periodically bump these SHAs after tests pass.

### Refactoring Work Overview
1. Audit `pyproject.toml` (or dependency management files).
2. Update floating Git branch references to exact commit hashes.

---

## 6. Code Quality - Subagent Deprecation

### Reviewer's Recommendation
Delete `subagent.py` as it is empty/dead code.

### My Assessment & Opinion
**Accurate**. `subagent.py` is an obsolete artifact of a previous architecture iteration and serves no purpose.

### Suggestion for Improvement
Remove the file outright to eliminate confusion.

### Refactoring Work Overview
1. Delete `src/remora/subagent.py`.
2. Ensure no rogue imports or documentation references to `remora.subagent` remain scattered in the codebase.

---

## 7. Performance - Sequential Tree-sitter Discovery

### Reviewer's Recommendation
Optimize the recursive directory walk and sequential tree-sitter parsing in `discovery/discoverer.py`.

### My Assessment & Opinion
**Accurate**. Currently, `TreeSitterDiscoverer.discover()` iterates through all `.py` files in a blocking loop (`for file_path in py_files: tree = self._parser.parse_file(file_path)`). For very large codebases, this will be incredibly slow.

### Suggestion for Improvement
Use `concurrent.futures.ThreadPoolExecutor` to parallelize file parsing. Tree-sitter is effectively synchronous but mapping the parsing across threads will mitigate disk I/O wait times and utilize multi-core parsing.

### Refactoring Work Overview
1. Refactor `TreeSitterDiscoverer.discover()` to use a thread pool.
2. Group the extracted `CSTNode` results, flatten, and sort them as is currently done.

---

## 8. Integration - Hub Daemon

### Reviewer's Recommendation
Hub daemon requires a separate process and is not tightly coupled with the main analysis flow. Recommends lazy initialization or an in-process option.

### My Assessment & Opinion
**Accurate**. Running `Hub` as a completely separate daemon process creates cognitive overhead for local development and complicates simple CLI executions.

### Suggestion for Improvement
Create an `InProcessHub` mode. The `RemoraAnalyzer` or `Coordinator` should be able to instantiate the Hub's `AgentFS` storage and fire up its watcher/rules engine as an asyncio background task within the same event loop when the user runs `remora analyze`.

### Refactoring Work Overview
1. Refactor the daemon loop in `hub/daemon.py` to allow execution as an `asyncio.Task`.
2. Update the Remora config to include a `hub.mode: "in-process" | "daemon"` flag.
3. Update `orchestrator.py` to start the Hub loop silently if configured for in-process.

---

## Conclusion
The reviewer's assessment was mostly accurate, successfully identifying several crucial areas for improvement such as the God object nature of `analyzer.py` and the brittle parsing inside `.pym` scripts. However, they misidentified the orchestrator's role in context building. 

The most impactful immediate refactor (highest ROI) will be replacing the hand-rolled JSON string parser in the sandboxed scripts with a natively injected `run_json_command` external. This will immediately resolve failing tests and unblock further feature development.
