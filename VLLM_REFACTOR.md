# vLLM Python Client Integration — Refactor Plan

**Date:** 2026-02-18
**Current state:** Remora uses the `openai` Python SDK (`AsyncOpenAI`) pointed at a vLLM server's OpenAI-compatible endpoint (`/v1/chat/completions`)
**Target state:** Remora uses the `vllm` Python client library directly for inference, unlocking native vLLM capabilities

---

## 1. Background: Why Change?

The current approach uses the `openai` SDK as a generic HTTP client. This works because vLLM exposes an OpenAI-compatible REST API. However, it treats vLLM as a black box and cannot use any vLLM-specific functionality.

The `vllm` Python package includes a client-side library (`vllm.sampling_params`, `vllm.outputs`, and in newer releases, async client wrappers) that speaks the native vLLM API directly. Crucially, this API exposes features that have no equivalent in the OpenAI spec:

- **Guided JSON / structured outputs** — constrain the model to emit valid JSON matching a schema
- **`sampling_params` full control** — beam search, top-k, top-p, repetition penalties, stop sequences, etc.
- **Logprobs and token-level metadata** — know the model's confidence per token
- **Prompt-level prefix caching hints** — explicitly mark shared prefixes for KV cache reuse
- **LoRA adapter hot-swap via API** — specify adapter in the request, with validation
- **`best_of` / beam search** — generate N candidates and select the best
- **Per-request token budget enforcement** — reject requests that would exceed VRAM budget

---

## 2. What Needs to Change

### 2.1 `remora/client.py`

**Current:**
```python
from openai import AsyncOpenAI
from remora.config import ServerConfig

def build_client(server_config: ServerConfig) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
    )
```

**Target:**

Replace `AsyncOpenAI` with a vLLM async HTTP client. The vLLM project provides `vllm.entrypoints.openai.async_client.AsyncOpenAI` (for OpenAI-compat) but more importantly the lower-level `vllm.engine.async_llm_engine` for in-process use, or for remote use: the `openai`-compatible API remains the primary network interface.

However, the actual vLLM client-side library (`vllm` package installed on the client) provides:
- `from vllm import SamplingParams` — for parameterizing requests
- `from vllm.engine.arg_utils import AsyncEngineArgs` — for server config when embedding vLLM in-process

For **remote vLLM** (the remora deployment model — client talks to a vLLM server over the network), the recommended approach is to use vLLM's `openai`-compatible API but with the `vllm`-specific extensions in the request body.

The key change is adding a `vllm`-aware client wrapper that:
1. Continues using HTTP POST to `/v1/chat/completions`
2. Adds `extra_body` fields for vLLM-specific parameters (guided decoding, etc.)
3. Can optionally use the `vllm` client library directly when co-located

**File changes required:**
- `remora/client.py` — Replace `AsyncOpenAI` client builder with a `VLLMClient` wrapper
- `remora/config.py` — Add `VLLMConfig` section for vLLM-specific parameters
- `pyproject.toml` — Add `vllm` to dependencies (or `vllm-client` if/when available as separate package)

---

### 2.2 `remora/config.py`

Add a new configuration section for vLLM-specific parameters:

```python
class VLLMConfig(BaseModel):
    guided_json: bool = True           # Enable JSON schema-constrained decoding
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.0
    stop: list[str] = Field(default_factory=list)
    logprobs: int | None = None        # Number of top logprobs to return per token
    prompt_logprobs: int | None = None
    skip_special_tokens: bool = True
    max_logprobs: int = 20
```

Update `RemoraConfig`:
```python
class RemoraConfig(BaseModel):
    ...
    vllm: VLLMConfig = Field(default_factory=VLLMConfig)  # NEW
```

Also extend `RunnerConfig`:
```python
class RunnerConfig(BaseModel):
    max_turns: int = 20
    max_concurrent_runners: int = 16
    timeout: int = 300
    max_tokens: int = 512             # NEW — was hardcoded in runner.py:147
    temperature: float = 0.1          # NEW — was hardcoded in runner.py:148
```

---

### 2.3 `remora/runner.py`

This is where the largest change happens. The call to `_http_client.chat.completions.create()` needs to be updated to pass vLLM-specific parameters.

**Current `_call_model`:**
```python
response = await self._http_client.chat.completions.create(
    model=self._model_target,
    messages=cast(list[ChatCompletionMessageParam], self.messages),
    max_tokens=512,
    temperature=0.1,
)
```

**Target `_call_model`:**
```python
response = await self._http_client.chat.completions.create(
    model=self._model_target,
    messages=cast(list[ChatCompletionMessageParam], self.messages),
    max_tokens=self._runner_config.max_tokens,
    temperature=self._runner_config.temperature,
    extra_body={
        "guided_json": self._tool_call_schema() if self._vllm_config.guided_json else None,
        "top_p": self._vllm_config.top_p,
        "repetition_penalty": self._vllm_config.repetition_penalty,
        "stop": self._vllm_config.stop or None,
        "logprobs": self._vllm_config.logprobs,
        "skip_special_tokens": self._vllm_config.skip_special_tokens,
    },
)
```

Where `_tool_call_schema()` computes a JSON schema that constrains the model output to be a valid tool call object:
```python
def _tool_call_schema(self) -> dict:
    tool_names = [t.name for t in self.definition.tools]
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": tool_names},
                    "arguments": {"type": "object"},
                },
                "required": ["name"],
            }
        ]
    }
```

**Additional changes to `runner.py`:**

1. Add `runner_config: RunnerConfig` and `vllm_config: VLLMConfig` as dataclass fields
2. Use `self.runner_config.max_tokens` and `self.runner_config.temperature` instead of hardcoded values
3. Update `__post_init__` to receive the new config fields
4. Update `_call_model` to pass `extra_body`
5. Update `FunctionGemmaRunner` dataclass signature to accept the new fields

---

### 2.4 `remora/orchestrator.py`

Pass the new config sections through to `FunctionGemmaRunner`:

```python
# In process_node, when constructing runners:
runners[operation] = FunctionGemmaRunner(
    definition=definition,
    node=node,
    workspace_id=f"{operation}-{node.node_id}",
    cairn_client=self.cairn_client,
    server_config=self.config.server,
    runner_config=self.config.runner,   # NEW
    vllm_config=self.config.vllm,       # NEW
    adapter_name=op_config.model_id,
    http_client=self._http_client,
    event_emitter=self._event_emitter,
)
```

---

### 2.5 `pyproject.toml`

Add `vllm` to the dependency list. Note: the `vllm` package is large (~GB with CUDA dependencies). For client-only use (no local inference), there may be a lighter-weight option:

**Option A — Full vLLM client+server package:**
```toml
dependencies = [
    ...
    "vllm>=0.4.0",
]
```

**Option B — Use `openai` SDK with `extra_body` (no new dependency):**
The `openai` Python SDK supports passing arbitrary additional body parameters via `extra_body={}`. This approach requires **no new dependencies** and achieves the same result for remote vLLM, since vLLM's API is OpenAI-compatible and accepts these extra fields.

**Recommendation:** Use Option B initially (no new deps, immediate benefit from guided JSON), then evaluate adding `vllm` as a full dependency once in-process inference or logprob analysis is needed.

---

## 3. Additional Functionality Enabled by vLLM Integration

### 3.1 Guided JSON Decoding (Most Impactful)

**What it does:** vLLM's `guided_json` parameter accepts a JSON schema. The vLLM server uses constrained decoding (via `outlines` or `lm-format-enforcer`) to guarantee every token emitted conforms to the schema. The model literally cannot output invalid JSON.

**Impact on remora:**
- Eliminates the `_parse_tool_calls` regex heuristic entirely
- Eliminates `AGENT_003 / "Model stopped without calling submit_result"` errors caused by the model outputting plain text instead of JSON
- The `_coerce_tool_calls` fallback becomes unnecessary
- Tool call parsing becomes trivial: `json.loads(response_text)`

This is the single most impactful change. The errors shown in the problem statement (model responding with "I apologize, but I cannot assist...") are caused by the model generating plain text. With guided JSON, this is structurally impossible.

**How to use:**
```python
# Pass in extra_body to openai SDK call:
extra_body={
    "guided_json": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "enum": ["run_linter", "apply_fix", "submit_result"]},
            "arguments": {"type": "object"},
        },
        "required": ["name", "arguments"],
    }
}
```

### 3.2 Per-Turn SamplingParams Control

**What it does:** Different turns in the agent loop may benefit from different sampling parameters. For example:
- `model_load` (first turn) — lower temperature for more deterministic tool selection
- `loop` turns — slightly higher temperature for more exploratory reasoning
- Final turns near the limit — temperature=0 for greedy, deterministic completion

With native vLLM, `SamplingParams` can be constructed per-call and passed directly:
```python
from vllm import SamplingParams

params = SamplingParams(
    temperature=0.0 if self.turn_count > self.definition.max_turns - 2 else 0.1,
    max_tokens=512,
    guided_json=tool_schema,
)
```

### 3.3 Logprobs for Confidence-Aware Routing

**What it does:** vLLM can return per-token log probabilities alongside the response. This allows the orchestrator to:
- Detect when the model is "uncertain" about a tool call (low logprob on the tool name)
- Retry with a different sampling strategy when confidence is below a threshold
- Collect per-turn confidence metrics for monitoring and model evaluation

**Impact on remora:**
- New event field: `"tool_confidence": 0.87` in `tool_call` events
- New routing logic in `run()` to retry on low-confidence turns
- Enables automated quality scoring without human review

### 3.4 Token Budget Enforcement and Cost Estimation

**What it does:** vLLM exposes `prompt_tokens` and `completion_tokens` in every response (already captured by remora's event system). With the `vllm` client, you can also:
- Set `max_tokens` per-turn based on remaining budget
- Receive `finish_reason: "length"` when the model hits its token limit
- React to `finish_reason` in the agent loop (e.g., retry with a shorter prompt)

Currently remora logs token counts but does not use them for control flow. Integration enables:
```python
# In _call_model, after response:
if response.choices[0].finish_reason == "length":
    # Model hit token limit — summarize conversation and retry
    await self._summarize_and_continue()
```

### 3.5 Structured Output for `submit_result`

**What it does:** The `submit_result` tool has a well-defined schema per subagent. With guided JSON, the model can be constrained to emit a `submit_result` call whose `arguments` matches the exact schema of that subagent's submit tool.

This catches issues like:
- Docstring agent returns `action: "added"` but the AgentResult expects `status: "success"`
- Lint agent omits the required `issues_fixed` field
- Sample data agent returns extra fields that cause Pydantic `ValidationError`

With schema enforcement, these field mismatches are caught at the token level, not at parse time.

### 3.6 Multi-LoRA Adapter Validation

**What it does:** When remora targets a LoRA adapter (e.g., `model_id: "lint"` in `OperationConfig`), the vLLM server must have that adapter loaded. The vLLM client can enumerate loaded adapters via `GET /v1/models` before starting the run.

Currently `remora/config.py` only does a DNS check for the server. With the vLLM client, a pre-flight check can:
- List all loaded LoRA adapters
- Warn if a requested adapter is not loaded
- Fall back to the base model if an adapter is missing

### 3.7 Prefix Cache Warm-up

**What it does:** The system prompt for each operation (lint, docstring, etc.) is repeated for every single node. vLLM's prefix caching means the KV cache for the system prompt is shared across requests — but only if the system prompt bytes are identical.

With the vLLM client, you can:
- Pre-warm the prefix cache by sending a dummy request for each operation's system prompt before the main run
- Monitor `prefix_cache_hit_rate` via vLLM metrics to confirm caching is working
- Ensure system prompts are not padded or modified between calls (breaking cache hit)

This is particularly impactful for large codebases where the same system prompt is used for thousands of nodes.

### 3.8 Streaming Responses

**What it does:** vLLM supports streaming token-by-token output. For longer responses, streaming allows the remora TUI to show token generation in real time rather than waiting for the full response.

Currently remora waits for the complete response before processing. With streaming:
```python
async for chunk in client.chat.completions.create(..., stream=True):
    content += chunk.choices[0].delta.content or ""
    # Emit streaming event to TUI
```

This improves perceived responsiveness for users monitoring the dashboard.

---

## 4. Migration Sequence

The safest path to integration, from least to most invasive:

**Phase 1 — No new dependencies, immediate bug fix:**
- Add `extra_body={"guided_json": schema}` to the existing `openai` SDK call
- Move `max_tokens` and `temperature` to `RunnerConfig`
- This fixes the model-stops-without-calling-submit-result error

**Phase 2 — Config restructuring:**
- Add `VLLMConfig` to `RemoraConfig`
- Surface `top_p`, `repetition_penalty`, `stop` sequences as config options
- Add `finish_reason` handling in `run()`

**Phase 3 — Client refactor:**
- Replace the `openai.AsyncOpenAI` import with a thin `VLLMHttpClient` wrapper that handles `extra_body` natively
- Add pre-flight adapter validation against `/v1/models`
- Add prefix cache warm-up logic to `Coordinator`

**Phase 4 — In-process vLLM (optional, for single-machine deployments):**
- Add optional in-process `AsyncLLMEngine` mode that bypasses HTTP entirely
- This is only relevant if remora and the model are on the same machine

---

## 5. Files Changed Summary

| File | Change Type | Description |
|---|---|---|
| `remora/client.py` | Refactor | Replace `AsyncOpenAI` builder with `VLLMHttpClient` wrapper |
| `remora/config.py` | Addition | Add `VLLMConfig`, move `max_tokens`/`temperature` to `RunnerConfig` |
| `remora/runner.py` | Refactor | Use configurable params, pass `guided_json`, handle `finish_reason` |
| `remora/orchestrator.py` | Update | Pass `runner_config` and `vllm_config` to `FunctionGemmaRunner` |
| `pyproject.toml` | Update | Add `vllm>=0.4.0` (or use `openai` `extra_body` to avoid dep) |
| `tests/test_runner.py` | Update | Update `FakeAsyncOpenAI` to accept `extra_body` in `create()` |
| `tests/test_config.py` | Update | Add tests for `VLLMConfig` defaults and YAML loading |
| `remora.yaml.example` | Update | Document new `vllm:` config section |

---

## 6. Dependency Notes

The `vllm` package requires CUDA and is not installable in a pure CPU environment. If adding it as a hard dependency, it will break installation on developer machines without GPUs.

**Recommended approach:** Add `vllm` as an optional dependency:
```toml
[project.optional-dependencies]
vllm = ["vllm>=0.4.0"]
dev = ["pytest>=7.0", "pytest-cov>=4.1", "mypy>=1.10", "ruff>=0.5.0"]
```

For Phase 1 and 2 (guided JSON via `extra_body`), no new dependency is needed at all — the `openai` SDK's `extra_body` parameter passes arbitrary additional fields through to the server.
