# Remora Harness Refactoring Guide

This guide provides step-by-step instructions to fix the FunctionGemma harness issues identified in `HARNESS_IMPROVEMENT_REVIEW.md`. Follow each step in order — later steps build on earlier work.

> **Target audience:** Developers new to the Remora codebase.
> **Prerequisites:** Read `HOW_TO_CREATE_AN_AGENT.md` and `HOW_TO_CREATE_A_GRAIL_PYM_SCRIPT.md` first.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Phase 1: Core Runner Fixes](#2-phase-1-core-runner-fixes)
3. [Phase 2: JSON Fallback Parsing](#3-phase-2-json-fallback-parsing)
4. [Phase 3: Harness Configuration](#4-phase-3-harness-configuration)
5. [Phase 4: System Prompt Improvements](#5-phase-4-system-prompt-improvements)
6. [Phase 5: Performance Optimizations](#6-phase-5-performance-optimizations)
7. [Phase 6: Production Agent Validation](#7-phase-6-production-agent-validation)
8. [Appendix A: Agent-Specific Improvements](#appendix-a-agent-specific-improvements)
9. [Appendix B: Testing Commands](#appendix-b-testing-commands)
10. [Appendix C: Rollback Procedures](#appendix-c-rollback-procedures)

---

## 1. Overview

### Problem Summary

The Remora harness produces poor tool-call rates because:

1. **Conversation history is not sent** — Each model call receives only `[system, user]`, not accumulated history
2. **No JSON fallback parsing** — Tool calls in JSON content are missed
3. **Suboptimal defaults** — `temperature=0.1` and `tool_choice="auto"` differ from working examples
4. **Minimal system prompts** — Lack explicit tool-calling directives

### Impact by Agent Type

| Agent | max_turns | Impact of Missing History |
|-------|-----------|---------------------------|
| harness | 2 | Low (single-turn test) |
| docstring | 15 | **CRITICAL** (multi-turn) |
| lint | 15 | **CRITICAL** (multi-turn) |
| test | 20 | **CRITICAL** (multi-turn) |
| sample_data | 12 | **HIGH** (multi-turn) |

### Refactoring Order

```
Phase 1: Fix core runner (conversation history)     ← CRITICAL
    ↓
Phase 2: Add JSON fallback parsing                  ← HIGH
    ↓
Phase 3: Update harness configuration               ← HIGH
    ↓
Phase 4: Improve system prompts                     ← MEDIUM
    ↓
Phase 5: Performance optimizations                  ← LOW
    ↓
Phase 6: Validate production agents                 ← VERIFICATION
```

---

## 2. Phase 1: Core Runner Fixes

**Goal:** Fix `_build_prompt_messages()` to send full conversation history.

**Files to modify:**
- `src/remora/runner.py`

### Step 1.1: Understand the Current Bug

The bug is in `_build_prompt_messages()` (lines 246-254):

```python
# CURRENT (BUGGY) — Always returns fresh [system, user]
def _build_prompt_messages(self) -> list[ChatCompletionMessageParam]:
    prompt_context = None
    if self.runner_config.include_prompt_context:
        prompt_context = self.context_manager.get_prompt_context()
    system_prompt = self._build_system_prompt(prompt_context)
    return [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt}),
        cast(ChatCompletionMessageParam, {"role": "user", "content": self._initial_message}),
    ]
```

The method rebuilds messages from scratch, ignoring `self.messages` which accumulates assistant responses and tool results.

### Step 1.2: Replace `_build_prompt_messages()`

Replace the entire method with:

```python
def _build_prompt_messages(self) -> list[ChatCompletionMessageParam]:
    """Return the full accumulated conversation history.

    The system prompt (messages[0]) is updated in-place if include_prompt_context
    is enabled, allowing dynamic context injection while preserving history.
    """
    # Update system prompt with current context if enabled
    if self.runner_config.include_prompt_context:
        prompt_context = self.context_manager.get_prompt_context()
        system_content = self._build_system_prompt(prompt_context)
    else:
        system_content = self._build_system_prompt(None)

    # Update system message in-place (it's always at index 0)
    self.messages[0] = cast(
        ChatCompletionMessageParam,
        {"role": "system", "content": system_content}
    )

    # Return a copy to prevent external mutation
    return list(self.messages)
```

### Step 1.3: Verify Message Initialization

Confirm that `__post_init__` correctly initializes `self.messages` (lines 140-143):

```python
self.messages = []
self.turn_count = 0
self.messages.append(cast(ChatCompletionMessageParam, {"role": "system", "content": self._system_prompt}))
self.messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": self._initial_message}))
```

This is correct — no changes needed here.

### Step 1.4: Verify Message Accumulation

Confirm that the `run()` method correctly appends messages (lines 264-287):

```python
# Assistant response (line 264)
self.messages.append(self._coerce_message_param(message))

# Tool results (lines 277-287)
self.messages.append(
    cast(
        ChatCompletionMessageParam,
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": tool_result_content,
        },
    )
)
```

This is correct — no changes needed here.

### Validation: Phase 1

Run these tests to verify the fix:

```bash
# 1. Unit test: Verify messages grow across turns
python -c "
from remora.runner import FunctionGemmaRunner
# Create a mock runner and verify self.messages grows
# (Requires test fixtures - see tests/unit/test_runner.py)
"

# 2. Integration test: Run harness with verbose logging
python scripts/functiongemma_harness.py \
    --requests-per-variant 5 \
    --concurrency 1

# Check event logs for message counts:
# - Turn 1: messages=2 (system, user)
# - Turn 2: messages=5 (system, user, assistant, tool, assistant)
# Look for MODEL_REQUEST_DEBUG events with increasing message counts

# 3. Manual verification: Enable LLM logging
# In remora.yaml:
#   llm_log:
#     enabled: true
#     include_full_prompts: true
# Then check .remora_cache/llm_conversations.log for full message arrays
```

**Expected Results:**
- Message count should increase with each turn (2 → 5 → 8 → ...)
- Tool results should appear in subsequent prompts
- No "Turn limit exceeded" errors for simple tasks

---

## 3. Phase 2: JSON Fallback Parsing

**Goal:** Parse tool calls from JSON content when `message.tool_calls` is empty.

**Files to modify:**
- `src/remora/runner.py`

### Step 2.1: Create a Tool Call Parser Module

Create a new file `src/remora/tool_parser.py`:

```python
"""Tool call parsing utilities.

Provides fallback parsing when the model returns tool calls as JSON
in the content field instead of the structured tool_calls field.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedToolCall:
    """A tool call extracted from JSON content."""
    name: str
    arguments: dict[str, Any]

    @property
    def id(self) -> str:
        """Generate a synthetic ID for tool result pairing."""
        import uuid
        return f"parsed-{uuid.uuid4().hex[:8]}"


def parse_tool_call_from_content(content: str) -> ParsedToolCall | None:
    """Attempt to parse a tool call from JSON content.

    Supports three formats:
    1. Direct: {"name": "tool_name", "arguments": {...}}
    2. Direct with parameters: {"name": "tool_name", "parameters": {...}}
    3. OpenAI array: {"tool_calls": [{"function": {"name": ..., "arguments": ...}}]}

    Args:
        content: The message content to parse.

    Returns:
        ParsedToolCall if parsing succeeds, None otherwise.
    """
    if not content or not content.strip():
        return None

    try:
        parsed = json.loads(content.strip())
    except json.JSONDecodeError:
        logger.debug("Content is not valid JSON: %s", content[:100])
        return None

    if not isinstance(parsed, dict):
        logger.debug("Parsed JSON is not a dict: %s", type(parsed))
        return None

    # Format 1 & 2: Direct format with "name" key
    if "name" in parsed:
        name = parsed["name"]
        # Support both "arguments" and "parameters" keys
        arguments = parsed.get("arguments", parsed.get("parameters", {}))

        # Arguments might be a JSON string that needs parsing
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if not isinstance(arguments, dict):
            arguments = {}

        logger.debug("Parsed direct format tool call: %s", name)
        return ParsedToolCall(name=name, arguments=arguments)

    # Format 3: OpenAI tool_calls array format
    if "tool_calls" in parsed:
        tool_calls = parsed["tool_calls"]
        if isinstance(tool_calls, list) and len(tool_calls) > 0:
            first_call = tool_calls[0]
            if isinstance(first_call, dict) and "function" in first_call:
                function = first_call["function"]
                name = function.get("name")
                arguments = function.get("arguments", {})

                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                if name and isinstance(arguments, dict):
                    logger.debug("Parsed OpenAI format tool call: %s", name)
                    return ParsedToolCall(name=name, arguments=arguments)

    logger.debug("No tool call pattern found in JSON")
    return None
```

### Step 2.2: Integrate Parser into Runner

Modify `src/remora/runner.py` to use the parser.

Add the import at the top:

```python
from remora.tool_parser import parse_tool_call_from_content, ParsedToolCall
```

Replace `_handle_no_tool_calls()` (lines 427-452) with:

```python
async def _handle_no_tool_calls(self, message: ChatCompletionMessage) -> AgentResult | None:
    """Handle a model response with no structured tool_calls.

    Attempts to parse tool calls from JSON content. If parsing fails
    and tool_choice is "required", raises an error. Otherwise, treats
    the content as a final result.
    """
    content = message.content or ""

    # Try to parse a tool call from content
    parsed_call = parse_tool_call_from_content(content)

    if parsed_call is not None:
        # We found a tool call in the content — dispatch it
        return await self._dispatch_parsed_tool_call(parsed_call)

    # No tool call found
    if self.runner_config.tool_choice == "required":
        raise AgentError(
            node_id=self.node.node_id,
            operation=self.definition.name,
            phase="loop",
            error_code=AGENT_003,
            message=f"Model stopped without calling {SUBMIT_RESULT_TOOL}",
        )

    # Treat content as a fallback result
    if content:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return self._build_submit_result(parsed)
        except json.JSONDecodeError:
            pass

    # Return a minimal success result
    result_data = {
        "status": AgentStatus.SUCCESS,
        "workspace_id": self.workspace_id,
        "changed_files": [],
        "summary": content,
        "details": {},
        "error": None,
    }
    return AgentResult.model_validate(result_data)
```

### Step 2.3: Add Parsed Tool Call Dispatch Method

Add this new method to `FunctionGemmaRunner`:

```python
async def _dispatch_parsed_tool_call(self, parsed_call: ParsedToolCall) -> AgentResult | None:
    """Dispatch a tool call parsed from JSON content.

    This method handles tool calls that were extracted from message.content
    instead of message.tool_calls. It synthesizes the necessary fields and
    delegates to the standard dispatch flow.
    """
    tool_name = parsed_call.name
    arguments = parsed_call.arguments

    # Check if this is submit_result
    if tool_name == SUBMIT_RESULT_TOOL:
        return self._build_submit_result(arguments)

    # Emit tool call event
    self.event_emitter.emit(
        {
            "event": EventName.TOOL_CALL,
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "tool_name": tool_name,
            "phase": "execution",
            "status": EventStatus.OK,
            "parsed_from_content": True,  # Flag for debugging
        }
    )

    # Merge base inputs with parsed arguments
    tool_inputs = {**self._base_tool_inputs(), **arguments}

    # Look up the tool definition
    tool_def = self.definition.tools_by_name.get(tool_name)
    if tool_def is None:
        tool_error = {"error": f"Unknown tool: {tool_name}"}
        self._emit_tool_result(tool_name, tool_error)
        # Add error to messages so model can see it
        self.messages.append(
            cast(
                ChatCompletionMessageParam,
                {
                    "role": "tool",
                    "tool_call_id": parsed_call.id,
                    "name": tool_name,
                    "content": json.dumps(tool_error),
                },
            )
        )
        return None  # Continue the loop

    # Execute the tool
    if self.grail_executor is not None and self.grail_dir is not None:
        tool_result_content = await self._dispatch_tool_grail(
            tool_name,
            tool_def,
            tool_inputs,
        )
    else:
        tool_result_content = json.dumps({"error": "No execution backend configured"})

    # Apply tool result event
    self._apply_tool_result_event(tool_name, tool_result_content)

    # Add to message history
    self.messages.append(
        cast(
            ChatCompletionMessageParam,
            {
                "role": "tool",
                "tool_call_id": parsed_call.id,
                "name": tool_name,
                "content": tool_result_content,
            },
        )
    )

    return None  # Continue the loop
```

### Step 2.4: Update the Main Loop

Modify the `run()` method to handle the case where `_handle_no_tool_calls` returns `None` (indicating the loop should continue):

Find this section (around line 266-267):

```python
if not tool_calls:
    return self._handle_no_tool_calls(message)
```

Replace with:

```python
if not tool_calls:
    result = await self._handle_no_tool_calls(message)
    if result is not None:
        return result
    # If None, a parsed tool was dispatched — continue the loop
    await self.context_manager.pull_hub_context()
    next_turn = self.turn_count + 1
    message = await self._call_model(phase="loop", tool_choice=self._tool_choice_for_turn(next_turn))
    continue
```

### Validation: Phase 2

```bash
# 1. Unit test the parser
python -c "
from remora.tool_parser import parse_tool_call_from_content

# Test Format 1: Direct with arguments
result = parse_tool_call_from_content('{\"name\": \"simple_tool\", \"arguments\": {\"payload\": \"test\"}}')
assert result is not None
assert result.name == 'simple_tool'
assert result.arguments == {'payload': 'test'}
print('Format 1 (direct): PASS')

# Test Format 2: Direct with parameters
result = parse_tool_call_from_content('{\"name\": \"simple_tool\", \"parameters\": {\"payload\": \"test\"}}')
assert result is not None
assert result.arguments == {'payload': 'test'}
print('Format 2 (parameters): PASS')

# Test Format 3: OpenAI array
result = parse_tool_call_from_content('{\"tool_calls\": [{\"function\": {\"name\": \"simple_tool\", \"arguments\": \"{\\\"payload\\\": \\\"test\\\"}\"}}]}')
assert result is not None
assert result.name == 'simple_tool'
print('Format 3 (OpenAI): PASS')

# Test invalid content
result = parse_tool_call_from_content('not json')
assert result is None
print('Invalid content: PASS')

print('All parser tests passed!')
"

# 2. Integration test: Run harness and check for parsed_from_content events
python scripts/functiongemma_harness.py \
    --tool-choice auto \
    --requests-per-variant 10 \
    --concurrency 1

# Look for events with "parsed_from_content": true in logs
```

**Expected Results:**
- Parser correctly handles all three JSON formats
- Tool calls in content are dispatched and executed
- Tool results appear in conversation history

---

## 4. Phase 3: Harness Configuration

**Goal:** Update harness defaults to match successful example projects.

**Files to modify:**
- `scripts/functiongemma_harness.py`

### Step 3.1: Update Default tool_choice

Find the CLI option definition (around line 274):

```python
tool_choice: str = typer.Option(
    "auto",
    help="Tool choice mode: required or auto.",
),
```

Change to:

```python
tool_choice: str = typer.Option(
    "required",
    help="Tool choice mode: required or auto. Default 'required' forces tool calls.",
),
```

### Step 3.2: Add Temperature Override

Find the runner_config creation (around line 192):

```python
runner_config = config.runner.model_copy(
    update={
        "tool_choice": tool_choice,
        "max_tokens": max_tokens,
        "include_prompt_context": False,
        "include_tool_guide": include_tool_guide,
    }
)
```

Add temperature override:

```python
runner_config = config.runner.model_copy(
    update={
        "tool_choice": tool_choice,
        "max_tokens": max_tokens,
        "temperature": 0,  # Deterministic output for harness testing
        "include_prompt_context": False,
        "include_tool_guide": include_tool_guide,
    }
)
```

### Step 3.3: Add CLI Temperature Option (Optional)

Add a new CLI option for flexibility:

```python
@app.command()
def main(
    definition_path: str = typer.Option(
        "harness/harness_subagent.yaml",
        help="Subagent definition path relative to agents_dir.",
    ),
    config_path: str | None = typer.Option(
        os.getenv("REMORA_CONFIG", None),
        help="Path to remora.yaml (defaults to repo root).",
    ),
    tool_choice: str = typer.Option(
        "required",
        help="Tool choice mode: required or auto.",
    ),
    max_tokens: int = typer.Option(256, help="Max tokens for model responses."),
    temperature: float = typer.Option(0.0, help="Sampling temperature (0 for deterministic)."),  # NEW
    concurrency: int = typer.Option(25, help="Max concurrent requests."),
    requests_per_variant: int = typer.Option(40, help="Requests per prompt."),
    include_tool_guide: bool = typer.Option(
        True, help="Include a compact tool guide in the system prompt."
    ),
) -> None:
```

Then update the runner_config:

```python
runner_config = config.runner.model_copy(
    update={
        "tool_choice": tool_choice,
        "max_tokens": max_tokens,
        "temperature": temperature,  # Use CLI value
        "include_prompt_context": False,
        "include_tool_guide": include_tool_guide,
    }
)
```

### Validation: Phase 3

```bash
# 1. Verify defaults changed
python scripts/functiongemma_harness.py --help
# Should show: --tool-choice TEXT  Tool choice mode... [default: required]
# Should show: --temperature FLOAT ... [default: 0.0]

# 2. Run with new defaults
python scripts/functiongemma_harness.py \
    --requests-per-variant 40 \
    --concurrency 10

# Expected: Tool call rate should be significantly higher than before
# Target: >90% tool call rate

# 3. Compare with old defaults
python scripts/functiongemma_harness.py \
    --tool-choice auto \
    --temperature 0.1 \
    --requests-per-variant 40 \
    --concurrency 10

# Compare tool call rates between the two runs
```

**Expected Results:**
- Default tool_choice is "required"
- Default temperature is 0
- Tool call rate improves from ~40-60% to >90%

---

## 5. Phase 4: System Prompt Improvements

**Goal:** Improve system prompts with explicit tool-calling directives.

**Files to modify:**
- `agents/harness/harness_subagent.yaml`
- `agents/docstring/docstring_subagent.yaml`
- `agents/lint/lint_subagent.yaml`
- `agents/test/test_subagent.yaml`
- `agents/sample_data/sample_data_subagent.yaml`

### Step 4.1: Define the Improved Prompt Pattern

Based on successful example projects, system prompts should follow this pattern:

```
You are a tool-calling model working on:
<task_description>[CONCRETE ROLE AND TASK]</task_description>

Respond to the conversation history by generating an appropriate tool call
that satisfies the user request. Generate only the tool call according to
the provided tool schema, do not generate anything else. Always respond
with a tool call.
```

Key elements:
1. `<task_description>` XML tags (FunctionGemma was trained with this format)
2. Explicit "Generate only the tool call"
3. Explicit "Always respond with a tool call"

### Step 4.2: Update Harness Agent

Edit `agents/harness/harness_subagent.yaml`:

```yaml
name: harness_agent
max_turns: 2

initial_context:
  system_prompt: |
    You are a tool-calling model working on:
    <task_description>You are a tool invocation tester. Given a request,
    call the appropriate function from the available tools.</task_description>

    Respond to the conversation history by generating an appropriate tool call
    that satisfies the user request. Generate only the tool call according to
    the provided tool schema, do not generate anything else. Always respond
    with a tool call.
  node_context: |
    Request:
    {{ node_text }}

tools:
  - tool_name: simple_tool
    pym: harness/tools/simple_tool.pym
    tool_description: Call this tool to echo a payload for tool-call testing.
    inputs_override:
      payload:
        description: "The payload string to echo back."

  - tool_name: submit_result
    pym: harness/tools/submit.pym
    tool_description: Submit the final harness result after calling simple_tool.
    inputs_override:
      summary:
        description: "Short summary of the harness run."
      changed_files:
        description: "List of modified files (empty for harness)."
```

### Step 4.3: Update Docstring Agent

Edit `agents/docstring/docstring_subagent.yaml`:

```yaml
name: docstring_agent
max_turns: 15

initial_context:
  system_prompt: |
    You are a tool-calling model working on:
    <task_description>You are a Python documentation maintenance tool. Given
    Python code, read the existing docstring and type hints, then write an
    appropriate docstring. If required arguments are missing, omit them from
    the function call.</task_description>

    Respond to the conversation history by generating an appropriate tool call
    that satisfies the user request. Generate only the tool call according to
    the provided tool schema, do not generate anything else. Always respond
    with a tool call.
  node_context: |
    Code to document:
    {{ node_text }}

# ... rest of tools configuration unchanged
```

### Step 4.4: Update Lint Agent

Edit `agents/lint/lint_subagent.yaml`:

```yaml
name: lint_agent
max_turns: 15

initial_context:
  system_prompt: |
    You are a tool-calling model working on:
    <task_description>You are a Python code linting tool. Given Python code,
    run the linter to find issues, then apply fixes for fixable issues.
    Track which issues have been fixed. If required arguments are missing,
    omit them from the function call.</task_description>

    Respond to the conversation history by generating an appropriate tool call
    that satisfies the user request. Generate only the tool call according to
    the provided tool schema, do not generate anything else. Always respond
    with a tool call.
  node_context: |
    Code to lint:
    {{ node_text }}

# ... rest of tools configuration unchanged
```

### Step 4.5: Update Test Agent

Edit `agents/test/test_subagent.yaml`:

```yaml
name: test_agent
max_turns: 20

initial_context:
  system_prompt: |
    You are a tool-calling model working on:
    <task_description>You are a Python test generator. Given Python code,
    analyze the function signature, check for existing tests, write new tests,
    and run them until they pass. If required arguments are missing, omit them
    from the function call.</task_description>

    Respond to the conversation history by generating an appropriate tool call
    that satisfies the user request. Generate only the tool call according to
    the provided tool schema, do not generate anything else. Always respond
    with a tool call.
  node_context: |
    Target file: {{ file_path }}
    Node: {{ node_name }} ({{ node_type }})

    {{ node_text }}

# ... rest of tools configuration unchanged
```

### Step 4.6: Update Sample Data Agent

Edit `agents/sample_data/sample_data_subagent.yaml`:

```yaml
name: sample_data_agent
max_turns: 12

initial_context:
  system_prompt: |
    You are a tool-calling model working on:
    <task_description>You are a Python fixture generator. Given Python code,
    analyze the function signature and generate appropriate fixture data.
    If required arguments are missing, omit them from the function call.</task_description>

    Respond to the conversation history by generating an appropriate tool call
    that satisfies the user request. Generate only the tool call according to
    the provided tool schema, do not generate anything else. Always respond
    with a tool call.
  node_context: |
    Code to generate fixtures for:
    {{ node_text }}

# ... rest of tools configuration unchanged
```

### Validation: Phase 4

```bash
# 1. Validate YAML syntax for all agents
python -c "
import yaml
from pathlib import Path

agents_dir = Path('agents')
for yaml_file in agents_dir.rglob('*_subagent.yaml'):
    with open(yaml_file) as f:
        try:
            data = yaml.safe_load(f)
            prompt = data.get('initial_context', {}).get('system_prompt', '')
            assert '<task_description>' in prompt, f'{yaml_file}: Missing <task_description> tag'
            assert 'Always respond with a tool call' in prompt, f'{yaml_file}: Missing tool-call directive'
            print(f'{yaml_file}: OK')
        except Exception as e:
            print(f'{yaml_file}: FAIL - {e}')
"

# 2. Run harness with new prompt
python scripts/functiongemma_harness.py \
    --requests-per-variant 40 \
    --concurrency 10

# 3. Test a production agent manually
# (Requires a Python file to lint)
# remora lint path/to/test_file.py --verbose
```

**Expected Results:**
- All YAML files pass validation
- System prompts contain `<task_description>` tags
- System prompts contain "Always respond with a tool call"

---

## 6. Phase 5: Performance Optimizations

**Goal:** Improve efficiency with prompt caching and context management.

**Files to modify:**
- `src/remora/runner.py`

### Step 5.1: Cache Static System Prompts

Add a cached prompt field to `__post_init__`:

```python
def __post_init__(self) -> None:
    # ... existing initialization ...

    # Cache the static system prompt if context is not dynamic
    self._cached_system_prompt: str | None = None
    if not self.runner_config.include_prompt_context:
        self._cached_system_prompt = self._build_system_prompt(None)
```

Update `_build_prompt_messages()` to use the cache:

```python
def _build_prompt_messages(self) -> list[ChatCompletionMessageParam]:
    """Return the full accumulated conversation history."""
    # Use cached prompt if available
    if self._cached_system_prompt is not None:
        system_content = self._cached_system_prompt
    else:
        prompt_context = self.context_manager.get_prompt_context()
        system_content = self._build_system_prompt(prompt_context)

    # Update system message in-place
    self.messages[0] = cast(
        ChatCompletionMessageParam,
        {"role": "system", "content": system_content}
    )

    return list(self.messages)
```

### Step 5.2: Add Context Length Management

Add a method to trim history if needed:

```python
def _trim_history_if_needed(self, max_messages: int = 50) -> None:
    """Trim conversation history to prevent context overflow.

    Keeps the system prompt and the most recent messages. This is a
    simple sliding window approach — more sophisticated summarization
    could be added later.

    Args:
        max_messages: Maximum number of messages to retain.
    """
    if len(self.messages) <= max_messages:
        return

    # Keep system prompt (index 0) + most recent messages
    system_message = self.messages[0]
    recent_messages = self.messages[-(max_messages - 1):]
    self.messages = [system_message] + recent_messages

    logger.debug(
        "Trimmed conversation history to %d messages",
        len(self.messages)
    )
```

Call this at the start of each turn in `run()`:

```python
async def run(self) -> AgentResult:
    """Execute the model loop until a result is produced."""
    await self.context_manager.pull_hub_context()
    message = await self._call_model(phase="model_load", tool_choice=self._tool_choice_for_turn(1))

    while self.turn_count < self.definition.max_turns:
        self.turn_count += 1
        self.context_manager.increment_turn()

        # Trim history if it's getting too long
        self._trim_history_if_needed(max_messages=40)

        # ... rest of loop unchanged
```

### Step 5.3: Improve Tool Result Parsing

Replace the fragile last-line JSON parsing in `_parse_tool_result_content()`:

```python
def _parse_tool_result_content(self, result_content: Any) -> dict[str, Any]:
    """Parse tool result content into a dict.

    Tries to parse the entire content as JSON first, then falls back
    to extracting JSON from the last non-empty line.
    """
    if isinstance(result_content, dict):
        return result_content

    if not result_content:
        return {}

    if not isinstance(result_content, str):
        return {"raw_output": result_content}

    content = result_content.strip()
    if not content:
        return {}

    # Try parsing entire content as JSON first
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return {"raw_output": data}
    except json.JSONDecodeError:
        pass

    # Fall back to last non-empty line
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return {}

    try:
        data = json.loads(lines[-1])
        if isinstance(data, dict):
            return data
        return {"raw_output": data}
    except json.JSONDecodeError:
        return {"raw_output": content}
```

### Validation: Phase 5

```bash
# 1. Test prompt caching
python -c "
# Verify cached prompt is used when include_prompt_context=False
# This requires instrumenting the runner - check logs for cache hits
print('Manual verification: Check debug logs for prompt cache usage')
"

# 2. Test history trimming with a long conversation
# Create a test that runs many turns and verify trimming occurs
python -c "
# Simulate a runner with many messages
messages = [{'role': 'system', 'content': 'test'}]
for i in range(60):
    messages.append({'role': 'user', 'content': f'message {i}'})

# After trimming to 40, should have 40 messages
# Verify system message is preserved
print(f'Before trim: {len(messages)} messages')

# Simulate trim
system = messages[0]
recent = messages[-39:]
trimmed = [system] + recent
print(f'After trim: {len(trimmed)} messages')
assert trimmed[0]['role'] == 'system'
print('History trimming: PASS')
"

# 3. Run harness and check performance
time python scripts/functiongemma_harness.py \
    --requests-per-variant 40 \
    --concurrency 10
```

**Expected Results:**
- System prompt built only once when `include_prompt_context=False`
- Long conversations are trimmed without losing context
- Tool result parsing handles edge cases gracefully

---

## 7. Phase 6: Production Agent Validation

**Goal:** Verify all production agents work correctly with the fixes.

### Step 6.1: Create Test Files

Create test fixtures for each agent type:

```bash
# Create a test directory
mkdir -p tests/integration/agent_fixtures

# Create a simple Python function to test
cat > tests/integration/agent_fixtures/sample_function.py << 'EOF'
def calculate_sum(a: int, b: int) -> int:
    """Add two numbers."""
    result = a + b
    return result


def unused_import_example():
    import os  # F401: unused import
    x = 1
    return x
EOF
```

### Step 6.2: Test Each Production Agent

```bash
# Test lint agent (requires ruff installed)
echo "=== Testing Lint Agent ==="
python -m remora.cli lint tests/integration/agent_fixtures/sample_function.py --verbose

# Expected output:
# - Agent runs linter
# - Identifies F401 (unused import)
# - Attempts to fix
# - Submits result with issues_fixed count

# Test docstring agent
echo "=== Testing Docstring Agent ==="
python -m remora.cli docstring tests/integration/agent_fixtures/sample_function.py --verbose

# Expected output:
# - Agent reads existing docstring
# - Reads type hints
# - Writes improved docstring
# - Submits result

# Test test agent (requires pytest installed)
echo "=== Testing Test Agent ==="
python -m remora.cli test tests/integration/agent_fixtures/sample_function.py --verbose

# Expected output:
# - Agent analyzes function signature
# - Writes test file
# - Runs pytest
# - Iterates if tests fail
# - Submits result with tests_passing count
```

### Step 6.3: Verify Multi-Turn Behavior

The key verification is that agents maintain context across turns:

```bash
# Enable detailed logging
export REMORA_LOG_LEVEL=DEBUG

# Run lint agent and check logs for message accumulation
python -m remora.cli lint tests/integration/agent_fixtures/sample_function.py --verbose 2>&1 | tee lint_test.log

# Check the log for:
# 1. Message count increasing each turn
# 2. Tool results appearing in subsequent prompts
# 3. No "Turn limit exceeded" errors for simple tasks

grep -E "(messages=|tool_result|Turn)" lint_test.log
```

### Step 6.4: Automated Validation Script

Create `scripts/validate_agents.py`:

```python
"""Validate all production agents after refactoring."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from remora.config import load_config
from remora.subagent import load_subagent_definition


async def validate_agent(agent_name: str, agents_dir: Path) -> bool:
    """Validate an agent loads correctly and has proper configuration."""
    try:
        yaml_path = agents_dir / agent_name / f"{agent_name}_subagent.yaml"
        if not yaml_path.exists():
            print(f"  {agent_name}: SKIP (no yaml file)")
            return True

        definition = load_subagent_definition(
            Path(f"{agent_name}/{agent_name}_subagent.yaml"),
            agents_dir
        )

        # Check system prompt
        prompt = definition.initial_context.system_prompt
        checks = [
            ("<task_description>", "<task_description> tag"),
            ("Always respond with a tool call", "tool-call directive"),
        ]

        for pattern, name in checks:
            if pattern not in prompt:
                print(f"  {agent_name}: FAIL - Missing {name}")
                return False

        # Check tools
        if len(definition.tools) < 2:
            print(f"  {agent_name}: FAIL - Need at least 2 tools (including submit_result)")
            return False

        # Check submit_result exists
        tool_names = [t.tool_name for t in definition.tools]
        if "submit_result" not in tool_names:
            print(f"  {agent_name}: FAIL - Missing submit_result tool")
            return False

        print(f"  {agent_name}: PASS ({len(definition.tools)} tools, max_turns={definition.max_turns})")
        return True

    except Exception as e:
        print(f"  {agent_name}: FAIL - {e}")
        return False


async def main():
    print("Validating production agents...\n")

    config = load_config(None)
    agents_dir = Path(config.agents_dir)

    agents = ["harness", "docstring", "lint", "test", "sample_data"]
    results = []

    for agent in agents:
        result = await validate_agent(agent, agents_dir)
        results.append(result)

    print()
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"All {total} agents validated successfully!")
        return 0
    else:
        print(f"Validation failed: {passed}/{total} agents passed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

Run validation:

```bash
python scripts/validate_agents.py
```

---

## Appendix A: Agent-Specific Improvements

Beyond the core fixes, each production agent can benefit from targeted improvements.

### A.1 Harness Agent

**Current Status:** Minimal test agent, works with fixes.

**No additional changes needed.**

---

### A.2 Docstring Agent

**Current Issues:**
- `write_docstring.pym` has unused `style` parameter
- No validation of docstring format before writing

**Recommended Improvements:**

#### A.2.1 Fix Unused Style Parameter

In `agents/docstring/tools/write_docstring.pym`, the `style` input is declared but unused:

```python
style: str = Input("style")
# ...
_ = style  # Currently unused
```

Either implement style-aware formatting or remove the parameter. To implement:

```python
style: str = Input("style", default="google")

def _format_docstring(content: str, style_name: str) -> str:
    """Format docstring according to style guide."""
    if style_name == "numpy":
        # NumPy style formatting
        return _format_numpy(content)
    elif style_name == "sphinx":
        # Sphinx style formatting
        return _format_sphinx(content)
    else:
        # Default: Google style
        return _format_google(content)
```

#### A.2.2 Add Docstring Validation

Add a validation step before writing:

```python
def _validate_docstring(docstring: str) -> tuple[bool, str | None]:
    """Validate docstring before writing."""
    if not docstring or not docstring.strip():
        return False, "Docstring is empty"

    # Check for common issues
    if '"""' in docstring:
        return False, "Docstring contains unescaped triple quotes"

    return True, None
```

---

### A.3 Lint Agent

**Current Status:** Has custom JSON parser, most robust.

**Recommended Improvements:**

#### A.3.1 Improve Tool Descriptions

Update `inputs_override` in `agents/lint/lint_subagent.yaml`:

```yaml
tools:
  - tool_name: run_linter
    pym: lint/tools/run_linter.pym
    tool_description: Run ruff linter on the Python code and return a list of issues found with their codes and line numbers.
    inputs_override:
      check_only:
        description: "If true, only check for issues without applying fixes. Default is true."

  - tool_name: apply_fix
    pym: lint/tools/apply_fix.pym
    tool_description: Apply an automatic fix for a specific lint issue by its code and line number.
    inputs_override:
      issue_code:
        description: "The ruff issue code to fix, e.g. F401 for unused import or E501 for line too long."
      line_number:
        description: "The line number where the issue occurs (1-indexed)."
```

#### A.3.2 Add Issue Tracking to Knowledge Delta

Update `run_linter.pym` to return better `knowledge_delta`:

```python
result = {
    "result": {
        "issues": issues,
        "total": len(issues),
        "fixable_count": fixable_count,
    },
    "summary": f"Found {len(issues)} issues ({fixable_count} fixable)",
    "knowledge_delta": {
        "lint_errors_total": len(issues),
        "lint_errors_fixable": fixable_count,
        "lint_error_codes": list(set(i["code"] for i in issues)),
    },
    "outcome": "success" if len(issues) == 0 else "partial",
}
```

---

### A.4 Test Agent

**Current Status:** Most complex agent (20 turns), has custom XML parser.

**Recommended Improvements:**

#### A.4.1 Improve Test Iteration Tracking

Update `run_tests.pym` to track iteration progress:

```python
result = {
    "result": {
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_errors": errors,
        "failure_messages": failure_messages[:5],  # Truncate for context
    },
    "summary": f"Tests: {passed} passed, {failed} failed, {errors} errors",
    "knowledge_delta": {
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_errors": errors,
        "tests_total": passed + failed + errors,
        "all_passing": failed == 0 and errors == 0,
    },
    "outcome": "success" if (failed == 0 and errors == 0) else "partial",
}
```

#### A.4.2 Add Test File Existence Check

In `write_test_file.pym`, check if overwriting:

```python
@external
async def file_exists(path: str) -> bool:
    """Check if a file or directory exists."""
    ...

# Before writing
test_path = # ... constructed path
exists = await file_exists(path=test_path)

result = {
    "result": {"path": test_path, "overwritten": exists},
    "summary": f"{'Overwrote' if exists else 'Created'} {test_path}",
    "knowledge_delta": {"test_file_path": test_path},
    "outcome": "success",
}
```

---

### A.5 Sample Data Agent

**Current Status:** Simplest multi-turn agent, has custom JSON/YAML serializers.

**Recommended Improvements:**

#### A.5.1 Improve Fixture Quality

Update `analyze_signature.pym` to provide better type information:

```python
result = {
    "result": {
        "function_name": func_name,
        "parameters": parameters,  # List of {name, type, default, has_default}
        "return_type": return_type,
    },
    "summary": f"Function {func_name} has {len(parameters)} parameters",
    "knowledge_delta": {
        "function_name": func_name,
        "parameter_count": len(parameters),
        "parameter_names": [p["name"] for p in parameters],
        "parameter_types": {p["name"]: p["type"] for p in parameters},
    },
    "outcome": "success",
}
```

#### A.5.2 Add Format Validation

In `write_fixture_file.pym`, validate the format before writing:

```python
format_input: str = Input("format_input", default="json")

# Validate format
if format_input not in ("json", "yaml"):
    result = {
        "result": None,
        "summary": f"Invalid format: {format_input}. Use 'json' or 'yaml'.",
        "knowledge_delta": {},
        "outcome": "error",
        "error": f"Invalid format: {format_input}",
    }
else:
    # ... proceed with writing
```

---

## Appendix B: Testing Commands

### Quick Validation

```bash
# Validate all agent YAML files
python scripts/validate_agents.py

# Run harness with new defaults
python scripts/functiongemma_harness.py \
    --requests-per-variant 40 \
    --concurrency 10

# Check tool call rate (should be >90%)
```

### Unit Tests

```bash
# Run existing unit tests
pytest tests/unit/ -v

# Test the new tool parser
pytest tests/unit/test_tool_parser.py -v
```

### Integration Tests

```bash
# Full integration test with a real file
python -m remora.cli lint tests/integration/agent_fixtures/sample_function.py --verbose

# Test with different agents
python -m remora.cli docstring tests/integration/agent_fixtures/sample_function.py --verbose
python -m remora.cli test tests/integration/agent_fixtures/sample_function.py --verbose
```

### Performance Comparison

```bash
# Before fixes (use old branch or stash changes)
git stash
time python scripts/functiongemma_harness.py --requests-per-variant 100
git stash pop

# After fixes
time python scripts/functiongemma_harness.py --requests-per-variant 100

# Compare:
# - Tool call rates
# - Execution time
# - Error counts
```

---

## Appendix C: Rollback Procedures

If issues occur, rollback changes in reverse phase order.

### Rollback Phase 5 (Performance)

```bash
# Revert runner.py performance changes
git checkout HEAD~1 -- src/remora/runner.py

# Or manually:
# - Remove _trim_history_if_needed()
# - Remove _cached_system_prompt
# - Restore original _parse_tool_result_content()
```

### Rollback Phase 4 (Prompts)

```bash
# Revert all agent YAML files
git checkout HEAD~1 -- agents/*/
```

### Rollback Phase 3 (Harness Config)

```bash
# Revert harness script
git checkout HEAD~1 -- scripts/functiongemma_harness.py
```

### Rollback Phase 2 (JSON Parsing)

```bash
# Remove tool_parser.py
rm src/remora/tool_parser.py

# Revert runner.py changes
git checkout HEAD~1 -- src/remora/runner.py
```

### Rollback Phase 1 (Core Fix)

```bash
# Revert to original _build_prompt_messages()
git checkout HEAD~1 -- src/remora/runner.py
```

### Full Rollback

```bash
# Revert all changes
git checkout HEAD~5 -- .

# Or reset to a known good commit
git reset --hard <commit-hash>
```

---

## Summary Checklist

Complete each phase in order, validating before moving to the next:

- [ ] **Phase 1:** Fix `_build_prompt_messages()` to send full history
  - [ ] Modified `runner.py`
  - [ ] Verified message counts increase each turn
  - [ ] No "Turn limit exceeded" on simple tasks

- [ ] **Phase 2:** Add JSON fallback parsing
  - [ ] Created `tool_parser.py`
  - [ ] Modified `runner.py` to use parser
  - [ ] Verified JSON tool calls are dispatched

- [ ] **Phase 3:** Update harness configuration
  - [ ] Changed default `tool_choice` to "required"
  - [ ] Changed default `temperature` to 0
  - [ ] Tool call rate >90%

- [ ] **Phase 4:** Improve system prompts
  - [ ] All agents have `<task_description>` tags
  - [ ] All agents have "Always respond with a tool call"
  - [ ] YAML validation passes

- [ ] **Phase 5:** Performance optimizations
  - [ ] Added prompt caching
  - [ ] Added history trimming
  - [ ] Improved tool result parsing

- [ ] **Phase 6:** Production agent validation
  - [ ] Lint agent completes multi-turn workflow
  - [ ] Docstring agent completes multi-turn workflow
  - [ ] Test agent completes multi-turn workflow
  - [ ] Sample data agent completes multi-turn workflow

---

## Final Notes

### Key Files Changed

| File | Phase | Changes |
|------|-------|---------|
| `src/remora/runner.py` | 1, 2, 5 | Core fixes, JSON parsing, performance |
| `src/remora/tool_parser.py` | 2 | New file for JSON parsing |
| `scripts/functiongemma_harness.py` | 3 | Default configuration |
| `agents/harness/harness_subagent.yaml` | 4 | Improved prompt |
| `agents/docstring/docstring_subagent.yaml` | 4 | Improved prompt |
| `agents/lint/lint_subagent.yaml` | 4 | Improved prompt |
| `agents/test/test_subagent.yaml` | 4 | Improved prompt |
| `agents/sample_data/sample_data_subagent.yaml` | 4 | Improved prompt |

### Testing Priority

1. **Critical:** Phase 1 (conversation history) — affects all agents
2. **High:** Phase 2 (JSON parsing) — improves reliability
3. **High:** Phase 3 (harness config) — improves benchmarks
4. **Medium:** Phase 4 (prompts) — improves behavior
5. **Low:** Phase 5 (performance) — optimization only

### Support

If you encounter issues:

1. Check the validation steps for each phase
2. Enable debug logging: `export REMORA_LOG_LEVEL=DEBUG`
3. Check `.remora_cache/llm_conversations.log` for full transcripts
4. Compare with the example projects in `.context/functiongemma_examples/`
