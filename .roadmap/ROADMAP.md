# Remora MVP Roadmap

This roadmap breaks the MVP into discrete, testable, and verifiable steps.
Each milestone includes a clear deliverable and validation criteria.

## 1. Project skeleton + dependencies

**Goal:** Establish the package structure and CLI entrypoint.

**Deliverables:**
- `remora` package layout with core modules wired
- CLI entrypoint that exposes `analyze`, `watch`, `config`, `list-agents`

**Verification:**
- `python -m remora --help` lists CLI commands
- `remora --help` works once installed

## 2. Configuration system

**Goal:** Define and load configuration with CLI overrides.

**Deliverables:**
- `RemoraConfig` Pydantic schema and YAML loader
- CLI overrides merged with file defaults
- Validation errors mapped to exit code `3`

**Verification:**
- `remora config -f yaml` shows merged defaults
- Invalid config returns exit code `3` and error code `CONFIG_003`

## 3. Query files + node discovery

**Goal:** Load Tree-sitter queries and extract CST nodes.

**Deliverables:**
- `.scm` query loader for `function_def`, `class_def`, `file`
- `NodeDiscoverer` returns `CSTNode` with correct metadata

**Verification:**
- Discovery on fixtures returns expected nodes and node IDs
- Malformed query returns `DISC_002`

## 4. Orchestration layer + Cairn interface

**Goal:** Spawn coordinator agents per node and collect results.

**Deliverables:**
- `process_node` spawns coordinator via Cairn
- Concurrent node processing with configurable max concurrency
- Structured `NodeResult` aggregation

**Verification:**
- Mocked Cairn spawn/wait returns correct `NodeResult`
- Concurrency respects `max_concurrent`

## 5. Coordinator agent contract

**Goal:** Implement `coordinator.pym` to spawn specialized agents and aggregate.

**Deliverables:**
- Coordinator reads standard inputs and operation list
- Spawns specialized agents and aggregates result schemas
- Proper error logging and propagation

**Verification:**
- Contract tests validate output schema shape
- Agent errors recorded in `errors` with correct phase

## 6. Specialized agents MVP

**Goal:** Implement the bundled agents and ensure correct outputs.

**Deliverables:**
- `lint_agent.pym` using configured tools (ruff/pylint)
- `test_generator_agent.pym` with pytest/unittest support
- `docstring_agent.pym` with style configuration
- `sample_data_agent.pym` (optional if enabled in config)

**Verification:**
- Each agent returns `status`, `summary`, `changed_files`, `workspace_id`
- Output `details` match spec schemas

## 7. Results aggregation + formatting

**Goal:** Provide consistent user-facing results.

**Deliverables:**
- `AnalysisResults` model and derived metrics
- Table, JSON, and interactive formatters
- Failure summaries and next-step hints

**Verification:**
- Table output matches spec structure
- JSON output validates against schema
- Interactive flow prompts for accept/reject

## 8. Accept / reject / retry workflow

**Goal:** Expose change control for workspaces.

**Deliverables:**
- `RemoraAnalyzer.accept/reject/retry` methods
- Workspace merge and rollback via Cairn
- Operation-specific retry config overrides

**Verification:**
- Accept merges changes into stable workspace
- Reject leaves stable workspace unchanged
- Retry reruns with override config

## 9. CLI analyze + list-agents

**Goal:** Provide end-to-end CLI experience.

**Deliverables:**
- `remora analyze` runs full pipeline on target paths
- `remora list-agents` lists bundled agents
- Exit codes align with spec

**Verification:**
- Running `remora analyze` on sample project returns valid results
- `remora list-agents -f json` outputs schema-compliant JSON

## 10. Watch mode

**Goal:** Re-analyze files on change.

**Deliverables:**
- `remora watch` with debounce and path filtering
- Re-runs analysis only for modified files

**Verification:**
- Touching a `.py` file triggers re-analysis for that file only
- Debounce prevents rapid duplicate runs

## 11. MVP acceptance tests

**Goal:** Validate the MVP success criteria end-to-end.

**Deliverables:**
- Acceptance tests aligned to spec section 10.3
- Coverage of lint, test generation, docstring, concurrency, and watch

**Verification:**
1. Point at Python file → lint suggestions → accept changes → files updated
2. Point at function → generate tests → test file created
3. Point at class → add docstrings → docstrings added
4. Process multiple nodes concurrently → results returned for all
5. Fail one agent → others continue
6. Watch mode → file change triggers re-analysis

## MVP Exit Criteria

The MVP is complete when milestones 1–11 pass their verification checks and the acceptance criteria are green on a sample Python project.