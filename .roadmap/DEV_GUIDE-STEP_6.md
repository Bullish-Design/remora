# DEV GUIDE STEP 6: FunctionGemmaRunner — Multi-Turn Loop

## Goal
Implement the core multi-turn tool calling loop: call the model, parse tool calls, dispatch tool `.pym` scripts via Cairn, inject context provider output, append results, and repeat until `submit_result` is called or the turn limit is reached.

## Why This Matters
This is the reasoning engine of each subagent. The loop must correctly handle every response type (tool call, plain text stop), inject per-tool context at the right moment, enforce turn limits, and cleanly terminate on `submit_result`. Any bug here affects every operation across every node.

## Implementation Checklist
- Implement `async def run(self) -> AgentResult`.
- After `_build_initial_messages()`, enter the while loop (bounded by `max_turns`).
- On each iteration: call `model.create_chat_completion(messages, tools, tool_choice="auto")`.
- Handle `finish_reason == "stop"`: task complete via plain text — extract and return result.
- Handle `finish_reason == "tool_calls"`:
  - For each tool call: dispatch `_dispatch_tool(tc)`, append tool role message.
  - If tool name is `submit_result`: immediately return `AgentResult` from parsed arguments.
- On turn limit exceeded: return failed `AgentResult` with `AGENT_003`.
- Implement `async def _dispatch_tool(self, tool_call: dict) -> dict`:
  - Lookup `ToolDefinition` by name from `definition.tools_by_name`.
  - For each `context_provider` in the tool definition: run via Cairn, inject as user message.
  - Execute the tool's `.pym` script via Cairn with the tool's arguments.
  - Return the JSON result dict.

## Suggested File Targets
- `remora/runner.py` (continue from Step 5)

## run() Pseudocode

```python
async def run(self) -> AgentResult:
    while self.turn_count < self.definition.max_turns:
        response = self.model.create_chat_completion(
            messages=self.messages,
            tools=self.definition.tool_schemas,
            tool_choice="auto",
        )
        choice = response["choices"][0]
        self.messages.append(choice["message"])
        self.turn_count += 1

        if choice["finish_reason"] == "stop":
            return AgentResult(
                status="success",
                workspace_id=self.workspace_id,
                changed_files=[],
                summary=choice["message"].get("content", ""),
                details={},
                error=None,
            )

        for tc in choice["message"].get("tool_calls", []):
            result = await self._dispatch_tool(tc)
            self.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })
            if tc["function"]["name"] == "submit_result":
                args = json.loads(tc["function"]["arguments"])
                return AgentResult(
                    status="success",
                    workspace_id=self.workspace_id,
                    **args,
                )

    return AgentResult(
        status="failed",
        workspace_id=self.workspace_id,
        changed_files=[],
        summary="",
        details={},
        error=f"AGENT_003: Turn limit ({self.definition.max_turns}) exceeded",
    )
```

## _dispatch_tool() Pseudocode

```python
async def _dispatch_tool(self, tool_call: dict) -> dict:
    name = tool_call["function"]["name"]
    args = json.loads(tool_call["function"]["arguments"])
    tool_def = self.definition.tools_by_name.get(name)
    if tool_def is None:
        return {"error": f"Unknown tool: {name}"}

    # Inject per-tool context providers before dispatching
    for provider_path in tool_def.context_providers:
        ctx = await self.cairn_client.run_pym(
            provider_path, self.workspace_id, inputs={}
        )
        self.messages.append({
            "role": "user",
            "content": f"[Context] {ctx}",
        })

    # Execute the tool
    return await self.cairn_client.run_pym(
        tool_def.pym, self.workspace_id, inputs=args
    )
```

## AgentResult Model

```python
class AgentResult(BaseModel):
    status: Literal["success", "failed", "skipped"]
    workspace_id: str
    changed_files: list[str]
    summary: str
    details: dict = {}
    error: str | None = None
```

## Implementation Notes
- `model.create_chat_completion()` is a synchronous llama.cpp call. Wrap it in `asyncio.get_event_loop().run_in_executor(None, ...)` to avoid blocking the event loop during concurrent runs.
- Tool call arguments from the model are always a JSON string in `tc["function"]["arguments"]`. Always parse with `json.loads()` — never eval or assume structure.
- `submit_result` arguments from the model may include extra fields if the YAML schema is permissive. Parse only the fields `AgentResult` expects; discard extras.
- Context provider output is injected as a `role: "user"` message with a `[Context]` prefix to clearly distinguish it from actual user turns in the conversation history.

## Testing Overview
- **Unit test (mock model):** Model that calls `submit_result` on first turn → returns `AgentResult` with `status=success` after 1 turn.
- **Unit test (mock model):** Model that calls 3 non-terminal tools then `submit_result` → returns after 4 turns with correct turn count.
- **Unit test (mock model):** Model that never calls `submit_result` → returns failed `AgentResult` with `AGENT_003` at `max_turns=3`.
- **Unit test (mock model):** Model with `finish_reason=stop` (plain text) → returns `AgentResult` with empty `changed_files`.
- **Unit test:** Context providers are called before tool dispatch and injected as user messages in order.
- **Unit test:** Unknown tool name returns error dict without crashing the loop.
