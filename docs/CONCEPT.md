# Remora Concept

## Purpose

A library that combines **Pydantree** (CST node extraction) with **Cairn** (sandboxed execution) and **custom-trained FunctionGemma subagents** to automatically analyze and enhance Python code at the node level — entirely locally, with no API dependencies.

Each CST node (file, class, function) is processed by a domain-specific FunctionGemma model that reasons about its task in a multi-turn tool calling loop, decides which tools to invoke, inspects the results, and iterates until done — all inside an isolated Cairn workspace.

## The Core Idea

Traditional code analysis tools run static, deterministic pipelines: lint the file, write the output, done. This works for simple cases but falls apart when the task requires multi-step reasoning:

- A generated test fails because a fixture is missing — should the agent try another approach or report the failure?
- A lint issue can only be fixed by understanding broader context than just the node
- A docstring needs to reference the style used in sibling functions

Remora's answer is to give each specialized agent a small language model that can **observe, reason, and iterate**. The model examines the situation, calls a tool, inspects the result, and decides what to do next — all within the same isolated workspace.

## Architecture

### Four-Layer Design

```
┌─────────────────────────────────────────────────────────┐
│  Application Layer                                       │
│  - CLI interface (analyze, watch, config, list-agents)   │
│  - Configuration management                              │
│  - Reactive file watching                                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Orchestration Layer                                     │
│  - Node discovery (Pydantree + Tree-sitter queries)      │
│  - Coordinator: routes nodes to FunctionGemma runners    │
│  - Result aggregation and presentation                   │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  FunctionGemma Runner Layer (new)                        │
│  - Loads subagent YAML definition                        │
│  - Builds initial context from CSTNode                   │
│  - Runs multi-turn tool calling loop                     │
│  - Dispatches tool calls → .pym scripts via Cairn        │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Execution Layer (Cairn)                                 │
│  - Individual tool .pym scripts per subagent             │
│  - Copy-on-write sandboxed execution                     │
│  - Human review gate: accept / reject / retry            │
└─────────────────────────────────────────────────────────┘
```

## FunctionGemma Subagents

### What They Are

Each specialized agent in Remora is a **fine-tuned FunctionGemma model** paired with a YAML definition file that describes its tool catalog and initial context. The base model is Google's FunctionGemma — a 270M parameter model purpose-built for structured tool calling. Remora fine-tunes a separate model checkpoint for each agent domain (lint, test, docstring, sample data), giving each model deep specialization in its task.

At ~288MB per model (Q8 GGUF quantization), the entire agent fleet fits in under 1.5GB and runs on a single CPU with no API keys, no network calls, and no data leaving the machine.

### The Multi-Turn Loop

Instead of a monolithic script that runs once, each FunctionGemma subagent runs in a **multi-turn tool calling loop**:

```
1. Build initial messages (system prompt + CST node context)
2. Call model with tool catalog → model responds with tool_calls or text
3. If tool_calls:
   a. For each tool call:
      - Run any per-tool context providers (inject into messages)
      - Execute the tool's .pym script in the Cairn workspace
      - Append tool result to messages
   b. Go to step 2
4. If no tool_calls (or submit_result called): task complete
```

The model can call tools in sequence, read their outputs, decide whether to try again or proceed differently, and ultimately call `submit_result` when it determines the task is done.

### Subagent Definition Format

Each subagent is described by a YAML file that specifies:

1. **The model** — path to the fine-tuned GGUF checkpoint for this domain
2. **Initial context** — system prompt and node context template (injected once at spawn)
3. **Tool catalog** — 4–8 coarse-grained tools, each backed by a `.pym` script
4. **Per-tool context providers** — optional `.pym` scripts that inject domain-specific context at the moment a tool is invoked

```yaml
# agents/lint/lint_subagent.yaml
name: lint_agent
model: agents/lint/models/lint_functiongemma_q8.gguf

initial_context:
  system_prompt: |
    You are a Python linting specialist. Analyze the provided code,
    apply safe auto-fixes, and report issues requiring manual attention.
  node_context: |
    Code to analyze:
    ```python
    {{ node_text }}
    ```

tools:
  - name: run_linter
    pym: agents/lint/tools/run_linter.pym
    description: Run the linter and return a list of issues with line numbers.
    parameters: { ... }
    context_providers:
      - agents/lint/context/ruff_config.pym

  - name: apply_fix
    pym: agents/lint/tools/apply_fix.pym
    description: Apply a fix for a specific lint issue code.
    parameters: { ... }

  - name: read_current_file
    pym: agents/lint/tools/read_file.pym
    description: Read the current state of the file being analyzed.
    parameters: { ... }

  - name: submit_result
    pym: agents/lint/tools/submit.pym
    description: Submit results and end the task.
    parameters: { ... }
```

### Agent Layout on Disk

```
agents/
├── lint/
│   ├── lint_subagent.yaml
│   ├── models/
│   │   └── lint_functiongemma_q8.gguf     # ~288MB, domain fine-tuned
│   ├── tools/
│   │   ├── run_linter.pym
│   │   ├── apply_fix.pym
│   │   ├── read_file.pym
│   │   └── submit.pym
│   └── context/
│       └── ruff_config.pym                # Per-tool context provider
├── test/
│   ├── test_subagent.yaml
│   ├── models/
│   │   └── test_functiongemma_q8.gguf
│   └── tools/ ...
├── docstring/
│   └── ...
└── sample_data/
    └── ...
```

## Data Flow

### Node Processing Pipeline

```
Python Source Code
    ↓
[Pydantree] Extract CST nodes via Tree-sitter queries
    ↓
[Coordinator] Route each node to relevant FunctionGemma runners
    ↓
[FunctionGemmaRunner × N] Each subagent runs multi-turn tool calling loop
    ├── lint runner     → run_linter.pym, apply_fix.pym
    ├── test runner     → analyze_signature.pym, write_test_file.pym, run_tests.pym
    ├── docstring runner→ read_docstring.pym, write_docstring.pym
    └── sample_data runner → analyze_signature.pym, write_fixture_file.pym
    ↓
[Cairn Workspaces] Each runner writes to its own isolated workspace
    ↓
[Human Review] User accepts / rejects / retries per operation or per node
```

### Workspace Isolation

```
.agentfs/
├── stable.db                          # Original codebase (never touched during runs)
├── coordinator-{node-id}.db           # Coordinator workspace
├── lint-{node-id}.db                  # All lint tool writes land here
├── test-{node-id}.db                  # All test tool writes land here
├── docstring-{node-id}.db             # All docstring tool writes land here
└── sample_data-{node-id}.db           # All sample_data tool writes land here
```

## Key Components

### 1. Node Discovery Engine

Uses Pydantree with custom Tree-sitter `.scm` queries to extract CST nodes:
- `function_def.scm` — all function definitions
- `class_def.scm` — all class definitions
- `file.scm` — file-level structure

Returns `CSTNode` objects with name, location, source text, and a unique node ID.

### 2. Coordinator

Receives a `CSTNode` and the list of configured operations, then for each operation spawns a `FunctionGemmaRunner` with the appropriate subagent YAML. The coordinator does not need to know the internals of any subagent — it only receives back the standard result contract:

```python
{
    "status": "success" | "failed" | "skipped",
    "workspace_id": str,
    "changed_files": list[str],
    "summary": str,
    "details": dict,
    "error": str | None
}
```

### 3. FunctionGemmaRunner

The central new component. Responsibilities:

- Load and validate the subagent YAML definition
- Initialize the GGUF model via llama.cpp
- Build the initial message list from the system prompt and rendered node context
- Run the multi-turn tool calling loop until `submit_result` or turn limit
- For each tool call: execute per-tool context providers, dispatch the `.pym` tool, append the result
- Return the final structured result to the coordinator

### 4. Tool Scripts

Each subagent has 4–8 coarse-grained `.pym` tools. Tools are distinct from each other along two axes:
- **Read vs. mutate** — reading tools inspect the workspace; mutating tools modify it
- **Domain specificity** — tools correspond to meaningful steps in the workflow, not low-level primitives

The `submit_result` tool is always the terminal action and is always present in every subagent.

### 5. Context Providers

Optional `.pym` scripts attached to specific tools. A context provider runs immediately before the tool is dispatched and injects domain-specific information into the conversation. For example, the lint agent's `apply_fix` tool has a `ruff_config.pym` provider that reads the project's `ruff.toml` and injects it as context at the moment the model is deciding which fix to apply.

This keeps the initial context minimal and focused — domain context enters the conversation exactly when it is relevant.

### 6. Result Aggregator

Collects `NodeResult` objects from all coordinators and presents them in table, JSON, or interactive format. Manages the accept/reject/retry workflow via Cairn workspace operations.

## Local Execution Model

FunctionGemma subagents are designed to run entirely offline:

| Property | Value |
|---|---|
| Model format | GGUF (quantized) |
| Model size | ~288MB per subagent (Q8) |
| Inference speed | ~125 tokens/sec on single CPU core |
| Runtime | llama.cpp (via llama-cpp-python) |
| Network dependency | None |
| API keys | None |
| Data egress | None |

Multiple subagent models run simultaneously (one per operation), matching the coordinator's existing concurrency model.

## Fine-Tuning

Each subagent uses a separately fine-tuned checkpoint of the FunctionGemma base model. Fine-tuning is performed on synthetic training examples in the `training/` directory:

```
training/
├── lint/
│   ├── generate_examples.py     # Script to produce training examples
│   ├── examples/                # Generated JSONL training data
│   └── fine_tune.py             # Fine-tuning script
├── test/
├── docstring/
└── sample_data/
```

Training examples follow the multi-turn tool calling conversation format. A training example consists of a starting context (node + system prompt), a sequence of tool calls and results, and a terminal `submit_result` call.

The fine-tuning pipeline outputs a GGUF file for each domain that is placed at the path referenced in the subagent YAML.

## MVP Scope

### Phase 1: Core Infrastructure
- [ ] Project structure, CLI entrypoint, dependencies
- [ ] Configuration system (Pydantic, YAML, CLI overrides)
- [ ] Node discovery with Pydantree

### Phase 2: FunctionGemma Runner
- [ ] Subagent YAML definition parser
- [ ] FunctionGemmaRunner: model loading via llama-cpp-python
- [ ] Multi-turn tool calling loop
- [ ] Per-tool context provider dispatch

### Phase 3: Subagent Tool Scripts
- [ ] Tool scripts for lint subagent
- [ ] Tool scripts for test subagent
- [ ] Tool scripts for docstring subagent
- [ ] Tool scripts for sample_data subagent

### Phase 4: Training Pipeline
- [ ] Training data generation scripts (per domain)
- [ ] Fine-tuning pipeline for FunctionGemma base model
- [ ] GGUF conversion and packaging

### Phase 5: Integration
- [ ] Coordinator integration (spawns FunctionGemmaRunner per operation)
- [ ] Results aggregation, formatting, accept/reject/retry
- [ ] CLI commands and watch mode
- [ ] End-to-end acceptance tests

## Success Metrics

The MVP is successful when:

- Point at a Python file → each subagent model runs locally, reasons about the code, and produces: lint fixes, generated tests, improved docstrings
- Review and accept/reject changes per operation or per node via Cairn workspaces
- Zero network calls during analysis — models, tools, and context providers all run locally
- Multiple nodes processed concurrently
- Watch mode re-triggers subagents on file changes

## Technology Stack

| Layer | Component | Technology |
|---|---|---|
| Application | CLI | Typer |
| Application | Config | Pydantic |
| Application | Terminal UI | Rich |
| Application | File Watching | watchfiles |
| Orchestration | Node Discovery | Pydantree + Tree-sitter |
| Orchestration | Async Runtime | AsyncIO |
| Execution | Model Inference | llama-cpp-python |
| Execution | Model Format | GGUF (Q8) |
| Execution | Sandbox | Cairn (.pym scripts) |
| Execution | Workspace Isolation | Cairn Copy-on-Write |
| Training | Fine-tuning | Unsloth / HuggingFace PEFT |
| Training | Base Model | FunctionGemma (270M) |
