# Error Analysis: "Model stopped without calling submit_result"

**Date:** 2026-02-18
**Errors reported:** `agent_error` events from `docstring_agent` and `type_check` (lint) operations
**Model:** `google/functiongemma-270m-it`

---

## The Errors

```json
{"event": "agent_error", "operation": "docstring", "error": "Model stopped without calling submit_result"}
{"event": "agent_error", "operation": "type_check", "error": "Model stopped without calling submit_result"}
```

Both failures share the same root cause.

---

## Root Cause Analysis

### What the model is actually doing

Looking at the `model_response` events preceding both errors:

```
response_text: "I apologize, but I cannot assist with generating or documenting code.
My current capabilities are limited to assisting with document management tasks
using the provided tools. I cannot generate or modify code."
```

```
response_text: "I apologize, but I cannot assist with analyzing or applying code.
My current capabilities are limited to assisting with the execution of linter
and fix tools. I cannot perform code analysis, apply fixes, or report issues."
```

The model is generating **plain text refusals**, not JSON tool calls.

### Why this causes `AGENT_003`

In `remora/runner.py`, the agent loop works as follows:

```python
# runner.py:95-106
while self.turn_count < self.definition.max_turns:
    self.turn_count += 1
    self.messages.append({"role": "assistant", "content": response_text})
    tool_calls = self._parse_tool_calls(response_text)
    if not tool_calls:
        raise AgentError(
            ...
            message="Model stopped without calling submit_result",
        )
```

`_parse_tool_calls` looks for either a `\`\`\`json ... \`\`\`` block or a bare JSON object in `response_text`. Since the model output is plain English, no JSON is found, `tool_calls` is an empty list, and the error is raised immediately on the first turn.

This is correct behavior — the code is working as designed. The problem is upstream in the model.

---

## Why the Model Produces Refusals

### Cause 1 (confirmed): Wrong tool calling API usage — chat template mismatch

This is the definitive root cause, confirmed by vLLM's official documentation for FunctionGemma.

FunctionGemma (`google/functiongemma-270m-it`) was trained with a specific Jinja2 chat template — `tool_chat_template_functiongemma.jinja`. This template presents tool definitions to the model as:

```
<start_of_turn>user
[system prompt content]
Available functions:
Function: run_linter
Description: Run the linter and return a list of issues with line numbers.
Parameters: {"type": "object", ...}
<end_of_turn>
<start_of_turn>model
```

Remora currently injects tools into the system message as a JSON array:

```
You have access to the following tools:
[{"type": "function", "function": {"name": "run_linter", ...}}, ...]

Call tools by responding with JSON in the format:
{"name": "<tool_name>", "arguments": { ... }}
```

The model was **never trained on this format**. It does not recognise it as a tool-calling context. It falls through to its instruction-following behaviour and declines.

Furthermore, FunctionGemma does not output `{"name": ..., "arguments": ...}` JSON. It outputs:

```
<start_function_call>call:run_linter{check_only:<escape>true<escape>}<end_function_call>
```

vLLM's `functiongemma` tool parser (`--tool-call-parser functiongemma`) is responsible for translating this format into standard OpenAI `tool_calls` objects. Without this flag on the server, neither the input formatting nor the output parsing work correctly.

### Cause 2: The model may not be the intended FunctionGemma variant

The config default is `google/functiongemma-270m-it`. Compare to the model IDs used in the brainstorm documentation:
- `docs/brainstorm/Refined_vLLM.md`: `google/function-gemma-3-270m`
- `docs/brainstorm/vllm_multi_lora_setup.md` directory: `function-gemma-270m/`

There is a naming discrepancy. If the wrong model variant is being served, it would also produce these refusals. According to vLLM's documentation, the supported model ID is explicitly `google/functiongemma-270m-it`, which matches the remora config default and is the correct name.

---

## How to Fix

### Fix 1: Use the correct vLLM tool calling API (the real fix)

This is the complete, correct fix. It requires changes to both the server and the client.

**Server:** Start vLLM with:
```bash
python3 -m vllm.entrypoints.openai.api_server \
    --model google/functiongemma-270m-it \
    --enable-auto-tool-choice \
    --tool-call-parser functiongemma \
    --chat-template examples/tool_chat_template_functiongemma.jinja \
    ...
```

The `--tool-call-parser functiongemma` flag activates vLLM's built-in FunctionGemma parser, which:
1. Presents tools to the model using the correct chat template format
2. Parses `<start_function_call>...<end_function_call>` responses into standard OpenAI `tool_calls` objects

**Client:** Change `_call_model` in `runner.py` to pass tools via the standard `tools=` parameter and add `tool_choice="required"` (supported in vllm>=0.8.3):

```python
response = await self._http_client.chat.completions.create(
    model=self._model_target,
    messages=cast(list[ChatCompletionMessageParam], self.messages),
    tools=cast(list[ChatCompletionToolParam], self.definition.tool_schemas),
    tool_choice="required",   # guarantees a tool call every turn
    max_tokens=512,
    temperature=0.1,
)
message = response.choices[0].message
tool_calls = message.tool_calls or []   # structured objects, no regex needed
```

Also remove the manual tool injection from `_build_system_prompt()` — the chat template handles this server-side. And change tool result messages from `role="user"` to `role="tool"` with `tool_call_id` set.

See `VLLM_REFACTOR.md` for the complete list of code changes.

### Fix 2: Verify the correct model is being served

Check which model the vLLM server is actually serving:

```bash
curl http://remora-server:8000/v1/models
```

The response should list the base model. Confirm it matches `google/functiongemma-270m-it` (or the intended variant). If it lists a different model (e.g., a generic `gemma-2-2b-it`), the wrong model was deployed.

Also confirm that the model name in `remora/config.py` matches the model name in the vLLM server's `--model` flag exactly:

```python
# config.py
class ServerConfig(BaseModel):
    default_adapter: str = "google/functiongemma-270m-it"
```

```bash
# vLLM server entrypoint
python3 -m vllm.entrypoints.openai.api_server \
    --model google/functiongemma-270m-it \
    ...
```

### Fix 3: Add an explicit first-step hint to the user message

Once Fix 1 is in place, the model should call tools reliably. However, adding an explicit action hint in the `node_context` template reduces first-turn uncertainty and saves tokens:

```yaml
# docstring_subagent.yaml
initial_context:
  node_context: |
    Code to document:
    ```python
    {{ node_text }}
    ```

    Begin by calling read_current_docstring to check for an existing docstring.
```

This costs nothing and works well with the FunctionGemma chat template.

---

## Priority Recommendation

1. **Fix 1 is the complete solution.** Update the vLLM server startup flags and the `_call_model` call in `runner.py`. This addresses all three layers of mismatch (prompt format, output parsing, tool result format) and makes the error structurally impossible.

2. **Fix 2 in parallel** — Run `curl http://remora-server:8000/v1/models` to confirm the model ID is correct before spending time on code changes.

3. **Fix 3 as a polish step** — Add first-step hints to YAML templates after Fix 1 is validated.

---

## Additional Code Issue: `AGENT_003` Error Phase is Incorrect

Looking at the event log:

```json
{"event": "agent_error", "phase": "run", "error": "Model stopped without calling submit_result"}
```

But in the code, this error is raised with `phase="loop"`:

```python
# runner.py:100-106
raise AgentError(
    node_id=self.node.node_id,
    operation=self.definition.name,
    phase="loop",    # ← raised here
    error_code=AGENT_003,
    message="Model stopped without calling submit_result",
)
```

The `phase="run"` in the event comes from the outer `except` in `orchestrator.py`:

```python
# orchestrator.py:82-93
except Exception as exc:
    self._event_emitter.emit({
        "event": "agent_error",
        ...
        "phase": "run",    # ← overwrites the original phase
        "error": str(exc),
    })
```

The original `AgentError.phase` ("loop") is overwritten by the orchestrator's generic "run" phase. The `AgentError` attributes (`phase`, `error_code`, `node_id`) should be read from the exception object if available, not hardcoded as "run". This loses diagnostic information.
