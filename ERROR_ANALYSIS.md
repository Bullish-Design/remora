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

### Cause 1: System prompt format mismatch (most likely)

The `google/functiongemma-270m-it` model was fine-tuned on a specific dataset with a specific system prompt format. The remora system prompt format is:

```
You have access to the following tools:
[JSON array of tool schemas]

Call tools by responding with JSON in the format:
{"name": "<tool_name>", "arguments": { ... }}

[subagent system_prompt from YAML]
```

If the model was trained on a different format (e.g., `<tool>` XML tags, a `functions:` YAML block, or a different JSON key naming convention), it will not recognize this as a function-calling context and will fall back to its instruction-tuning behavior — which is to respond in natural language and decline tasks outside its perceived scope.

The giveaway is the phrasing **"My current capabilities are limited to assisting with document management tasks using the provided tools."** The model is echoing back something from its training distribution. A general-purpose Gemma-IT model would typically say "I can help with that!" rather than "I cannot assist." This language suggests the model was fine-tuned with a specific narrow system prompt that described only document management, and it is now refusing to generalize beyond that training distribution.

### Cause 2: The model may not be the intended FunctionGemma variant

The config default is `google/functiongemma-270m-it`. Compare to the model IDs used in the brainstorm documentation:
- `docs/brainstorm/Refined_vLLM.md`: `google/function-gemma-3-270m`
- `docs/brainstorm/vllm_multi_lora_setup.md` directory: `function-gemma-270m/`

There is a discrepancy in the model name. `functiongemma-270m-it` (no hyphen, no version number) vs `function-gemma-3-270m` (hyphenated, version 3). If the wrong model variant is being served — for example, if a general-purpose Gemma 270M instruction-tuned model was deployed instead of the FunctionGemma fine-tune — it would produce exactly these refusals.

### Cause 3: The model is responding to the right system prompt but requires a different trigger

Some instruction-tuned models require the user message to contain an explicit function-call instruction to enter "tool use mode." The current user message is:

```
Code to document:
```python
def normalize(values: list[int]) -> list[float]:
    ...
```

There is no explicit instruction saying "call a tool now." Some FunctionGemma training recipes require a phrase like "Use the available tools to complete this task." Without it, the model treats the message as a regular user question and responds in natural language.

---

## How to Fix

### Fix 1: Enable guided JSON decoding (recommended, most reliable)

This fix makes the model structurally incapable of outputting plain text — every token it generates must conform to the tool-call JSON schema. This bypasses the model behavior issue entirely.

Modify `_call_model` in `runner.py` to pass `extra_body` to the vLLM server:

```python
# runner.py — in _call_model()
tool_names = [tool.name for tool in self.definition.tools]
guided_schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "enum": tool_names},
        "arguments": {"type": "object"},
    },
    "required": ["name"],
}

response = await self._http_client.chat.completions.create(
    model=self._model_target,
    messages=cast(list[ChatCompletionMessageParam], self.messages),
    max_tokens=512,
    temperature=0.1,
    extra_body={"guided_json": guided_schema},
)
```

This requires the vLLM server to have `outlines` or `lm-format-enforcer` installed (included by default in recent vLLM releases). No changes to the client library are needed — the `openai` SDK passes `extra_body` fields through to the server.

This fix also eliminates the `_parse_tool_calls` complexity and the `_coerce_tool_calls` fallback, since the response will always be valid JSON.

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

### Fix 3: Add an explicit tool-call instruction to the user message

Modify the `node_context` template in the subagent YAML files to include an explicit instruction to call a tool:

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

```yaml
# lint_subagent.yaml
initial_context:
  node_context: |
    Code to analyze:
    ```python
    {{ node_text }}
    ```

    Begin by calling run_linter to check for issues.
```

This gives the model an explicit action to take, which should trigger the function-calling behavior rather than the natural-language response path.

### Fix 4: Add a retry with simplified prompt on plain-text response

A more robust (but more complex) fix adds a retry layer when the model outputs non-JSON:

```python
# In runner.py, modify the no-tool-calls branch:
if not tool_calls:
    if self.turn_count == 1:
        # First turn: model may be confused. Prompt it explicitly.
        self.messages.append({
            "role": "user",
            "content": "Please call one of the available tools now. Respond with JSON only."
        })
        response_text = await self._call_model(phase="loop")
        continue
    raise AgentError(...)
```

This provides one recovery attempt before failing. Combined with Fix 3 (explicit instruction in user message), the model should rarely reach this branch.

---

## Priority Recommendation

Apply fixes in this order:

1. **Fix 2 first** — Verify the correct model is deployed. If the wrong model is running, none of the other fixes will matter.

2. **Fix 1 next** — Enable `guided_json`. This is a one-line addition to `_call_model` and permanently prevents plain-text responses. It also removes the fragile `_parse_tool_calls` regex logic.

3. **Fix 3 as well** — Adding explicit "call the tool" instructions to `node_context` templates costs nothing and improves reliability even when guided JSON is enabled (explicit instructions reduce token waste on the first turn).

Fix 4 is optional and may mask underlying model issues rather than fixing them.

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
