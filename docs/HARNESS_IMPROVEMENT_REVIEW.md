# Remora FunctionGemma Harness: Comprehensive Improvement Review

## Executive Summary

This document provides a detailed technical analysis of why the Remora FunctionGemma harness is producing poor tool-call rates compared to the reference implementations (distil-SHELLper and distil-smart-home). The analysis identifies **five critical gaps** and **seven secondary issues** that, when addressed, should bring the harness behavior in line with the successful example projects.

> **Note:** This review was created after verifying the junior dev's MODEL_INTERACTION_REVIEW.md against actual source code. Three errors in that document have been corrected here and in the original file. See [Appendix D: Review Verification](#appendix-d-review-verification) for details.

---

## Part 1: Reference Implementation Analysis

### 1.1 distil-SHELLper (Multi-Turn Bash Tool Calling)

**Architecture Overview:**
- OpenAI-compatible client pointing to local Ollama/vLLM server
- Full tool schema passed on every request
- Maintains growing conversation history across turns

**Key Implementation Patterns:**

#### Conversation History Management
```python
# From filesystem_demo.py
conversation_history: List[Dict[str, str]] = []

# User turn
conversation_history.append({"role": "user", "content": user_input})

# Model invocation (FULL history sent)
llm_response = client.invoke(conversation_history)

# After successful tool call
conversation_history.append({
    "role": "assistant",
    "content": "",
    "tool_calls": [{
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": json.dumps(arguments)
        }
    }]
})
```

**Critical Observation:** The history grows with each turn and is sent in full to the model every time. Failed messages are removed from history to avoid confusing the model.

#### Tool-Call Parsing (Two-Stage Architecture)

**Stage 1: Client Return (client.py:50-51)**
```python
# Note: Returns CONTENT first, tool_calls as FALLBACK
return response.content if response.content and len(response.content.strip('\n')) else response.tool_calls[0]
```

**Stage 2: Format Parsing (parsing.py - parse_llm_response())**
```python
# Path 1: OpenAI tool_call object (when Stage 1 returns tool_calls[0])
if not isinstance(llm_response, str):
    function_name = llm_response.function.name
    arguments = json.loads(llm_response.function.arguments)

# Path 2: Direct JSON format (when Stage 1 returns content)
elif isinstance(llm_response, str):
    parsed = json.loads(llm_response)
    if "name" in parsed and "parameters" in parsed:
        function_name = parsed["name"]
        arguments = parsed["parameters"]

# Path 3: OpenAI JSON response format
    elif "tool_calls" in parsed:
        tool_call = parsed["tool_calls"][0]
        function_name = tool_call["function"]["name"]
        arguments = json.loads(tool_call["function"]["arguments"])
```

**Critical Observations:**
1. SHELLper prefers text content over structured tool_calls (opposite of smart-home)
2. Multiple parsing paths in Stage 2 ensure robust extraction regardless of format
3. The separation of concerns (client vs. parser) is a clean architecture pattern

#### System Prompt
```python
# From client.py
"You are a tool-calling model working on:
<task_description>{self.task_description}</task_description>

Respond to the conversation history by generating an appropriate tool call
that satisfies the user request. Generate only the tool call according to the
provided tool schema, do not generate anything else. Always respond with a
tool call."
```

**Critical Observation:** Explicit instruction to "Always respond with a tool call" and "do not generate anything else."

#### Configuration
| Setting | Value |
|---------|-------|
| Temperature | **0** |
| tool_choice | **Not set** (relies on robust parsing instead) |
| reasoning_effort | "none" |
| Response preference | Content first, tool_calls as fallback |

---

### 1.2 distil-smart-home (Deterministic Orchestrator)

**Architecture Overview:**
- Six predefined smart-home tool schemas
- `tool_choice="required"` enforces tool calls
- Sophisticated slot elicitation for missing arguments

**Key Implementation Patterns:**

#### Model Invocation
```python
# From orchestrator.py - SLMClient.invoke()
chat_response = self.client.chat.completions.create(
    model=self.model_name,
    messages=[SYSTEM_PROMPT] + conversation_history,  # FULL history
    temperature=0,
    tools=TOOLS,
    tool_choice="required",  # FORCES tool call
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```

**Critical Observations:**
1. `tool_choice="required"` - The model MUST return a tool call
2. Full conversation history sent every turn
3. Temperature set to 0 for deterministic output
4. Thinking disabled for faster inference

#### Tool-Call Parsing (Dual-Path Fallback)
```python
# From orchestrator.py - SLMClient.invoke()

# Path A: Proper tool_calls field
if response.tool_calls:
    fn = response.tool_calls[0].function
    arguments = fn.arguments
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    return {"name": fn.name, "arguments": arguments}

# Path B: JSON in content field (fallback)
if response.content:
    try:
        parsed = json.loads(response.content.strip())
        if "name" in parsed:
            args = parsed.get("arguments", parsed.get("parameters", {}))
            if isinstance(args, str):
                args = json.loads(args)
            return {"name": parsed["name"], "arguments": args}
    except (json.JSONDecodeError, KeyError):
        pass
```

**Critical Observation:** Even with `tool_choice="required"`, the implementation includes a fallback to parse JSON from the content field. This handles edge cases where the server's tool parser fails.

#### System Prompt
```python
# From orchestrator.py
SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are a tool-calling model working on:\n"
        "<task_description>You are an on-device smart home controller. "
        "Given a natural language command from the user, call the appropriate "
        "smart home function. If the user does not specify a required value "
        "(e.g. which room or what temperature), omit that parameter from the "
        "function call. Maintain context across conversation turns to resolve "
        "pronouns and sequential commands.</task_description>\n\n"
        "Respond to the conversation history by generating an appropriate tool call that "
        "satisfies the user request. Generate only the tool call according to the provided "
        "tool schema, do not generate anything else. Always respond with a tool call.\n\n"
    ),
}
```

**Critical Observations:**
1. Domain context wrapped in `<task_description>` tags
2. Explicit instruction for handling missing arguments
3. Instruction to maintain context across turns
4. "Always respond with a tool call" directive

#### Configuration
| Setting | Value |
|---------|-------|
| Temperature | **0** |
| tool_choice | **"required"** |
| thinking | disabled |

---

## Part 2: Current Remora Harness Analysis

### 2.1 Architecture Overview

The Remora harness consists of:
- `scripts/functiongemma_harness.py` - High-concurrency test runner
- `src/remora/runner.py` - `FunctionGemmaRunner` class handling the model loop
- `agents/harness/harness_subagent.yaml` - Agent definition with tools
- `server/tool_chat_template_functiongemma.jinja` - vLLM chat template

### 2.2 Current Message Flow

```
1. Runner initialized with system prompt + initial user message
2. self.messages = [system_prompt, user_message]
3. _call_model() invoked
   └─> _build_prompt_messages() called
       └─> Returns FRESH [system_prompt, user_message] (NOT self.messages!)
4. Model response received
5. Response appended to self.messages
6. Tool calls executed, results appended to self.messages
7. Next turn: _call_model() again
   └─> _build_prompt_messages() returns FRESH [system_prompt, user_message]
       └─> Previous tool calls and results NOT sent to model!
```

### 2.3 Critical Code Analysis

#### The Core Bug: `_build_prompt_messages()` (runner.py:246-254)

```python
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

**Problem:** This method rebuilds messages from scratch every turn, returning only `[system, initial_user]`. The accumulated `self.messages` list (which contains assistant responses and tool results) is never used in API calls.

#### Where Messages Are Used (runner.py:358-366)

```python
async def _attempt() -> Any:
    return await self._http_client.chat.completions.create(
        model=self._model_target,
        messages=cast(list[ChatCompletionMessageParam], prompt_messages),  # <-- Only [system, user]
        tools=cast(list[ChatCompletionToolParam], tools_payload),
        tool_choice=cast(Any, tool_choice),
        max_tokens=self.runner_config.max_tokens,
        temperature=self.runner_config.temperature,
    )
```

#### Where History Is Accumulated But Not Sent (runner.py:264-287)

```python
# Assistant response is appended...
self.messages.append(self._coerce_message_param(message))

# Tool results are appended...
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
# But self.messages is NEVER sent to the API!
```

#### Missing JSON Fallback Parser (runner.py:427-452)

```python
def _handle_no_tool_calls(self, message: ChatCompletionMessage) -> AgentResult:
    if self.runner_config.tool_choice == "required":
        raise AgentError(...)
    content = message.content or ""
    if content:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return self._build_submit_result(parsed)  # <-- Only treats as submit_result!
    # ...
```

**Problem:** JSON in content is only treated as a `submit_result` payload. There's no fallback to parse `{"name": "tool_name", "arguments": {...}}` as an actual tool call.

### 2.4 Current Configuration

| Setting | Remora Default | distil-SHELLper | distil-smart-home |
|---------|----------------|-----------------|-------------------|
| Temperature | **0.1** | **0** | **0** |
| tool_choice | **"auto"** | **Not set** | **"required"** |
| History sent | **Initial only** | **Full history** | **Full history** |
| JSON fallback | **submit_result only** | **3-path parsing** | **2-path parsing** |
| Response preference | N/A | Content first | tool_calls first |

### 2.5 Current System Prompt

```yaml
# From harness_subagent.yaml
system_prompt: |
  You are a tool invocation tester. Given a request, call the appropriate function. Always call a function.
```

**Problems:**
1. No `<task_description>` tags
2. No explicit guidance on response format
3. No instruction to "generate only the tool call"
4. Minimal context about the testing domain

---

## Part 3: Identified Gaps

### Critical Gaps (High Impact)

#### Gap 1: Conversation History Not Sent to Model

**Severity:** CRITICAL

**Current Behavior:**
Every model call receives only `[system_prompt, initial_user_message]`. Previous assistant responses and tool results are stored in `self.messages` but never sent.

**Expected Behavior:**
Full conversation history should be sent on every turn, allowing the model to see:
- Its previous tool calls
- Results from executed tools
- Context from earlier turns

**Impact:**
- Multi-turn tool calling is broken
- Model cannot learn from tool execution results
- Model cannot maintain context across turns

**Reference Implementation:**
Both example projects send `[SYSTEM_PROMPT] + conversation_history` on every call.

---

#### Gap 2: tool_choice Defaults to "auto"

**Severity:** HIGH (not critical)

**Current Behavior:**
`tool_choice="auto"` in both config and harness CLI default.

**Expected Behavior:**
Either:
- `tool_choice="required"` forces the model to always return a tool call (smart-home approach), OR
- Robust JSON parsing to handle tool calls in content (SHELLper approach)

**Impact:**
- Model may return plain text instead of tool calls
- Without robust parsing, these responses are lost
- Higher variance in behavior

**Reference Implementation:**
- distil-smart-home uses `tool_choice="required"` explicitly
- distil-SHELLper does **not** set `tool_choice` but has robust multi-format parsing

**Recommendation:** For the harness, use `tool_choice="required"`. However, robust parsing (Gap 3) is equally important and provides resilience even when tool_choice is set.

---

#### Gap 3: No JSON Tool-Call Fallback

**Severity:** HIGH

**Current Behavior:**
If `message.tool_calls` is empty, JSON in content is only parsed as `submit_result`.

**Expected Behavior:**
JSON content should be parsed for standard tool call formats:
- `{"name": "...", "arguments": {...}}`
- `{"name": "...", "parameters": {...}}`
- `{"tool_calls": [...]}`

**Impact:**
- Tool calls in JSON format are missed
- Model's tool call attempts go unrecognized
- Lower effective tool-call rate

**Reference Implementation:**
Both examples implement multi-path JSON parsing as fallback.

---

#### Gap 4: Temperature Too High

**Severity:** HIGH

**Current Behavior:**
`temperature=0.1` allows some randomness.

**Expected Behavior:**
`temperature=0` for deterministic, consistent tool calls.

**Impact:**
- Non-deterministic behavior across runs
- Occasional malformed outputs
- Harder to debug and reproduce issues

**Reference Implementation:**
Both examples use `temperature=0`.

---

#### Gap 5: System Prompt Lacks Explicit Directives

**Severity:** MEDIUM-HIGH

**Current Behavior:**
```
You are a tool invocation tester. Given a request, call the appropriate function. Always call a function.
```

**Expected Behavior:**
```
You are a tool-calling model working on:
<task_description>You are a tool invocation tester. Given a request, call
the appropriate function from the available tools.</task_description>

Respond to the conversation history by generating an appropriate tool call
that satisfies the user request. Generate only the tool call according to
the provided tool schema, do not generate anything else. Always respond
with a tool call.
```

**Impact:**
- Model may not understand expected output format
- May generate explanatory text instead of tool calls
- Weaker instruction following

**Reference Implementation:**
Both examples include explicit formatting instructions and `<task_description>` tags.

---

### Secondary Issues (Medium Impact)

#### Issue 1: System Prompt Rebuilt Every Turn

**Current Behavior:**
`_build_system_prompt()` is called on every `_call_model()`, even though the prompt is mostly static.

**Impact:**
- Unnecessary string operations
- Tool guide regenerated repeatedly
- Minor performance overhead

**Recommendation:**
Cache the system prompt after first build, only rebuild if `include_prompt_context=True`.

---

#### Issue 2: No Argument Validation Before Dispatch

**Current Behavior:**
Tool arguments are parsed and passed directly to Grail scripts without schema validation.

**Impact:**
- Invalid arguments cause failures in child processes
- Errors are harder to diagnose
- No opportunity for early rejection

**Recommendation:**
Validate arguments against the tool schema before dispatch.

---

#### Issue 3: Tool Result Parsing Relies on Last Line

**Current Behavior:**
```python
# runner.py:471-476
lines = [line for line in result_content.splitlines() if line.strip()]
payload = lines[-1]  # Takes LAST line as JSON
data = json.loads(payload)
```

**Impact:**
- Fragile if tool output has trailing text
- May fail on multi-line outputs

**Recommendation:**
Try parsing the entire content first, fall back to last line.

---

#### Issue 4: Missing Tool Call ID Handling

**Current Behavior:**
```python
tool_call_id = getattr(tool_call, "id", None) or _missing_identifier("tool-call")
```

**Impact:**
- Generated UUIDs break tool result pairing in the chat template
- May cause issues with vLLM's tool parser

**Recommendation:**
Log a warning when ID is missing; ensure the generated ID format is compatible.

---

#### Issue 5: No Context Length Management

**Current Behavior:**
No mechanism to trim conversation history if it exceeds the model's context window (32768 tokens for FunctionGemma).

**Impact:**
- Long conversations may hit context limits
- Potential API errors or truncated prompts

**Recommendation:**
Implement a sliding window or summarization strategy.

---

#### Issue 6: Error Recovery Not Explicit

**Current Behavior:**
Tool errors are added to context_manager but not explicitly communicated in the next prompt (unless `include_prompt_context=True`).

**Impact:**
- Model may retry failed tools without understanding the failure
- No structured error feedback

**Recommendation:**
Include tool error information in the tool result message sent to the model.

---

#### Issue 7: Harness-Specific vs. Core Defaults

**Current Behavior:**
Harness uses the same defaults as the core runner (`temperature=0.1`, `tool_choice="auto"`).

**Impact:**
- Harness testing doesn't match optimal tool-calling configuration
- Results don't reflect best-case performance

**Recommendation:**
Override harness defaults to match example projects: `temperature=0`, `tool_choice="required"`.

---

## Part 4: Recommended Changes

### Priority 1: Critical Fixes (Immediate)

#### 1.1 Send Full Conversation History

**File:** `src/remora/runner.py`

**Change:** Replace `_build_prompt_messages()` to return `self.messages` instead of rebuilding fresh.

**Approach A (Simple):**
```python
def _build_prompt_messages(self) -> list[ChatCompletionMessageParam]:
    # Update system message with current context if needed
    if self.runner_config.include_prompt_context:
        prompt_context = self.context_manager.get_prompt_context()
        self.messages[0] = {"role": "system", "content": self._build_system_prompt(prompt_context)}
    return self.messages
```

**Approach B (Defensive):**
```python
def _build_prompt_messages(self) -> list[ChatCompletionMessageParam]:
    # Always return the full accumulated history
    # Update system prompt in-place if context changes
    system_prompt = self._build_system_prompt(
        self.context_manager.get_prompt_context() if self.runner_config.include_prompt_context else None
    )
    self.messages[0] = cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt})
    return list(self.messages)  # Return copy to prevent mutation
```

---

#### 1.2 Force Tool Calls in Harness (Recommended)

**File:** `scripts/functiongemma_harness.py`

**Change:** Default `tool_choice` to `"required"`.

```python
# Line 274
tool_choice: str = typer.Option(
    "required",  # Changed from "auto"
    help="Tool choice mode: required or auto.",
),
```

**Note:** distil-SHELLper works without `tool_choice="required"` by relying on robust parsing. However, for a harness where we want maximum tool-call rate, forcing tool calls is the simpler approach. The JSON fallback (1.3) provides resilience even with `tool_choice="required"`.

---

#### 1.3 Add JSON Tool-Call Fallback

**File:** `src/remora/runner.py`

**Change:** Modify `_handle_no_tool_calls()` to parse JSON tool calls, not just `submit_result`.

**Architecture Note:** Consider following SHELLper's two-stage pattern by extracting parsing logic into a separate function or module. This improves testability and separation of concerns.

```python
def _handle_no_tool_calls(self, message: ChatCompletionMessage) -> AgentResult | None:
    if self.runner_config.tool_choice == "required":
        raise AgentError(...)

    content = message.content or ""
    if not content:
        return self._build_fallback_result("")

    # Try to parse as JSON tool call
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return self._build_fallback_result(content)

    if not isinstance(parsed, dict):
        return self._build_fallback_result(content)

    # Check for tool call format
    if "name" in parsed:
        tool_name = parsed["name"]
        arguments = parsed.get("arguments", parsed.get("parameters", {}))
        if isinstance(arguments, str):
            arguments = json.loads(arguments)

        if tool_name == SUBMIT_RESULT_TOOL:
            return self._build_submit_result(arguments)

        # Synthesize a tool call and dispatch
        # (Requires refactoring _dispatch_tool to accept synthetic calls)
        return await self._dispatch_synthetic_tool(tool_name, arguments)

    # Check for tool_calls array format
    if "tool_calls" in parsed and parsed["tool_calls"]:
        tool_call = parsed["tool_calls"][0]
        tool_name = tool_call.get("function", {}).get("name")
        arguments = tool_call.get("function", {}).get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)

        if tool_name == SUBMIT_RESULT_TOOL:
            return self._build_submit_result(arguments)

        return await self._dispatch_synthetic_tool(tool_name, arguments)

    return self._build_submit_result(parsed)
```

---

#### 1.4 Set Temperature to Zero for Harness

**File:** `scripts/functiongemma_harness.py`

**Change:** Override temperature in runner_config.

```python
# Line 192-198
runner_config = config.runner.model_copy(
    update={
        "tool_choice": tool_choice,
        "max_tokens": max_tokens,
        "temperature": 0,  # Add this line
        "include_prompt_context": False,
        "include_tool_guide": include_tool_guide,
    }
)
```

---

### Priority 2: Important Improvements

#### 2.1 Improve System Prompt

**File:** `agents/harness/harness_subagent.yaml`

**Change:** Expand system prompt with explicit directives.

```yaml
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
```

---

#### 2.2 Cache System Prompt

**File:** `src/remora/runner.py`

**Change:** Avoid rebuilding static prompts.

```python
def __post_init__(self) -> None:
    # ... existing code ...
    self._cached_system_prompt: str | None = None
    if not self.runner_config.include_prompt_context:
        # Cache the static system prompt once
        self._cached_system_prompt = self._build_system_prompt(None)

def _build_prompt_messages(self) -> list[ChatCompletionMessageParam]:
    if self._cached_system_prompt is not None:
        system_content = self._cached_system_prompt
    else:
        prompt_context = self.context_manager.get_prompt_context()
        system_content = self._build_system_prompt(prompt_context)

    self.messages[0] = {"role": "system", "content": system_content}
    return list(self.messages)
```

---

### Priority 3: Nice-to-Have Enhancements

#### 3.1 Add Argument Validation

```python
def _validate_tool_arguments(self, tool_name: str, arguments: dict) -> tuple[bool, str | None]:
    tool_def = self.definition.tools_by_name.get(tool_name)
    if not tool_def:
        return False, f"Unknown tool: {tool_name}"

    schema = tool_def.parameters
    required = schema.get("required", [])

    for req_arg in required:
        if req_arg not in arguments:
            return False, f"Missing required argument: {req_arg}"

    return True, None
```

---

#### 3.2 Context Length Management

```python
def _trim_history_if_needed(self, max_messages: int = 50) -> None:
    if len(self.messages) > max_messages:
        # Keep system prompt + last N messages
        system = self.messages[0]
        recent = self.messages[-(max_messages - 1):]
        self.messages = [system] + recent
```

---

## Part 5: Verification Plan

### Step 1: Baseline Measurement

Run the current harness and record tool-call rates:
```bash
python scripts/functiongemma_harness.py \
    --tool-choice auto \
    --requests-per-variant 100
```

### Step 2: Apply Critical Fixes

1. Fix `_build_prompt_messages()` to send full history
2. Set `tool_choice="required"` in harness default
3. Add JSON fallback parsing
4. Set `temperature=0` in harness

### Step 3: Post-Fix Measurement

```bash
python scripts/functiongemma_harness.py \
    --tool-choice required \
    --requests-per-variant 100
```

### Step 4: Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| Tool call rate | ~40-60% | ~95%+ |
| OK responses | Variable | Consistent |
| Errors | Frequent | Rare |

---

## Part 6: Summary of Changes

### Files to Modify

| File | Changes |
|------|---------|
| `src/remora/runner.py` | Fix `_build_prompt_messages()`, add JSON fallback, cache system prompt |
| `scripts/functiongemma_harness.py` | Default `tool_choice="required"`, `temperature=0` |
| `agents/harness/harness_subagent.yaml` | Expand system prompt with explicit directives |

### Configuration Changes

| Setting | Before | After |
|---------|--------|-------|
| runner.tool_choice | auto | auto (unchanged for non-harness) |
| harness tool_choice | auto | required |
| harness temperature | 0.1 | 0 |

### Behavioral Changes

| Behavior | Before | After |
|----------|--------|-------|
| History sent | Initial only | Full history |
| Tool call parsing | tool_calls field only | tool_calls + JSON fallback |
| System prompt | Minimal | Explicit directives |

---

## Appendix A: Chat Template Analysis

The vLLM chat template (`tool_chat_template_functiongemma.jinja`) correctly handles:
- System messages with tool listings
- User messages
- Assistant messages with tool_calls
- Tool result messages

The template expects full conversation history in the `messages` array. Currently, Remora only sends `[system, user]`, so the template's tool result handling (`message.role == 'tool'`) is never exercised.

---

## Appendix B: Example Project File Locations

### distil-SHELLper
- `.context/functiongemma_examples/distil-SHELLper-main/client.py` - Model invocation
- `.context/functiongemma_examples/distil-SHELLper-main/parsing.py` - Tool call parsing
- `.context/functiongemma_examples/distil-SHELLper-main/filesystem_demo.py` - Conversation handling

### distil-smart-home
- `.context/functiongemma_examples/distil-smart-home-main/orchestrator.py` - Full implementation

---

## Appendix C: Quick Reference Comparison

| Aspect | distil-SHELLper | distil-smart-home | Remora (Current) |
|--------|-----------------|-------------------|------------------|
| Temperature | 0 | 0 | 0.1 |
| tool_choice | **Not set** | required | auto |
| History sent | Full | Full | Initial only |
| JSON fallback | 3 paths (two-stage) | 2 paths | submit_result only |
| System prompt | Explicit | Explicit | Minimal |
| Thinking | none | disabled | default |
| Response preference | Content first | tool_calls first | tool_calls only |

---

## Appendix D: Review Verification

This review was created after verifying the junior developer's `MODEL_INTERACTION_REVIEW.md` against the actual source code. Three errors were identified and corrected:

### Error 1: SHELLper Parsing Order Was Inverted

**Original claim:** Primary path is `response.tool_calls`, fallback is JSON parsing.

**Actual behavior (client.py:50-51):**
```python
return response.content if response.content and len(response.content.strip('\n')) else response.tool_calls[0]
```
Primary is `response.content`, fallback is `response.tool_calls[0]`.

### Error 2: Two-Stage Parsing Architecture Not Described

The original review implied client.py does JSON parsing. Actually:
- **Stage 1 (client.py):** Returns raw content OR tool_calls object
- **Stage 2 (parsing.py):** Handles JSON format variations

### Error 3: Overgeneralization About tool_choice

**Original claim:** "Examples force `tool_choice='required'`"

**Actual behavior:**
- distil-SHELLper: Does **not** set `tool_choice` at all
- distil-smart-home: Uses `tool_choice="required"`

Only one of the two examples forces tool calls. SHELLper relies on robust parsing instead.

### Impact on Recommendations

These corrections don't fundamentally change the recommendations, but clarify that:
1. There are two valid approaches: forcing tool_choice OR robust parsing
2. SHELLper's two-stage architecture is a cleaner separation of concerns
3. Preferring content vs. tool_calls is a design choice with trade-offs
