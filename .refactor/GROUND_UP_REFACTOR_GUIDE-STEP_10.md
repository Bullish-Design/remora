# Implementation Guide for Step 10: Update Bundle YAML Files

## Overview

This step updates all `bundle.yaml` files to use the structured-agents v0.3 format with Remora-specific extensions. This implements Idea 2 from the design document.

## Current State (What You're Replacing)

All five bundles currently use the old v0.2 format:
- `agents/lint/bundle.yaml`
- `agents/docstring/bundle.yaml`
- `agents/test/bundle.yaml`
- `agents/sample_data/bundle.yaml`
- `agents/harness/bundle.yaml`

Old format characteristics:
- `model.plugin`, `model.adapter` (function_gemma + google/functiongemma-270m-it)
- `initial_context.system_prompt`, `initial_context.user_template`
- `termination_tool`
- Detailed `tools` config with `registry`, `inputs_override`, `context_providers`
- Separate `registries` section

## Target State

All bundles use structured-agents v0.3 format with Remora extensions:

```yaml
# Standard structured-agents v0.3 fields
name: <agent_name>
model: qwen
grammar: ebnf
limits: default

system_prompt: |
  <prompt text>

tools:
  - tools/<tool_name>.pym

termination: submit_result
max_turns: <number>

# Remora-specific extensions
node_types:
  - <node_type>
priority: <number>
requires_context: true
```

## Implementation Steps

### Step 1: Update lint bundle

**File:** `agents/lint/bundle.yaml`

```yaml
name: lint_agent
model: qwen
grammar: ebnf
limits: default

system_prompt: |
  You are a linting agent. Analyze the provided Python code for issues
  using the ruff linter, apply fixes when possible, and report results.

tools:
  - tools/run_linter.pym
  - tools/apply_fix.pym

termination: submit_result
max_turns: 8

node_types:
  - function
  - class
priority: 10
requires_context: true
```

### Step 2: Update docstring bundle

**File:** `agents/docstring/bundle.yaml`

```yaml
name: docstring_agent
model: qwen
grammar: ebnf
limits: default

system_prompt: |
  You are a docstring generation agent. Read the provided Python code,
  analyze existing docstrings and type hints, then write or update
  appropriate docstrings in the requested style.

tools:
  - tools/read_current_docstring.pym
  - tools/read_type_hints.pym
  - tools/write_docstring.pym

termination: submit_result
max_turns: 6

node_types:
  - function
  - class
priority: 5
requires_context: true
```

### Step 3: Update test bundle

**File:** `agents/test/bundle.yaml`

```yaml
name: test_agent
model: qwen
grammar: ebnf
limits: permissive

system_prompt: |
  You are a test generation agent. Read the provided Python code,
  analyze function signatures, check for existing tests, and generate
  appropriate pytest tests.

tools:
  - tools/analyze_signature.pym
  - tools/read_existing_tests.pym
  - tools/write_test_file.pym
  - tools/run_tests.pym

termination: submit_result
max_turns: 10

node_types:
  - function
priority: 15
requires_context: true
```

### Step 4: Update sample_data bundle

**File:** `agents/sample_data/bundle.yaml`

```yaml
name: sample_data_agent
model: qwen
grammar: ebnf
limits: default

system_prompt: |
  You are a fixture generation agent. Read the provided Python code,
  analyze function signatures, and generate appropriate fixture data
  for use in tests.

tools:
  - tools/analyze_signature.pym
  - tools/write_fixture_file.pym

termination: submit_result
max_turns: 6

node_types:
  - function
priority: 8
requires_context: true
```

### Step 5: Update harness bundle

**File:** `agents/harness/bundle.yaml`

```yaml
name: harness_agent
model: qwen
grammar: ebnf
limits: strict

system_prompt: |
  You are a tool invocation testing harness. Given a request payload,
  call the specified tool with the payload and return a summary of
  the result. This is used for testing agent tool calls.

tools:
  - tools/simple_tool.pym

termination: submit_result
max_turns: 3

node_types:
  - function
priority: 1
requires_context: false
```

### Step 6: Verify bundle loading

Test that each bundle can be loaded by structured-agents:

```bash
python -c "import structured_agents as sa; print(sa.Agent.from_bundle('agents/lint/'))"
python -c "import structured_agents as sa; print(sa.Agent.from_bundle('agents/docstring/'))"
python -c "import structured_agents as sa; print(sa.Agent.from_bundle('agents/test/'))"
python -c "import structured_agents as sa; print(sa.Agent.from_bundle('agents/sample_data/'))"
python -c "import structured_agents as sa; print(sa.Agent.from_bundle('agents/harness/'))"
```

## Field Mapping Reference

| Old Field (v0.2) | New Field (v0.3) |
|------------------|------------------|
| `model.plugin` + `model.adapter` | `model` (just "qwen") |
| `model.grammar.mode` | `grammar` |
| `model.grammar.args_format` | `limits` (permissive, default, strict) |
| `initial_context.system_prompt` | `system_prompt` |
| `initial_context.user_template` | Removed (handled by DataProvider) |
| `termination_tool` | `termination` |
| `tools[].registry` + path | `tools` (just path list) |
| `tools[].inputs_override` | Removed (inferred from .pym) |
| `tools[].context_providers` | Removed (handled by DataProvider) |
| N/A | `node_types` (Remora extension) |
| N/A | `priority` (Remora extension) |
| N/A | `requires_context` (Remora extension) |

## Limits Preset Reference

| Preset | Description |
|--------|-------------|
| `strict` | Low token limits, fast iteration, for simple tasks |
| `default` | Balanced limits for typical agent tasks |
| `permissive` | Higher limits, more iterations, for complex tasks like test generation |

## Remora Extension Fields

| Field | Type | Description |
|-------|------|-------------|
| `node_types` | list[str] | Which CSTNode types this agent handles (function, class, file) |
| `priority` | int | Execution priority in the agent graph (lower = runs first) |
| `requires_context` | bool | Whether to inject Two-Track Memory context |

## Common Pitfalls

1. **Tool paths must be relative to bundle.yaml** - Use `tools/tool_name.pym`, not absolute paths
2. **limits preset names must be valid** - Only: `strict`, `default`, `permissive`
3. **node_types must match discovery output** - Valid types: `function`, `class`, `file`
4. **Model name must be valid** - Check structured-agents docs for supported models
5. **termination must match a tool name** - The tool that ends the agent turn

## Verification Checklist

- [ ] All 5 bundle.yaml files updated to v0.3 format
- [ ] Remora extensions added (node_types, priority, requires_context)
- [ ] Each bundle loads without errors
- [ ] Tool paths are correct relative to bundle.yaml
- [ ] limits presets are appropriate for each agent's complexity
- [ ] priorities reflect dependency order (lower = earlier)
- [ ] requires_context is true for agents that benefit from Two-Track Memory

## Dependencies

- structured-agents v0.3+
- All .pym tool scripts must exist in each bundle's `tools/` directory
