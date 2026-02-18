# vLLM FunctionGemma Tool Calling — Refactor Plan

**Date:** 2026-02-18
**Current state:** Remora manually injects tool schemas into the system prompt as JSON text, parses tool calls from the model's raw text output using regex heuristics, and formats tool results as `role="user"` messages.
**Target state:** Remora uses vLLM's native tool calling API with the `functiongemma` parser, passing tools via the standard `tools=` parameter and receiving structured `tool_calls` objects back.

---

## 1. What's Wrong with the Current Approach

The current approach is fundamentally incompatible with FunctionGemma's actual wire format. There are three layers of mismatch:

### 1.1 System prompt injection is wrong

Remora currently builds this system prompt in `runner.py:_build_system_prompt()`:

```
You have access to the following tools:
[JSON array of tool schemas]

Call tools by responding with JSON in the format:
{"name": "<tool_name>", "arguments": { ... }}

[subagent system_prompt]
```

FunctionGemma was **not trained on this prompt format**. The model does not know to output `{"name": ..., "arguments": ...}`. It was trained with a specific Jinja2 chat template (`tool_chat_template_functiongemma.jinja`) that presents tools as:

```
<start_of_turn>user
[system prompt content]
Available functions:
Function: get_weather
Description: Get the current weather
Parameters: {"type": "object", ...}
<end_of_turn>
<start_of_turn>model
```

This formatting is handled server-side by vLLM's chat template renderer when the client passes tools via the standard `tools=` parameter.

### 1.2 Output format expectation is wrong

The current `_parse_tool_calls` looks for JSON in the model's text output. FunctionGemma outputs a custom format:

```
<start_function_call>call:get_weather{location:<escape>London<escape>,unit:<escape>celsius<escape>}<end_function_call>
```

The vLLM server's `functiongemma` tool parser (`--tool-call-parser functiongemma`) automatically translates this into standard OpenAI-format `tool_calls` objects before the response reaches the client. The client never sees the raw `<start_function_call>` format.

### 1.3 Tool result message format is wrong

Remora currently appends tool results as:

```python
{"role": "user", "content": "[Tool result for run_linter] {...}"}
```

The correct format (per the FunctionGemma chat template) is:

```python
{"role": "tool", "content": "...", "tool_call_id": "call_abc123", "name": "run_linter"}
```

The chat template renders `role="tool"` messages as:

```
<start_of_turn>user
Function result for run_linter: {...}
<end_of_turn>
```

Using the wrong role means the model does not recognise previous tool results as function outputs, breaking the multi-turn loop.

---

## 2. The Correct Architecture

### 2.1 Server startup flags (required)

The vLLM server must be started with:

```bash
python3 -m vllm.entrypoints.openai.api_server \
    --model google/functiongemma-270m-it \
    --enable-auto-tool-choice \
    --tool-call-parser functiongemma \
    --chat-template examples/tool_chat_template_functiongemma.jinja \
    --enable-lora \
    --max-loras 20 \
    --max-lora-rank 32 \
    --enable-prefix-caching \
    --max-num-seqs 256
```

Key flags:
- `--enable-auto-tool-choice` — allows the model to call tools automatically
- `--tool-call-parser functiongemma` — uses vLLM's built-in FunctionGemma parser that understands `<start_function_call>...<end_function_call>` output
- `--chat-template examples/tool_chat_template_functiongemma.jinja` — formats system/user/tool messages correctly for FunctionGemma

### 2.2 Client-side call (correct form)

```python
response = await client.chat.completions.create(
    model=self._model_target,
    messages=self.messages,          # standard OpenAI message list
    tools=self.definition.tool_schemas,   # OpenAI-format tool definitions
    tool_choice="required",          # guarantee a tool call every turn
    max_tokens=512,
    temperature=0.1,
)
```

`tool_choice="required"` is supported as of vllm>=0.8.3. It guarantees the model produces at least one tool call, preventing the "model stopped without calling submit_result" error.

### 2.3 Response parsing (correct form)

The response, after vLLM's parser runs, uses standard OpenAI format:

```python
message = response.choices[0].message

if message.tool_calls:
    for tool_call in message.tool_calls:
        name = tool_call.function.name                          # "run_linter"
        arguments = json.loads(tool_call.function.arguments)    # {"check_only": true}
        call_id = tool_call.id                                  # "call_abc123"
```

No regex, no JSON extraction, no `_parse_tool_calls` needed.

### 2.4 Message history format

The message list must use standard OpenAI roles:

```python
# System message — subagent's system_prompt only (NO tool injection)
{"role": "system", "content": "You are a Python linting specialist..."}

# Initial user message — the node code
{"role": "user", "content": "Code to analyze:\n```python\ndef foo(): ...\n```"}

# Model's tool call (appended from response)
{
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "run_linter",
                "arguments": '{"check_only": false}'
            }
        }
    ]
}

# Tool result (role="tool", NOT role="user")
{
    "role": "tool",
    "tool_call_id": "call_abc123",
    "name": "run_linter",
    "content": '{"issues": [{"code": "E501", "line": 3}]}'
}
```

---

## 3. Files That Need to Change

### 3.1 `remora/runner.py` — FunctionGemmaRunner

This is the largest change. The following methods change completely:

**`_build_system_prompt()` → remove tool injection**

Currently injects the full tool schema JSON into the system prompt. Remove this entirely. The new system message is just `self.definition.initial_context.system_prompt` — the subagent's role description with no tool preamble.

```python
# Before (wrong):
def _build_system_prompt(self) -> str:
    tool_schema_block = json.dumps(self.definition.tool_schemas, indent=2)
    return (
        "You have access to the following tools:\n"
        f"{tool_schema_block}\n\n"
        "Call tools by responding with JSON in the format:\n"
        '{"name": "<tool_name>", "arguments": { ... }}\n\n'
        f"{self.definition.initial_context.system_prompt}"
    )

# After (correct):
def _build_system_prompt(self) -> str:
    return self.definition.initial_context.system_prompt
```

**`_call_model()` → pass `tools` and `tool_choice` parameters**

```python
# Before (wrong):
response = await self._http_client.chat.completions.create(
    model=self._model_target,
    messages=cast(list[ChatCompletionMessageParam], self.messages),
    max_tokens=512,
    temperature=0.1,
)
content = response.choices[0].message.content

# After (correct):
response = await self._http_client.chat.completions.create(
    model=self._model_target,
    messages=cast(list[ChatCompletionMessageParam], self.messages),
    tools=cast(list[ChatCompletionToolParam], self.definition.tool_schemas),
    tool_choice="required",
    max_tokens=512,
    temperature=0.1,
)
# Returns the full message object, not just text content
return response.choices[0].message
```

**`_parse_tool_calls()` and `_coerce_tool_calls()` → delete**

These are no longer needed. The vLLM server's `functiongemma` tool parser handles all output format conversion server-side. The client receives structured `tool_calls` objects from the standard OpenAI response format.

**Main `run()` loop → use `message.tool_calls` instead of text parsing**

```python
# Before (wrong):
response_text = await self._call_model(phase="model_load")
self.messages.append({"role": "assistant", "content": response_text})
tool_calls = self._parse_tool_calls(response_text)

# After (correct):
message = await self._call_model(phase="model_load")
self.messages.append(message)   # append the full assistant message (preserves tool_calls field)
tool_calls = message.tool_calls or []
```

**`_dispatch_tool()` → append role="tool" result, not role="user"**

```python
# Before (wrong):
tool_result = await self.cairn_client.run_pym(...)
self.messages.append({
    "role": "user",
    "content": f"[Tool result for {tool_name}] {json.dumps(tool_result)}"
})

# After (correct):
tool_result = await self.cairn_client.run_pym(...)
self.messages.append({
    "role": "tool",
    "tool_call_id": tool_call.id,      # must match the tool_call id
    "name": tool_call.function.name,
    "content": json.dumps(tool_result),
})
```

**Context providers → inject as user messages before dispatch**

Context providers currently inject `{"role": "user", "content": "[Context] {...}"}` messages. In the new format these can remain as `role="user"` messages inserted before the tool result, or they can be concatenated into the tool result content. The simplest approach is to prepend them to the tool result content:

```python
context_parts = []
for provider_path in tool_def.context_providers:
    ctx_result = await self.cairn_client.run_pym(provider_path, self.workspace_id, {})
    context_parts.append(json.dumps(ctx_result))

tool_result_content = "\n".join(context_parts + [json.dumps(tool_result)])
self.messages.append({
    "role": "tool",
    "tool_call_id": tool_call.id,
    "name": tool_call.function.name,
    "content": tool_result_content,
})
```

**`_build_submit_result()` → read from `tool_call.function.arguments`**

```python
# Before (wrong):
arguments = tool_call.get("arguments", {})

# After (correct):
arguments = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
```

### 3.2 `remora/config.py`

Add configurable inference parameters (currently hardcoded in `runner.py`):

```python
class RunnerConfig(BaseModel):
    max_turns: int = 20
    max_concurrent_runners: int = 16
    timeout: int = 300
    max_tokens: int = 512        # was hardcoded
    temperature: float = 0.1     # was hardcoded
    tool_choice: str = "required"  # "required" | "auto" | "none"
```

No new `VLLMConfig` section is needed for the core refactor — the tool calling integration is entirely handled by the server flags and the `tools=` parameter in the client call. Server-side vLLM flags are documented in `docs/SERVER_SETUP.md`, not in client config.

### 3.3 `remora/subagent.py`

The `tool_schemas` property is already in the correct OpenAI format for the `tools=` parameter — no change needed. The `"strict": True` field in tool schemas is passed through correctly.

The `InitialContext.system_prompt` now becomes the complete system message (no tool preamble is prepended by the runner). Existing YAML files already write concise role descriptions there, so no YAML changes are needed.

### 3.4 `server/` directory — `entrypoint.sh` update

The vLLM server startup command must be updated to include the FunctionGemma tool calling flags:

```bash
python3 -m vllm.entrypoints.openai.api_server \
    --model google/functiongemma-270m-it \
    --enable-auto-tool-choice \
    --tool-call-parser functiongemma \
    --chat-template /app/tool_chat_template_functiongemma.jinja \
    --enable-lora \
    --max-loras 20 \
    --max-lora-rank 32 \
    --enable-prefix-caching \
    --max-num-seqs 256
```

The `tool_chat_template_functiongemma.jinja` file (from vLLM's `examples/` directory) must be bundled into the Docker image.

### 3.5 `tests/test_runner.py`

The fake client and test assertions need updating:

**`FakeChatCompletions.create`** — must accept `tools` and `tool_choice` parameters, and return a response object with `.message.tool_calls` (not just `.message.content`):

```python
class FakeChatCompletions:
    async def create(self, *, model, messages, tools=None, tool_choice=None,
                     max_tokens, temperature):
        ...
        # Return mock with tool_calls structure
        return FakeCompletionResponse(
            tool_calls=[FakeToolCall(name=..., arguments=...)]
        )
```

All test assertions that check `runner.messages` for `{"role": "user", "content": "[Tool result..."}` must change to check for `{"role": "tool", "tool_call_id": ..., "content": ...}`.

---

## 4. Files Changed Summary

| File | Change Type | Description |
|---|---|---|
| `remora/runner.py` | Major refactor | Remove manual tool injection and text parsing; use `tools=` parameter and `message.tool_calls`; change tool results to `role="tool"` |
| `remora/config.py` | Minor addition | Move `max_tokens`, `temperature` to `RunnerConfig`; add `tool_choice` |
| `server/entrypoint.sh` | Update | Add `--enable-auto-tool-choice --tool-call-parser functiongemma --chat-template` flags |
| `server/` (new file) | New file | Bundle `tool_chat_template_functiongemma.jinja` into server image |
| `tests/test_runner.py` | Update | Update fakes and assertions for new message format and tool_calls structure |
| `docs/SERVER_SETUP.md` | Update | Document required server flags for FunctionGemma tool calling |
| `remora.yaml.example` | Minor update | Document `runner.tool_choice` config option |

**No changes needed:**
- `remora/subagent.py` — `tool_schemas` property already emits correct OpenAI format
- `remora/client.py` — `AsyncOpenAI` builder unchanged; `tools=` is a standard parameter
- `remora/orchestrator.py` — orchestration logic unchanged
- Subagent YAML files — `initial_context.system_prompt` already just the role description
- `pyproject.toml` — no new dependencies; `openai>=1.0` already supports `tools=`

---

## 5. Additional Functionality Enabled

### 5.1 `tool_choice="required"` — eliminates AGENT_003 errors

With `tool_choice="required"` (supported in vllm>=0.8.3), the server uses structured outputs to guarantee the model produces at least one valid tool call. The model cannot output plain text. This permanently solves the "Model stopped without calling submit_result" error without any client-side workarounds.

### 5.2 Parallel tool calls

The FunctionGemma model can output multiple `<start_function_call>` blocks in a single response. The vLLM parser returns all of them as a list in `message.tool_calls`. The refactored runner naturally handles this — the `for tool_call in message.tool_calls` loop processes each one.

This means a single model turn can dispatch multiple tools simultaneously (e.g., `read_current_docstring` and `read_type_hints` at once), reducing the number of model calls needed.

### 5.3 `tool_choice="auto"` for smarter routing

Setting `tool_choice="auto"` allows the model to decide whether to call a tool or respond in plain text. This enables a more conversational final turn where the model can summarise without being forced to call `submit_result` — instead, remora can detect when `tool_calls` is empty and interpret `message.content` as the completion signal.

### 5.4 Named function forcing

Setting `tool_choice={"type": "function", "function": {"name": "submit_result"}}` forces the model to call `submit_result` specifically. This can be used on the last turn before the turn limit to gracefully close out the loop:

```python
if self.turn_count >= self.definition.max_turns - 1:
    # Force the model to conclude on the next call
    tool_choice = {"type": "function", "function": {"name": "submit_result"}}
```

### 5.5 Streaming tool call deltas

With `stream=True`, vLLM streams `<start_function_call>` output token-by-token and the `functiongemma` parser buffers and reconstructs the tool call incrementally. The client receives delta objects as the function name and arguments stream in. This enables live progress in the `remora-tui` dashboard showing which tool is being called and its arguments forming in real time.

### 5.6 Logprobs on tool name selection

With `logprobs=True`, the model returns per-token log probabilities. For FunctionGemma tool calls, this means the client can see the model's confidence on the function name token (e.g., high confidence on `run_linter` vs low confidence choosing between `apply_fix` and `submit_result`). Low-confidence tool selections can be flagged or retried.

### 5.7 Prefix caching for system prompts

With `--enable-prefix-caching` on the server, the KV cache for the system prompt is shared across all requests that have the same prefix. Since all `docstring_agent` calls share the same system prompt, the first request pays the full prefill cost but all subsequent requests get a cache hit — dramatically reducing TTFT for large batches. This is server-side only, no client changes required.

---

## 6. Root Cause of Current Errors (Updated)

The vLLM documentation confirms the root cause of the errors shown in the problem statement:

**The model `google/functiongemma-270m-it` was trained with the FunctionGemma chat template** (`tool_chat_template_functiongemma.jinja`). When tools are NOT presented in this format — i.e., when they are injected manually into the system prompt text as JSON — the model does not recognise the context as a tool-calling task. It falls through to its general instruction-following behaviour and produces a refusal.

The fix is not a prompt workaround. The fix is to use the standard `tools=` parameter in the API call and start the vLLM server with `--tool-call-parser functiongemma --chat-template tool_chat_template_functiongemma.jinja`. The chat template then presents tools correctly to the model, the model produces `<start_function_call>` output, the parser converts it to `tool_calls`, and the client receives a structured tool call object.

No guided JSON, no regex parsing, no prompt engineering. Just the correct API usage.
