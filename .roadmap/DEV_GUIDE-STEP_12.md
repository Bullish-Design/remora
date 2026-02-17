# DEV GUIDE STEP 12: Runner Adaptation for `llm` Library

## Goal
Replace the `llama-cpp-python` / GGUF model loading approach in `FunctionGemmaRunner` with the `llm` Python library, calling the stock FunctionGemma model via Ollama. This eliminates the training pipeline entirely — the stock model is used as-is.

## Why This Matters
The `llama-cpp-python` path required domain-specific fine-tuned GGUF files to exist before any runner could work. By switching to the `llm` library with Ollama, the runner can operate immediately with the stock FunctionGemma model. This unblocks end-to-end testing without any model training.

## Implementation Checklist
- Update `pyproject.toml`: replace `llama-cpp-python` with `llm` and `llm-ollama`.
- Remove the `ModelCache` singleton (`remora/model_cache.py` or equivalent).
- Rewrite `FunctionGemmaRunner.__init__` to acquire a model handle via `llm.get_model()`.
- Rewrite the multi-turn loop in `FunctionGemmaRunner.run()` to use the `llm` conversation API.
- Implement tool schema injection: pass tool definitions to the model via the `llm` library's tool API or by encoding them in the system prompt.
- Implement tool call parsing: extract tool calls from the model response and dispatch them.
- Update `SubagentDefinition` loading — remove the `model` path field (GGUF path); replace with a `model_id` string (Ollama model name, e.g. `"ollama/functiongemma-4b-it"`).
- Update `AGENT_002` error: change from "GGUF file not found" to "model not available in Ollama".
- Update config: `RemoraConfig` should have a top-level `model_id` defaulting to `"ollama/functiongemma-4b-it"`.

## Suggested File Targets
- `pyproject.toml`
- `remora/runner.py`
- `remora/models.py` (update config schemas)
- `remora/subagent.py` (remove GGUF path field)
- Delete `remora/model_cache.py` (no longer needed)

## Dependency Changes

```toml
# pyproject.toml — remove llama-cpp-python, add llm ecosystem
dependencies = [
    "typer",
    "rich",
    "pydantic",
    "pydantree",
    "cairn",
    "llm>=0.19",
    "llm-ollama>=0.9",
    "jinja2",
    "watchfiles",
]
```

Install the Ollama plugin after install:
```bash
llm install llm-ollama
```

## Updated Runner Initialisation

```python
import llm

class FunctionGemmaRunner:
    def __init__(
        self,
        definition: SubagentDefinition,
        node: CSTNode,
        workspace_id: str,
        cairn_client: CairnClient,
        model_id: str = "ollama/functiongemma-4b-it",
    ):
        self.definition = definition
        self.node = node
        self.workspace_id = workspace_id
        self.cairn = cairn_client
        try:
            self.model = llm.get_model(model_id)
        except llm.UnknownModelError as e:
            raise RemoraError("AGENT_002", f"Model not available: {model_id}") from e
```

No model caching is needed — `llm.get_model()` is lightweight and Ollama handles the actual model lifecycle.

## Multi-Turn Loop with `llm`

```python
async def run(self) -> AgentResult:
    system_prompt = self._build_system_prompt()  # includes tool schemas as JSON
    initial_message = self._render_node_context()

    conversation = self.model.conversation(system=system_prompt)
    response = conversation.prompt(initial_message)

    for turn in range(self.max_turns):
        tool_calls = self._parse_tool_calls(response.text())

        if not tool_calls:
            # Model returned plain text with no tool call — treat as AGENT_003
            raise RemoraError("AGENT_003", "Model stopped without calling submit_result")

        for call in tool_calls:
            if call["name"] == "submit_result":
                return AgentResult(
                    status="success",
                    **call["arguments"],
                )
            tool_result = await self._dispatch_tool(call)
            response = conversation.prompt(
                f"Tool result for {call['name']}: {json.dumps(tool_result)}"
            )

    raise RemoraError("AGENT_003", f"Turn limit {self.max_turns} exceeded")
```

## Tool Schema Injection

FunctionGemma is a tool-calling model. Pass tool schemas in the system prompt as JSON so the stock model understands what tools are available. Prepend the schemas before the domain-specific system prompt:

```python
def _build_system_prompt(self) -> str:
    tool_schema_block = json.dumps(self.definition.tool_schemas, indent=2)
    return (
        f"You have access to the following tools:\n{tool_schema_block}\n\n"
        f"Call tools by responding with JSON in the format:\n"
        f'{{"name": "<tool_name>", "arguments": {{...}}}}\n\n'
        f"{self.definition.system_prompt}"
    )
```

If `llm-ollama` exposes a native tools API (check with `llm.get_model(...).can_use_tools`), prefer that over schema-in-prompt injection.

## Tool Call Parsing

The stock FunctionGemma model outputs tool calls as JSON. Parse the response text:

```python
def _parse_tool_calls(self, text: str) -> list[dict]:
    """Extract tool call JSON objects from the model response."""
    import re
    # FunctionGemma wraps calls in ```json ... ``` or outputs raw JSON
    json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if not json_blocks:
        # Try raw JSON
        try:
            obj = json.loads(text.strip())
            return [obj] if "name" in obj else []
        except json.JSONDecodeError:
            return []
    results = []
    for block in json_blocks:
        try:
            obj = json.loads(block)
            if "name" in obj:
                results.append(obj)
        except json.JSONDecodeError:
            continue
    return results
```

Adjust this parser as you observe actual FunctionGemma output format. Log raw responses during development to calibrate.

## Config Update

```python
class RemoraConfig(BaseModel):
    agents_dir: Path = Path("agents")
    model_id: str = "ollama/functiongemma-4b-it"  # replaces per-agent GGUF paths
    runner: RunnerConfig = RunnerConfig()
    operations: dict[str, OperationConfig] = {}

class OperationConfig(BaseModel):
    subagent: str  # path to YAML relative to agents_dir
    # model_id can be overridden per-operation if needed
    model_id: str | None = None
```

## Ollama Setup (Developer Prerequisite)

This step assumes Ollama is installed and the FunctionGemma model is pulled:

```bash
# Install Ollama: https://ollama.com
ollama pull functiongemma-4b-it   # verify exact model name on Ollama Hub
```

Verify the model is reachable:
```bash
llm -m ollama/functiongemma-4b-it "Say hello"
```

Document this in `README.md` as a setup prerequisite.

## Testing Overview
- **Unit test:** `FunctionGemmaRunner` raises `AGENT_002` when given an unavailable model ID.
- **Unit test:** `_build_system_prompt()` includes the tool schema JSON.
- **Unit test:** `_parse_tool_calls()` correctly extracts tool calls from various FunctionGemma output formats (wrapped in ```json```, raw JSON, multiple calls).
- **Unit test:** Multi-turn loop dispatches tools and returns `AgentResult` on `submit_result`.
- **Unit test:** Loop raises `AGENT_003` when turn limit is hit.
- **Smoke test:** `llm -m ollama/functiongemma-4b-it "Call the greet tool with name=world"` returns a parseable tool call response.
