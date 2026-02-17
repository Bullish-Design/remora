# Remora MVP Roadmap

This roadmap breaks the MVP into discrete, testable, and verifiable steps. The architecture is built around **custom-trained FunctionGemma subagents** — fine-tuned 270M parameter models that run locally and drive code analysis through a multi-turn tool calling loop.

Each milestone has a clear deliverable and verification criteria. Steps 1–4 establish infrastructure; Steps 5–7 build the FunctionGemma runner and subagent definitions; Steps 8–11 implement tool scripts for each domain; Steps 12–14 build and integrate the training pipeline; Steps 15–18 wire everything together and deliver the end-user experience.

---

## 1. Project Skeleton + Dependencies

**Goal:** Establish the package structure, CLI entrypoint, and dependency manifest.

**Deliverables:**
- `remora/` package with core modules wired
- `pyproject.toml` with all dependencies (typer, rich, pydantic, pydantree, cairn, llama-cpp-python, jinja2, watchfiles)
- CLI entrypoint exposing `analyze`, `watch`, `config`, `list-agents`

**Verification:**
- `python -m remora --help` lists all CLI commands
- `remora --help` works after install
- `python -c "from llama_cpp import Llama"` succeeds

---

## 2. Configuration System

**Goal:** Define and load all configuration with CLI overrides.

**Deliverables:**
- `RemoraConfig` Pydantic schema including `RunnerConfig` (max_turns, max_concurrent_runners, timeout)
- YAML loader with CLI override merging
- `OperationConfig` with `subagent` path field replacing old monolithic agent paths
- Validation errors mapped to `CONFIG_00x` exit codes

**Verification:**
- `remora config -f yaml` shows merged defaults including runner settings
- Invalid config returns exit code `3` and error `CONFIG_003`
- Missing `agents_dir` returns `CONFIG_004`

---

## 3. Query Files + Node Discovery

**Goal:** Load Tree-sitter queries and extract CST nodes.

**Deliverables:**
- `.scm` query loader for `function_def`, `class_def`, `file`
- `NodeDiscoverer` returns `CSTNode` objects with correct metadata and node IDs
- Node IDs computed as `hash(file_path + node_type + name)`

**Verification:**
- Discovery on fixture files returns expected nodes with correct `node_id`, `text`, `file_path`
- Malformed query returns `DISC_002`
- Overlapping queries (e.g., function inside class) produce distinct nodes

---

## 4. Subagent Definition Format

**Goal:** Parse and validate YAML subagent definition files; build tool schema objects.

**Deliverables:**
- `SubagentDefinition`, `ToolDefinition`, `InitialContext` Pydantic models
- YAML loader that validates structure and resolves `pym`/`model` paths relative to `agents_dir`
- `SubagentDefinition.tool_schemas` property returns OpenAI-compatible tool list
- Jinja2 template rendering for `node_context` (`{{ node_text }}`, `{{ node_name }}`, etc.)

**Verification:**
- Loading `agents/lint/lint_subagent.yaml` fixture produces correct `SubagentDefinition`
- Invalid YAML (missing `submit_result` tool) raises `AGENT_001`
- Rendered `node_context` correctly interpolates CSTNode fields
- `tool_schemas` output matches expected JSON schema structure with `"strict": true`

---

## 5. FunctionGemmaRunner — Model Loading + Context

**Goal:** Implement the runner's initialization: load the GGUF model and build initial messages.

**Deliverables:**
- `FunctionGemmaRunner` class with `SubagentDefinition`, `CSTNode`, `workspace_id`, `cairn_client`
- `ModelCache` singleton to avoid reloading 288MB models between runs
- `_build_initial_messages()` — renders system prompt + node context into initial message list
- `AGENT_002` error when GGUF file not found at definition's model path

**Verification:**
- Runner initializes without error when given a valid GGUF path
- `ModelCache.get(path)` returns same `Llama` instance on second call
- Initial message list has correct `system` + `user` roles and rendered node text
- Missing GGUF returns `AGENT_002` without crashing other runners

---

## 6. FunctionGemmaRunner — Multi-Turn Loop

**Goal:** Implement the core tool calling loop.

**Deliverables:**
- `run()` method: calls model, parses `tool_calls` or `stop`, dispatches tools, appends results
- `_dispatch_tool()`: runs context providers (if any), executes `.pym` tool via Cairn
- Terminal detection: `submit_result` tool call exits loop and returns `AgentResult`
- Turn limit enforcement with `AGENT_003` error on overflow

**Verification:**
- Mock model that immediately calls `submit_result` returns `AgentResult` after 1 turn
- Mock model that calls 3 tools then `submit_result` returns result after 4 turns
- Model that never calls `submit_result` raises `AGENT_003` at `max_turns`
- Context providers are injected into messages before the tool they're attached to

---

## 7. Coordinator — FunctionGemmaRunner Dispatch

**Goal:** Wire the orchestration layer to spawn FunctionGemmaRunner instances.

**Deliverables:**
- `Coordinator.process_node(node, operations)` spawns one `FunctionGemmaRunner` per operation
- Concurrent runner execution via `asyncio.gather`, bounded by `max_concurrent_runners` semaphore
- `NodeResult` aggregation from runner outputs
- Per-operation error isolation: failed runners don't halt sibling runners

**Verification:**
- Mocked runners return correct `NodeResult` shape
- Semaphore correctly limits concurrency to `max_concurrent_runners`
- One runner raising an exception is captured as an error in `NodeResult`, others succeed
- Coordinator does not require a Cairn `.pym` script

---

## 8. Lint Subagent Tool Scripts

**Goal:** Implement all `.pym` tool scripts and context provider for the lint subagent.

**Deliverables:**
- `agents/lint/tools/run_linter.pym` — runs ruff on workspace file, returns issue list
- `agents/lint/tools/apply_fix.pym` — applies a single auto-fixable issue by code + line
- `agents/lint/tools/read_file.pym` — reads current file state from workspace
- `agents/lint/tools/submit.pym` — returns standard result schema and terminates
- `agents/lint/context/ruff_config.pym` — reads `ruff.toml` / `pyproject.toml` lint config
- `agents/lint/lint_subagent.yaml` — complete definition file for lint subagent

**Verification:**
- `run_linter.pym` on fixture file with known issues returns expected issue codes
- `apply_fix.pym` on E225 issue produces correctly formatted output
- `submit.pym` output validates against the standard agent result schema
- `ruff_config.pym` returns empty string gracefully when no ruff config exists

---

## 9. Test Subagent Tool Scripts

**Goal:** Implement all `.pym` tool scripts and context provider for the test subagent.

**Deliverables:**
- `agents/test/tools/analyze_signature.pym` — extracts function name, parameters, type hints, return type
- `agents/test/tools/read_existing_tests.pym` — reads test file if it exists, returns empty string otherwise
- `agents/test/tools/write_test_file.pym` — writes test content to test file path in workspace
- `agents/test/tools/run_tests.pym` — runs pytest on workspace, returns pass/fail/error per test
- `agents/test/tools/submit.pym` — returns standard result schema
- `agents/test/context/pytest_config.pym` — reads pytest.ini / pyproject.toml test config
- `agents/test/test_subagent.yaml` — complete definition file

**Verification:**
- `analyze_signature.pym` on a typed function returns correct parameter and return type data
- `write_test_file.pym` creates a file at the expected test path in workspace
- `run_tests.pym` on passing tests returns `{"passed": N, "failed": 0}`
- `run_tests.pym` on a failing test captures the failure message

---

## 10. Docstring Subagent Tool Scripts

**Goal:** Implement all `.pym` tool scripts and context provider for the docstring subagent.

**Deliverables:**
- `agents/docstring/tools/read_current_docstring.pym` — extracts existing docstring or returns null
- `agents/docstring/tools/read_type_hints.pym` — extracts parameter and return type annotations
- `agents/docstring/tools/write_docstring.pym` — injects a new docstring into the source file at the correct position
- `agents/docstring/tools/submit.pym` — returns standard result schema
- `agents/docstring/context/docstring_style.pym` — reads configured style (google/numpy/sphinx) from project
- `agents/docstring/docstring_subagent.yaml` — complete definition file

**Verification:**
- `write_docstring.pym` on a function with no existing docstring injects immediately after `def` line
- `write_docstring.pym` on a function with an existing docstring replaces it correctly
- `read_current_docstring.pym` returns `null` for undocumented functions
- `docstring_style.pym` returns `google` as default when no config found

---

## 11. Sample Data Subagent Tool Scripts

**Goal:** Implement all `.pym` tool scripts and context provider for the sample_data subagent.

**Deliverables:**
- `agents/sample_data/tools/analyze_signature.pym` — extracts parameter types and defaults
- `agents/sample_data/tools/write_fixture_file.pym` — writes JSON/YAML fixture file to workspace
- `agents/sample_data/tools/submit.pym` — returns standard result schema
- `agents/sample_data/context/existing_fixtures.pym` — lists any existing fixture files for reference
- `agents/sample_data/sample_data_subagent.yaml` — complete definition file

**Verification:**
- `write_fixture_file.pym` writes valid JSON to the expected fixture path
- `analyze_signature.pym` on a function with default values includes defaults in output
- `submit.pym` output validates against standard agent result schema

---

## 12. Training Data Generation

**Goal:** Build scripts that generate synthetic multi-turn training examples for each domain.

**Deliverables:**
- `training/shared/conversation_schema.py` — Pydantic models for the training conversation format
- `training/lint/generate_examples.py` — generates N lint training conversations from Python fixtures
- `training/test/generate_examples.py` — generates N test generation training conversations
- `training/docstring/generate_examples.py` — generates N docstring training conversations
- `training/sample_data/generate_examples.py` — generates N sample data training conversations
- JSONL outputs in `training/{domain}/examples/`

**Verification:**
- Each generator produces valid JSONL with correct conversation structure
- Every conversation ends with a `submit_result` tool call
- Tool call arguments in training data match the YAML schemas for each domain
- Generation scripts accept `--count N` to control example count

---

## 13. Fine-Tuning Pipeline + GGUF Export

**Goal:** Fine-tune the FunctionGemma base model for each domain and export GGUF files.

**Deliverables:**
- `training/shared/base_model.py` — downloads/caches FunctionGemma base model
- `training/{domain}/fine_tune.py` — LoRA fine-tuning script using Unsloth/PEFT
- `training/shared/gguf_export.py` — converts fine-tuned checkpoint to Q8 GGUF
- GGUF output placed at `agents/{domain}/models/{domain}_functiongemma_q8.gguf`
- `training/Makefile` with targets: `generate`, `train-{domain}`, `export-{domain}`, `train-all`

**Verification:**
- `make train-lint` produces a GGUF file at the expected path
- GGUF file loads successfully via `llama-cpp-python` (no crash on init)
- Exported model responds to a sample tool call prompt with valid tool call JSON
- File sizes are ~288MB ± 10% (Q8 quantization of 270M params)

---

## 14. End-to-End Runner Integration Test

**Goal:** Validate the full `FunctionGemmaRunner` → tool scripts → result pipeline with real GGUF models.

**Deliverables:**
- Integration test fixture: a small Python file with known lint issues, undocumented functions, and no tests
- Integration test: run lint, test, and docstring runners against fixture; verify `AgentResult` outputs
- Verify each runner produces `status=success` and non-empty `changed_files`
- Verify workspace diffs are non-empty and correspond to expected changes

**Verification:**
- Lint runner fixes at least one known issue in fixture file
- Test runner writes a new test file to workspace
- Docstring runner injects a docstring for each undocumented function
- All runners complete within configured timeout

---

## 15. Results Aggregation + Formatting

**Goal:** Provide consistent user-facing results from all runners.

**Deliverables:**
- `AnalysisResults` and `NodeResult` Pydantic models
- Table formatter (node × operation grid with status indicators)
- JSON formatter (machine-readable output)
- Interactive formatter (step-through accept/reject prompts)
- Failure summaries with per-operation error details

**Verification:**
- Table output correctly renders success/failure/skipped for each cell
- JSON output validates against the `AnalysisResults` schema
- Interactive flow prompts user and routes to correct Cairn accept/reject call

---

## 16. Accept / Reject / Retry Workflow

**Goal:** Expose change control for per-operation workspaces.

**Deliverables:**
- `RemoraAnalyzer.accept(node_id, operation)` — merges workspace into stable via Cairn
- `RemoraAnalyzer.reject(node_id, operation)` — discards workspace, stable unchanged
- `RemoraAnalyzer.retry(node_id, operation, config_override)` — re-runs runner with overrides
- Workspace merge and rollback via Cairn

**Verification:**
- `accept()` merges lint workspace; changed file appears in stable workspace
- `reject()` leaves stable workspace unchanged after a lint run
- `retry()` with `{"max_turns": 30}` re-runs the runner with higher turn limit

---

## 17. CLI + Watch Mode

**Goal:** Deliver end-to-end CLI experience including reactive watch mode.

**Deliverables:**
- `remora analyze <paths>` — full pipeline with all configured operations
- `remora watch <paths>` — debounced re-analysis on file changes
- `remora list-agents` — lists available subagent definitions with GGUF status
- `remora config -f yaml` — displays merged configuration
- Exit codes aligned with spec

**Verification:**
- `remora analyze src/fixture.py` returns valid output and correct exit code
- `remora list-agents -f json` shows all four subagents with model path and status
- Touching a `.py` file in watch mode triggers re-analysis for that file only
- Debounce prevents rapid duplicate runs within the configured window

---

## 18. MVP Acceptance Tests

**Goal:** Validate the MVP success criteria end-to-end on a sample Python project.

**Deliverables:**
- Acceptance test suite covering all six scenarios below
- Uses real GGUF models (not mocks) for integration validation

**Verification Scenarios:**
1. Point at Python file → lint runner identifies and fixes style issues → accept → changes in stable workspace
2. Point at undocumented function → docstring runner injects docstring → accept → docstring in source
3. Point at function → test runner generates pytest file → accept → test file exists in stable workspace
4. Process file with 5+ functions → all run concurrently → results returned for all nodes
5. Deliberately break one runner (invalid GGUF path) → other runners complete successfully
6. Watch mode → save a Python file → re-analysis runs automatically for that file

## MVP Exit Criteria

The MVP is complete when milestones 1–18 pass their verification checks and the six acceptance scenarios pass against a sample Python project using real fine-tuned GGUF models.
