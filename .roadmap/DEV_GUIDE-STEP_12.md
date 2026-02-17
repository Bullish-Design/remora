# DEV GUIDE STEP 12: Runner Adaptation for `openai` HTTP Client

## Goal
Replace the `llm`/Ollama integration in `FunctionGemmaRunner` with the OpenAI-compatible HTTP client for the vLLM server, keeping the multi-turn tool loop intact while moving inference to the Tailscale-hosted server.

## Why This Matters
vLLM centralizes inference, handles batching, and removes the need for local model weights. The client becomes a thin HTTP caller, unlocking true concurrency while keeping tool execution local.

## Implementation Checklist
- Update `pyproject.toml`: remove `llm` and `llm-ollama`; add `openai>=1.0`.
- Add `ServerConfig` to `RemoraConfig`; remove the top-level `model_id`.
- Treat `OperationConfig.model_id` as an adapter override (e.g. `"lint"`) and fall back to `server.default_adapter`.
- Remove the `ModelCache` singleton and any `llm` imports/shims.
- Add `remora/client.py` (shared `AsyncOpenAI` client builder) and pass it or `ServerConfig` into runners.
- Rewrite `FunctionGemmaRunner` to use `AsyncOpenAI.chat.completions.create`.
- Update `AGENT_002` to report vLLM server unreachability.
- Keep `_parse_tool_calls()` and tool schema injection logic unchanged.

## Suggested File Targets
- `pyproject.toml`
- `remora/config.py`
- `remora/runner.py`
- `remora/client.py`
- `remora/orchestrator.py`
- `remora/subagent.py`
- `remora/errors.py`

## Dependency Changes

```toml
# pyproject.toml — remove llm ecosystem, add OpenAI client
dependencies = [
    "typer",
    "rich",
    "pydantic",
    "pydantree",
    "cairn",
    "openai>=1.0",
    "jinja2",
    "watchfiles",
]
```

## Updated Runner Initialization

```python
from openai import AsyncOpenAI
from remora.config import ServerConfig

class FunctionGemmaRunner:
    def __init__(
        self,
        definition: SubagentDefinition,
        node: CSTNode,
        workspace_id: str,
        cairn_client: CairnClient,
        server_config: ServerConfig,
        adapter_name: str | None = None,
    ):
        self.definition = definition
        self.node = node
        self.workspace_id = workspace_id
        self.cairn = cairn_client
        self.server_config = server_config
        self.adapter_name = adapter_name
        self._model_target = adapter_name or server_config.default_adapter
        self._http_client = AsyncOpenAI(
            base_url=server_config.base_url,
            api_key=server_config.api_key,
            timeout=server_config.timeout,
        )
```

## Multi-Turn Loop with vLLM

```python
async def _call_model(self) -> str:
    response = await self._http_client.chat.completions.create(
        model=self._model_target,
        messages=self.messages,
        max_tokens=512,
        temperature=0.1,
    )
    return response.choices[0].message.content or ""
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
class ServerConfig(BaseModel):
    base_url: str = "http://function-gemma-server:8000/v1"
    api_key: str = "EMPTY"
    timeout: int = 120
    default_adapter: str = "google/functiongemma-270m-it"

class RemoraConfig(BaseModel):
    agents_dir: Path = Path("agents")
    server: ServerConfig = ServerConfig()
    runner: RunnerConfig = RunnerConfig()
    operations: dict[str, OperationConfig] = {}

class OperationConfig(BaseModel):
    subagent: str  # path to YAML relative to agents_dir
    # model_id can be overridden per-operation if needed
    model_id: str | None = None  # LoRA adapter name override
```

## vLLM Server Prerequisite

This step assumes the vLLM server is reachable on your Tailscale network:

```bash
uv run server/test_connection.py
```

Document this in `README.md` as a setup prerequisite.

## Testing Overview
- **Unit test:** `FunctionGemmaRunner` raises `AGENT_002` when the vLLM server is unreachable.
- **Unit test:** `_build_system_prompt()` includes the tool schema JSON.
- **Unit test:** `_parse_tool_calls()` correctly extracts tool calls from various FunctionGemma output formats (wrapped in ```json```, raw JSON, multiple calls).
- **Unit test:** Multi-turn loop dispatches tools and returns `AgentResult` on `submit_result`.
- **Unit test:** Loop raises `AGENT_003` when turn limit is hit.
- **Smoke test:** `uv run server/test_connection.py` returns a successful response.
