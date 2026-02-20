# Model Interaction Review

## Example Projects: FunctionGemma Integration

### distil-SHELLper (multi-turn bash tool calling)

**How the model is called**
- Uses an OpenAI-compatible client pointing at a local server (Ollama / vLLM / llama.cpp) and passes the full tool schema on every request.
- The system prompt embeds the task description and instructs the model to always return a tool call.
- Calls the model with `temperature=0` for deterministic tool-call output.

**Conversation handling**
- Maintains a growing `conversation_history` list.
- Appends each user message to history.
- After a tool call is accepted, appends the assistant’s tool call (OpenAI tool_calls format) back into history before the next turn.

**Tool-call parsing (two-stage)**
- Stage 1 (client.py): Returns `response.content` if non-empty, otherwise returns `response.tool_calls[0]` as fallback.
- Stage 2 (parsing.py): `parse_llm_response()` handles the returned value:
  - If OpenAI tool_call object: extracts `function.name` and `function.arguments`
  - If JSON string `{"name": ..., "parameters": ...}`: parses directly
  - If JSON string `{"tool_calls": [...]}`: extracts from tool_calls array
- Does **not** parse raw FunctionGemma tags directly; relies on the server's tool-call parser.

**Safety and execution**
- Blocks dangerous `rm` patterns before translating the tool call to bash.
- Asks for user confirmation before executing a command.

**Relevant files**
- `.context/functiongemma_examples/distil-SHELLper-main/client.py`
- `.context/functiongemma_examples/distil-SHELLper-main/filesystem_demo.py`
- `.context/functiongemma_examples/distil-SHELLper-main/parsing.py`

### distil-smart-home (deterministic orchestrator)

**How the model is called**
- Defines explicit OpenAI tool schemas for six smart-home functions.
- Uses an OpenAI-compatible client and requires tool calls (`tool_choice="required"`).
- Uses a system prompt that explicitly instructs tool calling, with missing args left blank.
- Sets `temperature=0` for deterministic calls.

**Conversation handling**
- Sends the full conversation history on every model call.
- Appends assistant tool calls to history in OpenAI tool_calls format.

**Tool-call parsing**
- Primary path: uses `response.tool_calls`.
- Fallback: tries to parse JSON from `response.content` (supports `{"name": ..., "arguments": ...}` or `{"parameters": ...}`)
- Does **not** parse raw FunctionGemma tags directly; relies on the server’s tool-call parser.

**Orchestration logic**
- Enforces required arguments and asks follow-up questions for missing slots.
- Routes the completed tool call into deterministic backend logic.

**Relevant files**
- `.context/functiongemma_examples/distil-smart-home-main/orchestrator.py`

## Remora Harness: Current Behavior

### Tool schemas and .pym execution
- Tool schemas are generated from Grail `.pym` scripts via `GrailToolRegistry`.
- The registry loads each script, reads Grail’s generated `inputs.json`, and builds OpenAI-style schemas.
- Tool calls are executed through `ProcessIsolatedExecutor` (child process), and results are returned as JSON strings.

### Model request flow
- `FunctionGemmaRunner` builds a prompt from:
  - System prompt from the subagent definition.
  - A single initial user message derived from the node context.
- For each model call, it **rebuilds** prompt messages using only the system prompt + initial message.
- It does not include prior tool calls or tool results in the prompt payload.

### Tool-call handling
- The runner expects tool calls in the OpenAI `tool_calls` field.
- If no tool calls are returned, it may parse JSON from content and treat it as a `submit_result` payload.
- There is no fallback to parse JSON tool calls (e.g., `{"name":..., "arguments":...}`) as an actual tool call.

### Server configuration
- The vLLM server is started with FunctionGemma tool-call parser and a FunctionGemma chat template.
- The harness relies on server-side parsing of FunctionGemma’s special tags.

**Relevant files**
- `scripts/functiongemma_harness.py`
- `src/remora/runner.py`
- `src/remora/tool_registry.py`
- `src/remora/execution.py`
- `server/entrypoint.sh`
- `server/tool_chat_template_functiongemma.jinja`

## Where Remora Differs From the Examples

1. **Conversation history is not sent each turn**
   - Examples send the full, growing conversation history on each call.
   - Remora rebuilds only the initial system + user prompt every turn, so tool results are not part of the next prompt.

2. **Tool choice defaults**
   - distil-smart-home forces `tool_choice="required"`.
   - distil-SHELLper does **not** set `tool_choice` (relies on robust parsing instead).
   - Remora defaults to `auto` in config and in the harness CLI.

3. **JSON tool-call fallback**
   - Examples attempt to parse JSON tool calls from `response.content` if `tool_calls` is missing.
   - Remora only parses JSON from content when treating it as a `submit_result` payload.

4. **Prompt specificity**
   - Examples embed explicit, task-specific tool-calling instructions and missing-argument handling guidance.
   - Remora harness prompt is minimal and relies heavily on the tool list.

5. **Temperature defaults**
   - Examples use `temperature=0` for deterministic tool-call output.
   - Remora uses `temperature=0.1` by default.

## Recommended Refactor for Alignment

### 1) Send full conversation history
- Track the full `self.messages` history in `FunctionGemmaRunner` and pass it directly to the model.
- Avoid rebuilding a fresh prompt each time; instead, update the system message once and append new messages.

### 2) Force tool calls in the harness (optional)
- Set `tool_choice="required"` by default in `scripts/functiongemma_harness.py`.
- Keep the core `RunnerConfig` default as `auto` to avoid changing other subagents.
- Note: distil-SHELLper does not use `tool_choice="required"` and instead relies on robust parsing. Either approach can work.

### 3) Add JSON tool-call fallback
- If `message.tool_calls` is empty and `message.content` parses to `{"name":..., "arguments":...}` or `{"parameters":...}`, treat it as a synthetic tool call.
- Allow `submit_result` only if `name == "submit_result"`.

### 4) Improve harness system prompt
- Include a short tool-calling directive similar to the examples:
  - “Always respond with a tool call.”
  - “If required args are missing, omit them and let the caller ask.”

### 5) Lower temperature for harness runs
- Set default harness CLI temperature to `0` (still overridable via config).

## Implementation Overview

### Code changes (high level)
- **`src/remora/runner.py`**
  - Replace `_build_prompt_messages()` to return the current message history rather than rebuilding a fresh prompt each call.
  - Ensure the system prompt is inserted once at the beginning, and new messages are appended as the run progresses.
  - Add a JSON tool-call fallback parser when `message.tool_calls` is missing.

- **`scripts/functiongemma_harness.py`**
  - Default `tool_choice` to `required`.
  - Override temperature to `0` for harness runs.

- **`agents/harness/harness_subagent.yaml`**
  - Expand the system prompt with explicit tool-calling guidance.

### Rollout steps
1. Update harness defaults (tool choice + temperature).
2. Update `FunctionGemmaRunner` message handling and JSON tool-call fallback.
3. Run the harness sweep to verify tool-call rate improves.
4. Optionally tune the harness system prompt if any errors persist.

### Expected outcome
- The harness should now behave like the examples: full conversation context, deterministic output, required tool calls, and robust tool-call parsing even when content is JSON.
