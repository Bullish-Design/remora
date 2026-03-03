# LLM Provider Abstraction: Multi-Provider Architecture for Remora

**Status:** Brainstorming / Analysis Document
**Date:** 2026-03-03
**Scope:** Making Remora's LLM interface provider-agnostic with per-call provider/model swapping

---

## Table of Contents

1. **[Current State Summary](#1-current-state-summary)** — How LLM calls flow today: the three code paths, single OpenAI-compatible client, global config, and where the bottlenecks are.

2. **[Goal and Requirements](#2-goal-and-requirements)** — Target state: any LLM API endpoint (OpenAI, Anthropic, Google Vertex, AWS Bedrock, Groq, Ollama, local vLLM), high-throughput async, per-call provider/model swapping.

3. **[Architecture Proposal: ProviderRegistry](#3-architecture-proposal-providerregistry)** — The core abstraction: provider interface extending/wrapping `LLMClient` Protocol, built-in providers, registry mapping provider names to client factories, connection pooling per provider+endpoint.

4. **[Per-Call Model Resolution](#4-per-call-model-resolution)** — How a single agent or node specifies its provider+model independently of its neighbors: extended `bundle.yaml`, extended `Config`, resolution flow through `create_kernel()`.

5. **[Config Design](#5-config-design)** — What `remora.yaml` looks like with multi-provider support, including YAML examples, environment variable expansion, and backward compatibility.

6. **[Impact Analysis](#6-impact-analysis)** — File-by-file breakdown of what changes, what stays the same, and the magnitude of each change.

7. **[Migration Path](#7-migration-path)** — Backward compatibility strategy, incremental adoption, and rollout phases.

8. **[Open Questions](#8-open-questions)** — Streaming differences, rate limiting per provider, cost tracking, provider-specific features (Anthropic thinking blocks, OpenAI structured outputs, vLLM grammar constraints), and other unresolved design decisions.

9. **[Library-Based Simplification Analysis](#9-library-based-simplification-analysis)** — Research into existing Python libraries (LiteLLM, LLM datasette, aisuite, instructor, magentic, PydanticAI) that could replace or simplify the custom multi-provider architecture proposed in Sections 3-7, including per-library fit analysis, comparison matrix, integration approaches for the top candidate, impact on the v1 architecture, and revised recommendations.

---

## 1. Current State Summary

### 1.1 The LLM Protocol Layer (`structured_agents`)

Remora's LLM access is mediated by the vendored `structured_agents` library (v0.3.4). The key abstractions:

| Type | File | Role |
|------|------|------|
| `LLMClient` (Protocol) | `structured_agents/client/protocol.py` | Defines `chat_completion()` — the single method all LLM access goes through |
| `CompletionResponse` | `structured_agents/client/protocol.py` | Normalized return type: `content`, `tool_calls`, `usage`, `finish_reason`, `raw_response` |
| `OpenAICompatibleClient` | `structured_agents/client/openai.py` | **The only concrete `LLMClient` implementation.** Wraps `AsyncOpenAI` from the `openai` package |
| `build_client(config)` | `structured_agents/client/openai.py` | Factory function — takes a config dict, returns `OpenAICompatibleClient`. **This is the sole client factory** |
| `ModelAdapter` | `structured_agents/models/adapter.py` | Adapts message/tool formatting per model family. Has `format_messages`, `format_tools`, `ResponseParser` |
| `AgentKernel` | `structured_agents/kernel.py` | The agent loop: takes `LLMClient` + `ModelAdapter` + tools + observer, runs step loop (model call -> tool exec -> repeat) |

The `LLMClient` Protocol is clean and minimal:

```python
class LLMClient(Protocol):
    model: str
    async def chat_completion(
        self, messages, tools, tool_choice, max_tokens, temperature, extra_body, model
    ) -> CompletionResponse: ...
    async def close(self) -> None: ...
```

This protocol is already provider-agnostic in design. The constraint is that `build_client()` only returns `OpenAICompatibleClient`, and all three Remora code paths call `build_client()`.

### 1.2 The Three Client Creation Code Paths

There are exactly three places in Remora that create LLM clients:

**Path 1: `kernel_factory.py` — The canonical factory**

```
create_kernel() → build_client() → OpenAICompatibleClient → AsyncOpenAI
```

`create_kernel()` (`src/remora/core/kernel_factory.py:18`) is the central factory. It accepts `model_name`, `base_url`, `api_key`, `timeout`, and an optional pre-built `client`. When no client is provided, it calls `build_client()`. It then creates a `ModelAdapter` (with model-specific `ResponseParser`) and returns an `AgentKernel`.

**Path 2: `swarm_executor.py` — Connection-pooled swarm mode**

```
SwarmExecutor.__init__() → build_client() → OpenAICompatibleClient (shared)
SwarmExecutor._run_kernel() → create_kernel(client=self._client) (reuses pooled client)
```

`SwarmExecutor` (`src/remora/core/swarm_executor.py:58`) creates a SINGLE `OpenAICompatibleClient` in `__init__` and reuses it for ALL agent runs. When it calls `create_kernel()`, it passes `client=self._client` to skip client creation. This is the connection pooling pattern — one `AsyncOpenAI` instance shared across agents.

Per-agent model name override exists via `_resolve_model_name()` (line 271) which reads `bundle.yaml` for `model.id`/`model.name`/`model.model`. But this only overrides the model name string — the endpoint and API key are always the global ones from `Config`.

**Path 3: `lsp/runner.py` — LSP agent runner**

```
LLMClient.__init__() → build_client() → OpenAICompatibleClient
AgentRunner uses self.llm (single LLMClient instance)
```

The LSP runner (`src/remora/lsp/runner.py:54`) has its own `LLMClient` wrapper class (confusingly named the same as the protocol). It wraps `build_client()` internally and adds a `chat()` method that normalizes the response into its own `LLMResponse` model. Created once per `AgentRunner` instance.

### 1.3 Configuration: Single Global Endpoint

`Config` (`src/remora/core/config.py:41`) has exactly three LLM-related fields:

```python
model_base_url: str = "http://localhost:8000/v1"
model_default: str = "Qwen/Qwen3-4B"
model_api_key: str = ""
```

These are flat, global, single-endpoint fields. There is no concept of multiple providers, no per-agent endpoint override, no provider type discriminator. The `bundle.yaml` per-agent override only changes the model *name* within the same endpoint.

### 1.4 `ChatSession` — No Connection Pooling

`ChatSession` (`src/remora/core/chat.py:91`) creates a NEW `AgentKernel` (and therefore a new `OpenAICompatibleClient` and `AsyncOpenAI` instance) on every `.send()` call. It does NOT pool connections. This is the interactive chat path, and each call opens a fresh HTTP connection.

### 1.5 Summary of Constraints

| Constraint | Location | Nature |
|-----------|----------|--------|
| Only one `LLMClient` implementation | `structured_agents/client/openai.py` | `OpenAICompatibleClient` using `AsyncOpenAI` |
| Only one client factory | `build_client()` in same file | Always returns `OpenAICompatibleClient` |
| Global single endpoint | `Config.model_base_url/model_api_key` | No per-provider config |
| Per-agent model name only | `bundle.yaml` + `_resolve_model_name()` | Model name, not endpoint/key |
| Inconsistent connection pooling | `SwarmExecutor` pools, `ChatSession` doesn't | Fragmented lifecycle |

---

## 2. Goal and Requirements

### 2.1 Core Goal

Make Remora capable of calling **any LLM API endpoint** — not just OpenAI-compatible servers — while preserving high-throughput async operation and enabling **per-call provider/model swapping** so that a single agent or node in a chain can use a different provider and model than its neighbors.

### 2.2 Target Providers

| Provider | API Style | SDK | Notes |
|----------|-----------|-----|-------|
| **vLLM** (local) | OpenAI-compatible | `openai` | Current default. Grammar/constrained decoding via `extra_body` |
| **OpenAI** | OpenAI native | `openai` | GPT-4o, o3, structured outputs, function calling |
| **Anthropic** | Anthropic Messages API | `anthropic` | Claude, thinking blocks, long context, different tool format |
| **Google Vertex / Gemini** | Google AI API | `google-genai` | Gemini models, multimodal, different auth (service account / API key) |
| **AWS Bedrock** | AWS API | `boto3` / `anthropic[bedrock]` | Claude/Titan/Llama via AWS, IAM auth |
| **Groq** | OpenAI-compatible | `openai` | Fast inference, OpenAI-compatible endpoint |
| **OpenRouter** | OpenAI-compatible | `openai` | Multi-model gateway, OpenAI-compatible |
| **Ollama** (local) | OpenAI-compatible | `openai` | Local models, OpenAI-compatible endpoint |
| **Together AI** | OpenAI-compatible | `openai` | Hosted open models, OpenAI-compatible |

Key observation: **Many providers are OpenAI-compatible.** The existing `OpenAICompatibleClient` already handles vLLM, Groq, OpenRouter, Ollama, Together, and OpenAI itself. The providers that truly need new client implementations are **Anthropic**, **Google**, and **AWS Bedrock**.

### 2.3 Requirements

**R1. Per-call provider/model swapping.** A single agent in a swarm can specify a different provider+model than the global default. Example: a code review agent uses Claude, while code generation agents use local vLLM, all in the same swarm run.

**R2. Connection pooling per provider+endpoint.** Each unique (provider_type, base_url) pair should share a single underlying HTTP client. No per-call connection setup overhead.

**R3. Unified `LLMClient` Protocol.** All providers must satisfy the existing `LLMClient` Protocol from `structured_agents`. The `AgentKernel` should not know or care which provider it is talking to.

**R4. Preserve `ModelAdapter` flexibility.** Provider-specific message formatting, tool formatting, and response parsing should flow through the existing `ModelAdapter` mechanism, not through ad-hoc provider branches.

**R5. Backward compatibility.** Existing `remora.yaml` files with flat `model_base_url` / `model_default` / `model_api_key` must continue to work unchanged.

**R6. No mandatory new dependencies.** Provider SDKs (anthropic, google-genai, boto3) should be optional extras. If you only use OpenAI-compatible providers, you don't need to install anything new.

**R7. Centralized configuration.** All provider configs live in `remora.yaml` under a `providers` dict. Environment variable expansion (`${VAR:-default}`) works for all values, especially API keys.

**R8. Observable.** The existing `Observer` pattern should capture which provider/model was used for each call, for debugging and cost tracking.

### 2.4 Non-Goals (for now)

- **Streaming.** The current architecture is request-response. Streaming support is valuable but orthogonal to provider abstraction. It can be layered on later.
- **Fallback/retry chains.** "If Anthropic fails, try OpenAI" logic is useful but adds complexity. Out of scope for the initial abstraction.
- **Load balancing across providers.** Running the same prompt against multiple providers and picking the best response. Research territory, not production architecture.
- **Provider-specific UI.** Displaying Anthropic thinking blocks or OpenAI structured output schemas in the frontend. The protocol normalizes to `CompletionResponse`; provider-specific rendering can be added incrementally.

---

## 3. Architecture Proposal: ProviderRegistry

### 3.1 Conceptual Overview

The design introduces three new concepts:

1. **`ProviderConfig`** — A data class describing how to connect to a specific provider (type, base_url, api_key, default_model, extra options).
2. **`ProviderRegistry`** — A singleton that maps provider names to `ProviderConfig` instances and maintains a pool of `LLMClient` instances keyed by (provider_name, base_url).
3. **Provider-specific `LLMClient` implementations** — `AnthropicClient`, `GoogleClient`, etc. that satisfy the existing `LLMClient` Protocol.

The flow becomes:

```
remora.yaml (providers section)
    ↓
ProviderRegistry (holds configs + connection pool)
    ↓
create_kernel(provider="anthropic", model="claude-sonnet-4-20250514")
    ↓
registry.get_client("anthropic") → cached AnthropicClient
    ↓
AgentKernel(client=anthropic_client, adapter=claude_adapter, ...)
```

### 3.2 `ProviderConfig` Data Class

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a single LLM provider."""
    
    name: str                          # e.g. "local", "openai", "anthropic"
    type: str                          # e.g. "openai_compatible", "anthropic", "google"
    base_url: str = ""                 # Required for openai_compatible; optional for native SDKs
    api_key: str = ""                  # API key (env var expanded before this point)
    default_model: str = ""            # Default model for this provider
    timeout: float = 300.0             # Request timeout in seconds
    max_tokens: int = 4096             # Default max tokens
    extra: dict = field(default_factory=dict)  # Provider-specific options
```

The `type` field is the discriminator that determines which `LLMClient` implementation to instantiate.

### 3.3 Provider Type Registry

```python
# Type alias for client factories
ClientFactory = Callable[[ProviderConfig], LLMClient]

# Built-in provider type mapping
_PROVIDER_TYPES: dict[str, ClientFactory] = {}

def register_provider_type(type_name: str, factory: ClientFactory) -> None:
    """Register a provider type with its client factory."""
    _PROVIDER_TYPES[type_name] = factory

def get_provider_factory(type_name: str) -> ClientFactory:
    """Get the client factory for a provider type."""
    if type_name not in _PROVIDER_TYPES:
        raise ConfigError(f"Unknown provider type: {type_name!r}. "
                         f"Available: {sorted(_PROVIDER_TYPES)}")
    return _PROVIDER_TYPES[type_name]
```

Built-in registrations (at module load):

```python
# Always available — uses the existing openai package
register_provider_type("openai_compatible", _build_openai_compatible)
register_provider_type("openai", _build_openai_compatible)  # alias

# Conditionally available — only if SDK is installed
try:
    from remora.core.providers.anthropic import _build_anthropic
    register_provider_type("anthropic", _build_anthropic)
except ImportError:
    pass

try:
    from remora.core.providers.google import _build_google
    register_provider_type("google", _build_google)
except ImportError:
    pass
```

### 3.4 `ProviderRegistry` — The Connection Pool

```python
class ProviderRegistry:
    """Registry of named providers with connection-pooled LLM clients."""
    
    def __init__(self, default_provider: str = "local"):
        self._configs: dict[str, ProviderConfig] = {}
        self._clients: dict[str, LLMClient] = {}  # Pooled by provider name
        self._default_provider = default_provider
    
    def register(self, config: ProviderConfig) -> None:
        """Register a provider configuration."""
        self._configs[config.name] = config
    
    def get_client(self, provider_name: str | None = None) -> LLMClient:
        """Get (or create) a pooled client for the named provider."""
        name = provider_name or self._default_provider
        
        if name not in self._configs:
            raise ConfigError(f"Unknown provider: {name!r}. "
                            f"Available: {sorted(self._configs)}")
        
        if name not in self._clients:
            config = self._configs[name]
            factory = get_provider_factory(config.type)
            self._clients[name] = factory(config)
        
        return self._clients[name]
    
    def get_config(self, provider_name: str | None = None) -> ProviderConfig:
        """Get the configuration for a named provider."""
        name = provider_name or self._default_provider
        if name not in self._configs:
            raise ConfigError(f"Unknown provider: {name!r}")
        return self._configs[name]
    
    def resolve_model(self, provider_name: str | None, model_name: str | None) -> tuple[str, str]:
        """Resolve provider + model, falling back to defaults.
        
        Returns (provider_name, model_name).
        """
        pname = provider_name or self._default_provider
        config = self._configs.get(pname)
        if config is None:
            raise ConfigError(f"Unknown provider: {pname!r}")
        mname = model_name or config.default_model
        return (pname, mname)
    
    @property
    def default_provider(self) -> str:
        return self._default_provider
    
    async def close_all(self) -> None:
        """Close all pooled clients."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
```

Key design decisions:

- **Clients are pooled by provider name**, not by (type, base_url). Each named provider gets exactly one client instance. This is simple and covers the common case. If you need two different OpenAI endpoints, you configure two named providers.
- **Lazy client creation.** Clients are created on first `get_client()` call, not at registry construction time. This avoids creating connections to providers that are configured but never used.
- **The registry replaces `SwarmExecutor._client`.** Instead of `SwarmExecutor` doing its own `build_client()`, it uses `registry.get_client()`.

### 3.5 Built-in Provider Implementations

#### 3.5.1 OpenAI-Compatible (existing)

This is just the existing `OpenAICompatibleClient` wrapped in the factory pattern:

```python
def _build_openai_compatible(config: ProviderConfig) -> LLMClient:
    """Build an OpenAI-compatible client. Covers: OpenAI, vLLM, Groq, Ollama, etc."""
    return OpenAICompatibleClient(
        base_url=config.base_url or "https://api.openai.com/v1",
        api_key=config.api_key or "EMPTY",
        model=config.default_model,
        timeout=config.timeout,
    )
```

No new code needed — we're reusing the existing class.

#### 3.5.2 Anthropic Client (new)

```python
# remora/core/providers/anthropic.py
from anthropic import AsyncAnthropic
from structured_agents.client.protocol import CompletionResponse, LLMClient

class AnthropicClient:
    """Anthropic API client satisfying the LLMClient protocol."""
    
    def __init__(self, api_key: str, model: str, timeout: float = 300.0):
        self.model = model
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout)
    
    async def chat_completion(
        self, messages, tools=None, tool_choice="auto",
        max_tokens=4096, temperature=0.1, extra_body=None, model=None,
    ) -> CompletionResponse:
        # Convert OpenAI-format messages to Anthropic format
        system_msg, user_msgs = self._split_system(messages)
        
        kwargs = {
            "model": model or self.model,
            "messages": user_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            # Anthropic uses {"type": "auto"} not "auto" string
            kwargs["tool_choice"] = {"type": tool_choice}
        
        response = await self._client.messages.create(**kwargs)
        return self._to_completion_response(response)
    
    def _split_system(self, messages):
        """Split system message from user/assistant messages.
        
        Anthropic requires system as a top-level param, not in messages array.
        """
        system = None
        others = []
        for msg in messages:
            if msg.get("role") == "system":
                system = msg.get("content", "")
            else:
                others.append(msg)
        return system, others
    
    def _convert_tools(self, tools):
        """Convert OpenAI tool format to Anthropic tool format.
        
        OpenAI: [{"type": "function", "function": {"name": ..., "parameters": ...}}]
        Anthropic: [{"name": ..., "input_schema": ...}]
        """
        result = []
        for tool in tools:
            func = tool.get("function", tool)
            result.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object"}),
            })
        return result
    
    def _to_completion_response(self, response) -> CompletionResponse:
        """Convert Anthropic response to CompletionResponse."""
        content = ""
        tool_calls = []
        
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    },
                })
        
        usage = TokenUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        ) if response.usage else None
        
        return CompletionResponse(
            content=content or None,
            tool_calls=tool_calls or None,
            usage=usage,
            finish_reason=response.stop_reason,
            raw_response={"model": response.model, "id": response.id},
        )
    
    async def close(self):
        await self._client.close()
```

#### 3.5.3 Google Client (sketch)

```python
# remora/core/providers/google.py — sketch only
from google import genai

class GoogleClient:
    """Google Gemini/Vertex client satisfying LLMClient protocol."""
    
    def __init__(self, api_key: str, model: str, ...):
        self.model = model
        self._client = genai.Client(api_key=api_key)
    
    async def chat_completion(self, messages, tools=None, ...) -> CompletionResponse:
        # Convert to Google's format, call API, convert back
        ...
```

The Google and Bedrock clients follow the same pattern: implement `chat_completion()` by converting to/from the native SDK format and returning a `CompletionResponse`.

### 3.6 Where This Lives in the Codebase

Proposed file structure:

```
src/remora/core/
├── providers/
│   ├── __init__.py          # ProviderConfig, ProviderRegistry, register_provider_type()
│   ├── openai_compat.py     # _build_openai_compatible (thin wrapper around existing)
│   ├── anthropic.py         # AnthropicClient + _build_anthropic
│   └── google.py            # GoogleClient + _build_google
├── kernel_factory.py        # Updated to accept provider_name + registry
├── config.py                # Extended with providers dict
└── ...
```

The `providers/__init__.py` module is the entry point. It exports `ProviderRegistry`, `ProviderConfig`, and auto-registers the built-in provider types.

---

## 4. Per-Call Model Resolution

This is the core requirement: any single agent or node can use a different provider+model than the global default. The resolution flows through three layers.

### 4.1 Resolution Hierarchy (Most Specific Wins)

```
1. Explicit override on create_kernel() call   ← highest priority
2. bundle.yaml per-agent config                ← agent-level
3. Provider's default_model                    ← provider-level
4. Config.model_default + default_provider     ← global fallback
```

At each level, two values are resolved: **provider name** and **model name**. If a level specifies only one, the other falls through to the next level.

### 4.2 Extended `bundle.yaml`

Currently, `bundle.yaml` supports:

```yaml
model:
  id: "Qwen/Qwen3-4B"    # model name only
```

Extended to:

```yaml
model:
  id: "claude-sonnet-4-20250514"
  provider: "anthropic"              # NEW: which named provider to use
  # Optionally override provider-level defaults:
  # base_url: "https://custom-endpoint.example.com"
  # api_key: "${CUSTOM_KEY}"
```

The `provider` field references a named provider from the `providers` section of `remora.yaml`. This is the mechanism for per-agent provider swapping.

### 4.3 Extended `_resolve_model_name()` → `_resolve_model_spec()`

The existing `SwarmExecutor._resolve_model_name()` (line 271) returns just a string. It becomes `_resolve_model_spec()` returning a `ModelSpec`:

```python
@dataclass(frozen=True)
class ModelSpec:
    """Resolved provider + model for a single agent call."""
    provider_name: str | None = None   # None means "use default"
    model_name: str | None = None      # None means "use provider's default"

def _resolve_model_spec(self, bundle_path: Path, manifest: Any) -> ModelSpec:
    """Read bundle.yaml for provider and model overrides."""
    path = bundle_path / "bundle.yaml" if bundle_path.is_dir() else bundle_path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        model_data = data.get("model")
        if isinstance(model_data, dict):
            provider = model_data.get("provider")   # NEW
            model_id = (model_data.get("id") 
                       or model_data.get("name") 
                       or model_data.get("model"))
            return ModelSpec(provider_name=provider, model_name=model_id)
    except Exception:
        pass
    return ModelSpec()
```

### 4.4 Updated `create_kernel()` Signature

The central factory gains optional `provider_name` and `registry` parameters:

```python
def create_kernel(
    *,
    model_name: str | None = None,
    base_url: str | None = None,          # Kept for backward compat
    api_key: str | None = None,           # Kept for backward compat
    timeout: float = 300.0,
    tools: list[Any] | None = None,
    observer: Any | None = None,
    grammar_config: Any | None = None,
    client: Any | None = None,
    # NEW parameters:
    provider_name: str | None = None,
    registry: ProviderRegistry | None = None,
) -> AgentKernel:
    """Create an AgentKernel with provider-aware client resolution.
    
    Resolution order:
    1. If `client` is provided, use it directly (existing behavior).
    2. If `registry` is provided, use it to get/create a pooled client
       for the specified `provider_name`.
    3. Fall back to `build_client()` with base_url/api_key (legacy path).
    """
    if client is None:
        if registry is not None:
            # New path: provider-aware
            pname, mname = registry.resolve_model(provider_name, model_name)
            client = registry.get_client(pname)
            model_name = mname
        else:
            # Legacy path: direct build_client
            client = build_client({
                "base_url": base_url or "http://localhost:8000/v1",
                "api_key": api_key or "EMPTY",
                "model": model_name or "default",
                "timeout": timeout,
            })
    
    parser = get_response_parser(model_name or "default")
    pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
    adapter = ModelAdapter(
        name=model_name or "default",
        response_parser=parser,
        constraint_pipeline=pipeline,
    )
    
    return AgentKernel(
        client=client,
        adapter=adapter,
        tools=tools or [],
        observer=observer,
    )
```

**Key insight:** When using the registry path, `create_kernel()` gets a pooled client from the registry and uses the resolved model name for the `ModelAdapter`. The client itself carries its own default model, but `model_name` can override it per-call via the `model` parameter on `chat_completion()`.

### 4.5 Updated `SwarmExecutor` Flow

```python
class SwarmExecutor:
    def __init__(self, config, event_bus, event_store, ...):
        ...
        # BEFORE: self._client = build_client({...})
        # AFTER:
        self._registry = build_registry_from_config(config)
    
    async def _run_kernel(self, manifest, prompt, tools, *, 
                          model_spec: ModelSpec, ...):
        ...
        kernel = create_kernel(
            model_name=model_spec.model_name,
            provider_name=model_spec.provider_name,
            registry=self._registry,
            timeout=self.config.timeout_s,
            tools=tools,
            observer=observer,
            grammar_config=manifest.grammar_config if manifest.grammar_config else None,
        )
        # Note: no more `client=self._client` — the registry handles pooling
```

The `SwarmExecutor` no longer manages its own client. The `ProviderRegistry` handles connection pooling across all providers.

### 4.6 Per-Call Model Override in `AgentKernel`

The `LLMClient` Protocol already supports per-call model override:

```python
async def chat_completion(self, ..., model: str | None = None) -> CompletionResponse:
```

And `OpenAICompatibleClient` already uses it:

```python
kwargs["model"] = model or self.model
```

So even if multiple agents share the same pooled client, each can specify a different model name. The client instance is shared (connection pooling), but the model name can vary per call. This is the mechanism that enables per-agent model switching within a single provider.

### 4.7 Full Resolution Flow Example

Scenario: A swarm with three agents, each using a different provider+model.

```yaml
# remora.yaml
providers:
  local:
    type: openai_compatible
    base_url: http://localhost:8000/v1
    api_key: EMPTY
    default_model: Qwen/Qwen3-4B
  openai:
    type: openai
    api_key: ${OPENAI_API_KEY}
    default_model: gpt-4o
  anthropic:
    type: anthropic
    api_key: ${ANTHROPIC_API_KEY}
    default_model: claude-sonnet-4-20250514
default_provider: local
```

```yaml
# agents/code-gen/bundle.yaml — uses default (local vLLM)
model:
  id: Qwen/Qwen3-4B

# agents/code-review/bundle.yaml — uses Anthropic
model:
  id: claude-sonnet-4-20250514
  provider: anthropic

# agents/summarizer/bundle.yaml — uses OpenAI
model:
  id: gpt-4o-mini
  provider: openai
```

Resolution for each agent:

| Agent | bundle.yaml | Resolved Provider | Resolved Model | Client Used |
|-------|-------------|-------------------|----------------|-------------|
| code-gen | `id: Qwen/Qwen3-4B` (no provider) | `local` (default) | `Qwen/Qwen3-4B` | Pooled `OpenAICompatibleClient` → localhost:8000 |
| code-review | `provider: anthropic, id: claude-sonnet-4-20250514` | `anthropic` | `claude-sonnet-4-20250514` | Pooled `AnthropicClient` |
| summarizer | `provider: openai, id: gpt-4o-mini` | `openai` | `gpt-4o-mini` | Pooled `OpenAICompatibleClient` → api.openai.com |

All three agents run concurrently in the same swarm. Each gets a different pooled client. The `code-gen` and `summarizer` agents both use `OpenAICompatibleClient` but with different base URLs (and therefore different pooled instances).

---

## 5. Config Design

### 5.1 New `remora.yaml` Format

The new format adds a `providers` dict and a `default_provider` field alongside the existing flat fields:

```yaml
# remora.yaml — full multi-provider example

project_path: "."
discovery_paths: ["src/"]

# === NEW: Provider configurations ===
providers:
  local:
    type: openai_compatible
    base_url: http://localhost:8000/v1
    api_key: EMPTY
    default_model: Qwen/Qwen3-4B
    timeout: 300

  openai:
    type: openai
    # No base_url needed — openai type defaults to https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    default_model: gpt-4o
    timeout: 120

  anthropic:
    type: anthropic
    api_key: ${ANTHROPIC_API_KEY}
    default_model: claude-sonnet-4-20250514
    timeout: 120

  groq:
    type: openai_compatible
    base_url: https://api.groq.com/openai/v1
    api_key: ${GROQ_API_KEY}
    default_model: llama-3.3-70b-versatile
    timeout: 60

  ollama:
    type: openai_compatible
    base_url: http://localhost:11434/v1
    api_key: EMPTY
    default_model: qwen2.5:7b

default_provider: local

# === LEGACY: Flat model fields (still supported for backward compat) ===
# model_base_url: http://localhost:8000/v1
# model_default: Qwen/Qwen3-4B
# model_api_key: ""

# Everything else unchanged
bundle_root: agents
swarm_root: .remora
max_concurrency: 4
max_turns: 8
timeout_s: 300
```

### 5.2 Extended `Config` Class

```python
class ProviderConfigModel(BaseModel):
    """Pydantic model for a single provider in remora.yaml."""
    type: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    timeout: float = 300.0
    extra: dict = Field(default_factory=dict)

class Config(BaseSettings):
    """Remora configuration with multi-provider support."""
    
    model_config = SettingsConfigDict(env_prefix="REMORA_")
    
    # ... existing fields unchanged ...
    
    # Legacy flat model fields (backward compat)
    model_base_url: str = "http://localhost:8000/v1"
    model_default: str = "Qwen/Qwen3-4B"
    model_api_key: str = ""
    
    # NEW: Multi-provider config
    providers: dict[str, ProviderConfigModel] = Field(default_factory=dict)
    default_provider: str = ""
```

### 5.3 Building the Registry from Config

A factory function bridges `Config` → `ProviderRegistry`:

```python
def build_registry_from_config(config: Config) -> ProviderRegistry:
    """Build a ProviderRegistry from a Config object.
    
    If config.providers is populated, uses that.
    Otherwise, synthesizes a single provider from the legacy flat fields.
    """
    if config.providers:
        # New-style multi-provider config
        default_name = config.default_provider or next(iter(config.providers))
        registry = ProviderRegistry(default_provider=default_name)
        for name, pconfig in config.providers.items():
            registry.register(ProviderConfig(
                name=name,
                type=pconfig.type,
                base_url=pconfig.base_url,
                api_key=pconfig.api_key,
                default_model=pconfig.default_model,
                timeout=pconfig.timeout,
                extra=pconfig.extra,
            ))
        return registry
    
    # Legacy fallback: synthesize a single "default" provider
    registry = ProviderRegistry(default_provider="default")
    registry.register(ProviderConfig(
        name="default",
        type="openai_compatible",
        base_url=config.model_base_url,
        api_key=config.model_api_key,
        default_model=config.model_default,
        timeout=config.timeout_s,
    ))
    return registry
```

This is the backward compatibility bridge. Existing configs with just `model_base_url` / `model_default` / `model_api_key` automatically get a single "default" provider. No changes required to existing YAML files.

### 5.4 Environment Variable Expansion

The existing `_expand_env_vars()` in `config.py` already recursively expands `${VAR:-default}` patterns in all string values. This works automatically for the nested `providers` dict — no changes needed. API keys in the providers section like `${OPENAI_API_KEY}` are expanded before Pydantic validation.

### 5.5 Environment Variable Overrides

Pydantic Settings with `env_prefix="REMORA_"` allows env var overrides. For the flat fields this already works (`REMORA_MODEL_BASE_URL`, etc.). For nested provider config, the env var approach doesn't compose well. Two options:

**Option A: Keep env vars for legacy fields only.** The `providers` dict is always configured in YAML, with `${VAR}` expansion for secrets. This is the simpler path and matches how most tools work (secrets in env, structure in config file).

**Option B: Add `REMORA_PROVIDERS` as a JSON string env var.** This is ugly and fragile. Not recommended.

Recommendation: **Option A.** Env var overrides for the flat fields provide the escape hatch for simple deployments. Multi-provider configs go in the YAML file.

---

## 6. Impact Analysis

File-by-file assessment of what changes, what stays the same, and the magnitude of each change.

### 6.1 New Files

| File | Description | Size Estimate |
|------|-------------|---------------|
| `src/remora/core/providers/__init__.py` | `ProviderConfig`, `ProviderRegistry`, `register_provider_type()`, `build_registry_from_config()` | ~150 lines |
| `src/remora/core/providers/openai_compat.py` | `_build_openai_compatible()` factory — thin wrapper around existing `OpenAICompatibleClient` | ~20 lines |
| `src/remora/core/providers/anthropic.py` | `AnthropicClient` implementing `LLMClient` Protocol, `_build_anthropic()` factory | ~120 lines |
| `src/remora/core/providers/google.py` | `GoogleClient` (stub/sketch initially) | ~100 lines |

### 6.2 Modified Files — Remora Core

#### `src/remora/core/config.py` — **Small change**

- Add `ProviderConfigModel` Pydantic model (~10 lines)
- Add `providers: dict[str, ProviderConfigModel]` and `default_provider: str` to `Config` (~3 lines)
- Existing fields and logic unchanged
- `_expand_env_vars()` already handles nested dicts — no changes needed

**Risk: Low.** Additive change only. Existing configs continue to work.

#### `src/remora/core/kernel_factory.py` — **Medium change**

- Add optional `provider_name` and `registry` parameters to `create_kernel()`
- Add registry-based resolution branch before the legacy `build_client()` branch
- All existing callers continue to work — new params default to `None`

**Before:**
```python
def create_kernel(*, model_name, base_url, api_key, timeout, tools, observer, grammar_config, client):
```

**After:**
```python
def create_kernel(*, model_name, base_url=None, api_key=None, timeout, tools, observer, grammar_config, client, provider_name=None, registry=None):
```

**Risk: Low-Medium.** The function signature changes, but all new params are optional with backward-compatible defaults. Existing callers pass `base_url` and `api_key` explicitly, which continues to work via the legacy branch.

#### `src/remora/core/swarm_executor.py` — **Medium change**

- Replace `self._client = build_client(...)` in `__init__` with `self._registry = build_registry_from_config(config)`
- Replace `_resolve_model_name()` with `_resolve_model_spec()` returning `ModelSpec`
- Update `_run_kernel()` to pass `provider_name` + `registry` instead of `client=self._client`
- Remove `build_client` import, add `providers` imports

**Risk: Medium.** This is the most structurally impacted file. The client creation and model resolution logic both change. Tests for `SwarmExecutor` will need updating.

#### `src/remora/core/chat.py` — **Small change**

- `ChatConfig` optionally gains `provider_name` field
- `ChatSession.send()` can pass `registry` to `create_kernel()` if available
- Or: `ChatSession` continues to use the legacy path (base_url + api_key) for simplicity
- `ChatConfig.from_config()` could optionally accept a registry

**Risk: Low.** The chat session can adopt the new pattern incrementally. The legacy path continues to work.

### 6.3 Modified Files — LSP Layer

#### `src/remora/lsp/runner.py` — **Medium change**

- `LLMClient` wrapper class should be updated to accept a `ProviderRegistry` or a pre-built `LLMClient` (from `structured_agents`)
- Or: `AgentRunner` accepts a `ProviderRegistry` and resolves per-agent clients internally
- The `get_agent_tools()` and tool loop logic is unaffected — it only consumes the `LLMResponse` output

Two sub-options:

**Option A: Registry-aware LLMClient wrapper.** The `runner.py` `LLMClient` class takes a registry and resolves per-call:
```python
class LLMClient:
    def __init__(self, registry: ProviderRegistry):
        self._registry = registry
    
    async def chat(self, messages, tools, *, provider_name=None, model=None):
        client = self._registry.get_client(provider_name)
        response = await client.chat_completion(messages=messages, tools=tools, model=model)
        return self._normalize(response)
```

**Option B: Per-agent client resolution in AgentRunner.** The `AgentRunner.execute_turn()` method resolves the provider from the agent's metadata and gets the appropriate client.

Recommendation: **Option B.** It keeps the resolution logic close to where agent metadata is available and doesn't require changing the `LLMClient` wrapper's interface.

**Risk: Medium.** The LSP runner currently has a single `self.llm` for all agents. Making it per-agent requires passing the registry through and resolving at turn execution time.

### 6.4 Modified Files — `structured_agents` (Vendored)

#### `structured_agents/client/protocol.py` — **No change needed**

The `LLMClient` Protocol is already correct. New provider implementations just need to satisfy this protocol.

#### `structured_agents/client/openai.py` — **No change needed**

The `OpenAICompatibleClient` and `build_client()` stay as-is. The new provider registry wraps them; it doesn't modify them.

#### `structured_agents/kernel.py` — **No change needed**

`AgentKernel` takes any `LLMClient` via duck typing. It doesn't care whether it's `OpenAICompatibleClient` or `AnthropicClient`.

#### `structured_agents/models/adapter.py` — **Possibly small change**

If Anthropic or Google require different `ResponseParser` behavior, new parsers may be needed in `structured_agents/models/parsers.py`. The existing `get_response_parser(model_name)` function would need to recognize Anthropic/Google model names and return appropriate parsers.

However, since the new provider clients already normalize responses to `CompletionResponse` format (including converting tool calls to OpenAI format), the existing default parser may work for all providers. This needs testing.

**Risk: Low.** The normalization happens in the provider client, before the response reaches the parser.

### 6.5 Unchanged Files

These files are not affected by the provider abstraction:

- `src/remora/core/agent_node.py` — No LLM interaction
- `src/remora/core/agent_context.py` — No LLM interaction
- `src/remora/core/event_store.py` — No LLM interaction
- `src/remora/core/event_bus.py` — No LLM interaction
- `src/remora/core/subscriptions.py` — No LLM interaction
- `src/remora/core/discovery.py` — No LLM interaction
- `src/remora/core/workspace.py` — No LLM interaction
- `src/remora/core/tools/` — Tools are LLM-agnostic
- `src/remora/lsp/models.py` — Event models are LLM-agnostic
- `src/remora/lsp/handlers/` — Handlers dispatch to runner, don't touch LLM directly

### 6.6 Summary Table

| File | Change Type | Magnitude | Risk |
|------|-------------|-----------|------|
| `providers/__init__.py` | NEW | ~150 lines | Low (new module) |
| `providers/openai_compat.py` | NEW | ~20 lines | Low |
| `providers/anthropic.py` | NEW | ~120 lines | Medium (SDK integration) |
| `providers/google.py` | NEW | ~100 lines | Medium (SDK integration) |
| `core/config.py` | MODIFY | ~15 lines added | Low |
| `core/kernel_factory.py` | MODIFY | ~20 lines changed | Low-Medium |
| `core/swarm_executor.py` | MODIFY | ~40 lines changed | Medium |
| `core/chat.py` | MODIFY | ~10 lines changed | Low |
| `lsp/runner.py` | MODIFY | ~30 lines changed | Medium |
| `structured_agents/*` | UNCHANGED | 0 | None |

Total new code: ~390 lines. Total modified code: ~115 lines changed across 4 existing files.

---

## 7. Migration Path

### 7.1 Guiding Principle: Zero Breaking Changes

The entire migration is designed so that **existing `remora.yaml` files and `bundle.yaml` files work without modification.** The new provider system is purely additive. Users opt in by adding a `providers` section to their config.

### 7.2 Phase 1 — Core Abstraction (No New Providers)

**Goal:** Introduce `ProviderRegistry` and `ProviderConfig`, wire them through `create_kernel()` and `SwarmExecutor`, but only ship the `openai_compatible` provider type. This is a pure refactor — behavior is identical.

Steps:

1. Create `src/remora/core/providers/__init__.py` with `ProviderConfig`, `ProviderRegistry`, `build_registry_from_config()`.
2. Create `src/remora/core/providers/openai_compat.py` — thin wrapper calling existing `OpenAICompatibleClient`.
3. Add `providers` and `default_provider` fields to `Config`.
4. Update `kernel_factory.py` to accept optional `registry` + `provider_name`.
5. Update `SwarmExecutor.__init__` to build a registry instead of a raw client.
6. Update `SwarmExecutor._run_kernel()` to use the registry.
7. Update `_resolve_model_name()` → `_resolve_model_spec()`.

**Validation:** All existing tests pass. Existing `remora.yaml` files work via the `build_registry_from_config()` legacy fallback. The swarm executor behaves identically — it just gets its `OpenAICompatibleClient` from the registry instead of building it directly.

### 7.3 Phase 2 — Anthropic Provider

**Goal:** Add the first non-OpenAI provider.

Steps:

1. Create `src/remora/core/providers/anthropic.py` with `AnthropicClient`.
2. Register `"anthropic"` provider type (conditionally, behind `try/except ImportError`).
3. Add `anthropic` as an optional dependency in `pyproject.toml` extras: `remora[anthropic]`.
4. Write integration tests using a mock Anthropic server or the real API with a test key.
5. Verify that a `bundle.yaml` with `provider: anthropic` correctly routes to the Anthropic client while other agents in the same swarm use the default provider.

**Validation:** Mixed-provider swarm test: one agent on local vLLM, one on Anthropic, running concurrently.

### 7.4 Phase 3 — LSP Runner Integration

**Goal:** Bring the LSP runner (`lsp/runner.py`) into the provider system.

Steps:

1. Modify `AgentRunner` to accept a `ProviderRegistry`.
2. In `execute_turn()`, resolve the agent's provider from its metadata / bundle config.
3. Replace the single `self.llm` with per-turn client resolution from the registry.
4. The `LLMClient` wrapper class in `runner.py` either becomes a thin shim over the registry or is removed entirely.

**Validation:** LSP-driven agent activation works with mixed providers.

### 7.5 Phase 4 — Chat Session & Additional Providers

**Goal:** Extend to the remaining code paths and add more providers.

Steps:

1. Update `ChatSession` to optionally use a registry (or keep the legacy path for simple usage).
2. Add Google/Vertex provider.
3. Add Bedrock provider.
4. Add any provider-specific `ModelAdapter` or `ResponseParser` variants if needed.

### 7.6 Deprecation Timeline

The flat `model_base_url` / `model_default` / `model_api_key` fields are NOT deprecated immediately. They remain as the simple-deployment path. The `build_registry_from_config()` function ensures they always work.

Potential future deprecation: If the `providers` section becomes the universal standard, the flat fields could emit a deprecation warning in a future major version. But there's no urgency — they're not harmful, and they provide a convenient simple case.

---

## 8. Open Questions

### 8.1 Streaming Support

**Problem:** The current `LLMClient` Protocol is request-response only. `chat_completion()` returns a complete `CompletionResponse`. Streaming (SSE/chunked responses) requires a different return type — an async iterator of chunks.

**Options:**

- **A) Separate method.** Add `chat_completion_stream()` to the Protocol that returns `AsyncIterator[CompletionChunk]`. Providers implement both. The `AgentKernel` uses the non-streaming version (as today); streaming is used at the UI layer.
- **B) Flag parameter.** Add `stream: bool = False` to `chat_completion()`. When `True`, return type changes. This is type-unsafe and awkward.
- **C) Defer.** Streaming is orthogonal to provider abstraction. Implement provider abstraction first, add streaming later with a clean interface.

**Recommendation:** Option C for now, Option A when streaming is needed. The provider abstraction should not be blocked on streaming design.

### 8.2 Provider-Specific Features

Each provider has unique capabilities that don't map cleanly to the unified `CompletionResponse`:

| Provider | Unique Feature | How It Works |
|----------|---------------|--------------|
| **Anthropic** | Thinking blocks (`<thinking>`) | Extended thinking is returned as a separate content block with `type: "thinking"`. Currently lost in normalization. |
| **Anthropic** | Prompt caching | Requires `cache_control` on messages. Could be passed via `extra_body`. |
| **OpenAI** | Structured Outputs | `response_format: {"type": "json_schema", ...}`. Could be passed via `extra_body`. |
| **vLLM** | Grammar/constrained decoding | Already handled via `extra_body` → `ConstraintPipeline`. Works today. |
| **Google** | Multimodal (images, video) | Messages can contain image parts. Not supported by current `Message` type. |
| **OpenAI** | Reasoning tokens (o3) | Usage breakdown includes reasoning tokens. Lost in `TokenUsage` normalization. |

**Approach:** The `extra_body` parameter on `chat_completion()` is the escape hatch for provider-specific features. Provider clients can interpret `extra_body` keys specific to their provider. For example:

```python
# Anthropic thinking blocks
extra_body={"thinking": {"type": "enabled", "budget_tokens": 10000}}

# OpenAI structured outputs
extra_body={"response_format": {"type": "json_schema", "json_schema": {...}}}
```

The `CompletionResponse.raw_response` field preserves the full provider response for callers that need provider-specific data. The normalization to `content` + `tool_calls` covers 95% of use cases.

**Thinking blocks specifically:** If Anthropic thinking blocks are important for Remora's agent reasoning, `CompletionResponse` could gain an optional `thinking: str | None` field. This is a small, backward-compatible addition.

### 8.3 Rate Limiting

**Problem:** Different providers have different rate limits (RPM, TPM). A swarm running 4 agents concurrently against Anthropic might hit rate limits that wouldn't be an issue with local vLLM.

**Options:**

- **A) Per-provider semaphore in the registry.** `ProviderConfig` gains `max_concurrency: int`, and `get_client()` returns a rate-limited wrapper.
- **B) Token bucket per provider.** More sophisticated, handles TPM limits.
- **C) Defer to retry logic.** Just retry on 429 with exponential backoff.

**Recommendation:** Start with Option C (retry on 429) since most provider SDKs handle this internally. Add Option A if rate limiting becomes a practical problem.

### 8.4 Cost Tracking

**Problem:** Different providers charge different amounts. When agents use different providers, tracking cost per agent becomes valuable.

**Approach:** The `Observer` pattern already captures `TokenUsage` per model call via `ModelResponseEvent`. The `ModelRequestEvent` already includes the model name. Extending this to include the provider name is trivial:

```python
@dataclass
class ModelRequestEvent:
    turn: int
    messages_count: int
    tools_count: int
    model: str
    provider: str = ""  # NEW: which provider was used
```

Cost calculation can then be a post-processing step that maps (provider, model, token_count) → cost.

### 8.5 `ModelAdapter` Per Provider vs. Per Model

**Question:** Should `ModelAdapter` selection be driven by provider type or by model name?

**Current behavior:** `get_response_parser(model_name)` selects the parser based on model name string matching (e.g., "Qwen" models get a different parser than default). This is model-family-based, not provider-based.

**With multi-provider:** An Anthropic model and an OpenAI model might need different message formatting. But the new provider clients already normalize to/from the shared format:

- `AnthropicClient` converts OpenAI-format messages → Anthropic format internally
- `AnthropicClient` converts Anthropic response → `CompletionResponse` (OpenAI-like format) internally

So the `ModelAdapter` only sees normalized data. The model-name-based parser selection should still work:

- `get_response_parser("claude-sonnet-4-20250514")` → default parser (since Anthropic client already normalized the response)
- `get_response_parser("gpt-4o")` → default parser (OpenAI responses are already in the expected format)
- `get_response_parser("Qwen/Qwen3-4B")` → Qwen-specific parser (handles text-based tool calls)

**Answer:** Model-name-based selection remains correct. The provider client handles the provider-level normalization; the `ModelAdapter` handles model-family-level quirks.

### 8.6 Authentication Diversity

Different providers use different auth mechanisms:

| Provider | Auth Type |
|----------|-----------|
| OpenAI, Anthropic, Groq | API key in header |
| AWS Bedrock | IAM credentials (SigV4) |
| Google Vertex | Service account / ADC |
| Local (vLLM, Ollama) | None or dummy key |

The `ProviderConfig.extra` field handles this:

```yaml
providers:
  bedrock:
    type: bedrock
    extra:
      region: us-east-1
      # Uses default AWS credential chain (env vars, ~/.aws/credentials, etc.)
  
  vertex:
    type: google
    extra:
      project_id: my-project
      location: us-central1
      # Uses Application Default Credentials (ADC)
```

Each provider's factory function interprets the `extra` dict as needed. The core registry doesn't need to understand provider-specific auth.

### 8.7 Connection Lifecycle & Cleanup

**Question:** When should pooled clients be closed?

**Current behavior:** `SwarmExecutor` never explicitly closes `self._client`. `ChatSession` closes its kernel (and therefore its client) after each `.send()`. The LSP runner's `LLMClient` is never explicitly closed.

**With the registry:** `ProviderRegistry.close_all()` closes all pooled clients. This should be called:

- When `SwarmExecutor` shuts down
- When the LSP server shuts down
- When the application exits

The registry should be treated as an application-scoped singleton. It lives for the duration of the process and is closed at shutdown.

### 8.8 Testing Strategy

**Unit tests:** Mock the `LLMClient` Protocol. The registry and resolution logic can be tested without any real LLM calls.

**Integration tests:** Each provider client needs integration tests against real or mocked APIs:

- `OpenAICompatibleClient` — already tested against vLLM
- `AnthropicClient` — test against Anthropic's API or a mock server
- `GoogleClient` — test against Google's API or a mock

**Mixed-provider test:** A swarm integration test where agents use different providers. This validates the full resolution flow and connection pooling.

### 8.9 `structured_agents` Vendoring vs. Forking

**Question:** Should the new provider clients live in `structured_agents` or in Remora's own code?

**Recommendation:** In Remora (`src/remora/core/providers/`). The `structured_agents` library defines the Protocol and the OpenAI-compatible implementation. Remora adds the provider registry and additional implementations. This keeps `structured_agents` focused and avoids vendoring drift.

The only scenario where `structured_agents` might need changes is if the `LLMClient` Protocol itself needs extending (e.g., for streaming). But the current Protocol is sufficient for the provider abstraction.

### 8.10 Concurrent Multi-Provider Safety

**Question:** Is it safe for multiple asyncio tasks to share a pooled `AsyncOpenAI` / `AsyncAnthropic` client?

**Answer: Yes.** Both `AsyncOpenAI` and `AsyncAnthropic` are designed for concurrent use. They use `httpx.AsyncClient` internally, which is safe for concurrent requests. This is the same pattern `SwarmExecutor` already uses (sharing a single `OpenAICompatibleClient` across concurrent agent runs).

The `ProviderRegistry` is not itself thread-safe for registration (adding new providers), but it only mutates during initialization. After startup, it's read-only from concurrent tasks, which is safe.

---

## Summary

The LLM Provider Abstraction is a **moderate-scope refactor** (~500 lines of new and changed code) that:

1. **Introduces `ProviderRegistry`** as the central broker for LLM client instances, replacing ad-hoc `build_client()` calls.
2. **Enables per-agent provider/model swapping** via `bundle.yaml`'s new `provider` field, resolved through a clear hierarchy.
3. **Preserves full backward compatibility** — existing configs work unchanged via a legacy fallback in `build_registry_from_config()`.
4. **Doesn't touch `structured_agents`** — new providers implement the existing `LLMClient` Protocol from outside the vendored library.
5. **Adds new provider SDKs as optional dependencies** — you only install what you use.

The architecture leverages the existing clean abstractions (`LLMClient` Protocol, `ModelAdapter`, `CompletionResponse`) rather than fighting them. The main work is plumbing the `ProviderRegistry` through the three code paths and implementing the Anthropic/Google client adapters.

**Update (Section 9):** After researching 6 open-source libraries, the revised recommendation is **Option B (Hybrid)**: keep the `ProviderRegistry` infrastructure but use **LiteLLM** as the universal transport for non-OpenAI-compatible providers, eliminating the need to hand-write `AnthropicClient`, `GoogleClient`, etc. This reduces custom provider code from ~320+ lines to ~80 lines (a single `LiteLLMProviderClient`), while keeping `structured-agents` unchanged and preserving the proven `OpenAICompatibleClient` for vLLM. See Section 9 for the full analysis.

---

## 9. Library-Based Simplification Analysis

**Motivation:** Sections 3-7 propose a custom-built multi-provider abstraction with hand-written provider clients (`AnthropicClient`, `GoogleClient`, etc.), a `ProviderRegistry`, and `ProviderConfig` system. This section asks: **can an existing open-source library eliminate or dramatically reduce that custom code?** We also own the `structured-agents` library, so we can rework it if needed.

### Section 9 Table of Contents

- **9.1 Library-by-Library Analysis** — Deep evaluation of six candidate libraries against Remora's specific requirements. For each: what it does, API style, fit rating, pros, cons, and deal-breakers.
  - 9.1.1 LiteLLM — Unified `completion()` / `acompletion()` with OpenAI-format I/O, 100+ provider support, model prefix routing
  - 9.1.2 LLM (datasette) — CLI-first tool with plugin-based model support, own Response format, no tool/function-calling abstraction
  - 9.1.3 aisuite — Lightweight OpenAI-style API with provider prefix routing, tool support, but immature and lacking async
  - 9.1.4 instructor — Structured output extraction layer (Pydantic models), complementary but not a transport replacement
  - 9.1.5 magentic — Decorator-based LLM integration with multiple backends, opinionated about calling patterns
  - 9.1.6 PydanticAI — Full agent framework from Pydantic team, competing architecture rather than transport layer

- **9.2 Comparison Matrix** — Side-by-side table comparing all 6 libraries + custom approach against Remora's hard requirements: per-call provider/model swapping, `extra_body` passthrough (vLLM grammar constraints), async support, OpenAI-format input compatibility, connection pooling, dependency weight, tool format compatibility, ownership/control.

- **9.3 Integration Approaches for Top Candidate** — Detailed analysis of how the most promising library (LiteLLM) would integrate with Remora and structured-agents. Three concrete options:
  - 9.3.1 Option A: LiteLLM inside structured-agents — Replace `OpenAICompatibleClient` with `LiteLLMClient` wrapping `litellm.acompletion()`. One-file change.
  - 9.3.2 Option B: LiteLLM inside ProviderRegistry — Keep ProviderRegistry from v1 but use LiteLLM as the universal transport inside a single `LiteLLMProviderClient` instead of hand-writing per-provider clients.
  - 9.3.3 Option C: LiteLLM replacing the entire client layer — Use LiteLLM's model prefix routing directly, bypass ProviderRegistry.
  - 9.3.4 Comparison of Options A/B/C — Trade-offs, recommended option.

- **9.4 How Library Approach Changes v1 Architecture** — Section-by-section walkthrough of how Sections 3-7 of this document are affected: what is eliminated, what is simplified, what is unchanged.

- **9.5 Revised Recommendation** — Given the library analysis, which approach (fully custom, library-based, or hybrid) and why. Cost-benefit of introducing a large external dependency vs. writing ~500 lines of custom code.

- **9.6 Impact on structured-agents** — What changes in the library we own. Key question: modify structured-agents to use LiteLLM internally, keep it pure (OpenAI SDK only) and handle multi-provider at the Remora layer, or something else?

- **9.7 Open Questions Specific to Library Approach** — `extra_body` passthrough verification for vLLM grammar constraints, LiteLLM dependency size and transitive deps, version pinning risks, LiteLLM's treatment of non-OpenAI response formats, async performance characteristics, and fallback if the library becomes unmaintained.

---

### 9.1 Library-by-Library Analysis

#### 9.1.1 LiteLLM

**What it is:** A Python SDK (+ optional proxy server) that provides a unified `completion()` / `acompletion()` function to call 100+ LLM providers using **OpenAI input/output format**. Model routing is via a prefix convention: `openai/gpt-4o`, `anthropic/claude-sonnet-4-20250514`, `hosted_vllm/model-name`, etc.

**API Style:**
```python
from litellm import acompletion

response = await acompletion(
    model="anthropic/claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": "Hello"}],
    tools=[...],           # OpenAI tool format
    max_tokens=4096,
    temperature=0.1,
)
# Returns OpenAI-format ChatCompletion object
print(response.choices[0].message.content)
```

**Fit for Remora: HIGH**

| Criterion | Assessment |
|-----------|------------|
| Per-call model swapping | Yes — just change the `model` string per call. No separate client/config needed. |
| `extra_body` passthrough | Likely yes for OpenAI-compatible providers (uses `openai` SDK under the hood). For `hosted_vllm/` prefix, kwargs pass through to `openai.ChatCompletion.create()`. **Needs verification** for vLLM `structured_outputs` grammar constraint format. |
| Async support | Yes — `acompletion()` is first-class async, uses `asyncio`. |
| OpenAI-format input | Yes — this is LiteLLM's entire design. Messages and tools use OpenAI format. |
| OpenAI-format output | Yes — returns `ModelResponse` objects that mirror OpenAI's `ChatCompletion`. |
| Connection pooling | Partial — LiteLLM creates/reuses `httpx` clients internally. Not explicitly configurable per-provider. |
| Tool/function calling | Yes — passes through OpenAI tool format. For Anthropic, auto-converts to Anthropic tool format internally. |
| Streaming | Yes — `acompletion(stream=True)` returns async iterator. |
| Cost tracking | Built-in — `litellm.completion_cost()`, callbacks for logging, has a `model_prices_and_context_window.json`. |
| Error mapping | Yes — maps all provider errors to OpenAI error classes (`RateLimitError`, `AuthenticationError`, etc.). |

**Pros:**
- Eliminates the need to write `AnthropicClient`, `GoogleClient`, `BedrockClient`, etc. — LiteLLM handles all translation internally.
- Messages and tools stay in OpenAI format throughout Remora's codebase — no format conversion code anywhere.
- Response format is already what `structured_agents` expects (OpenAI `ChatCompletion` shape).
- Adding a new provider is zero code — just use a new model prefix string.
- Built-in retry/fallback routing (`litellm.Router` class) if we ever want it.
- Actively maintained (37k+ stars, frequent releases, wide adoption).
- Apache 2.0 license — no commercial restrictions.

**Cons:**
- **Large dependency.** LiteLLM pulls in many transitive dependencies. It supports 100+ providers, and while it lazy-loads provider SDKs, the core package itself is substantial (~100+ Python files).
- **Version churn risk.** Frequent releases mean the API surface could shift. Need to pin versions carefully.
- **Opaque internals.** When something goes wrong with a specific provider, debugging requires diving into LiteLLM's translation layer rather than a simple direct SDK call. Error messages may be wrapped/transformed.
- **Potential `extra_body` transformation.** LiteLLM may strip, rename, or reformat keys in `extra_body` for certain providers. The vLLM `structured_outputs` key in `extra_body` must pass through unmodified — this needs testing.
- **We don't own it.** External dependency that could change direction, become abandoned, or introduce breaking changes. Unlike structured-agents, we can't just fix bugs or add features ourselves.
- **Overhead for simple cases.** For calling a local vLLM server (our primary use case), LiteLLM adds a layer of indirection that `AsyncOpenAI` handles perfectly directly.

**Deal-breakers to verify:**
1. Does `extra_body={"structured_outputs": {"structural_tag": {...}}}` pass through to vLLM when using the `hosted_vllm/` prefix? If LiteLLM strips or transforms this key, it breaks our grammar constraint pipeline.
2. Does LiteLLM's response format preserve `tool_calls` in exactly the OpenAI format that `QwenResponseParser` expects?

---

#### 9.1.2 LLM (datasette)

**What it is:** A CLI tool + Python library by Simon Willison. Plugin-based model support via `llm-anthropic`, `llm-ollama`, etc. Designed primarily as a command-line tool for interacting with LLMs, with a Python API as secondary.

**API Style:**
```python
import llm

model = llm.get_model("gpt-4o-mini")
response = model.prompt("Hello")
print(response.text())

# Async:
model = llm.get_async_model("gpt-4o")
response = await model.prompt("Hello")
text = await response.text()
```

**Fit for Remora: LOW**

| Criterion | Assessment |
|-----------|------------|
| Per-call model swapping | Yes — `llm.get_model(name)` returns different model instances. |
| `extra_body` passthrough | No clear mechanism. Plugin-based — each plugin defines its own parameter handling. |
| Async support | Yes — `get_async_model()` with `await`. |
| OpenAI-format input | **No.** Uses its own `Prompt` objects, not OpenAI-format message dicts. |
| OpenAI-format output | **No.** Returns `Response` objects (lazy-evaluated), not `ChatCompletion`. |
| Tool/function calling | **No.** No built-in tool/function calling abstraction. |
| Connection pooling | Not explicitly — managed by plugins. |

**Pros:**
- Lightweight and well-designed for its intended use case (CLI + simple Python scripting).
- Plugin architecture is extensible.
- Simon Willison is a respected maintainer.

**Cons:**
- **Completely different API shape.** Not OpenAI-format input OR output. Would require writing conversion layers both ways, negating the simplification benefit.
- **No tool/function calling.** Remora's core use case is tool-using agents. This library doesn't support it.
- **CLI-first design.** The Python API is secondary and less mature.
- **Plugin installation required.** Each provider needs a separate plugin package installed.

**Verdict: Not suitable.** The API mismatch and lack of tool calling make this a non-starter for Remora.

---

#### 9.1.3 aisuite

**What it is:** A lightweight unified API by Andrew Ng's team, modeled after OpenAI's API style. Provider prefix routing: `openai:gpt-4o`, `anthropic:claude-3-5-sonnet-20240620`.

**API Style:**
```python
import aisuite as ai

client = ai.Client()
response = client.chat.completions.create(
    model="anthropic:claude-3-5-sonnet-20240620",
    messages=[{"role": "user", "content": "Hello"}],
    tools=[...],
)
```

**Fit for Remora: MEDIUM-LOW**

| Criterion | Assessment |
|-----------|------------|
| Per-call model swapping | Yes — model prefix routing per call. |
| `extra_body` passthrough | Unknown. Documentation doesn't mention `extra_body` or custom kwargs. |
| Async support | **No first-class async.** No `acreate()` or async client documented. |
| OpenAI-format input | Yes — messages and tools in OpenAI format. |
| OpenAI-format output | Yes — returns OpenAI-style response objects. |
| Tool/function calling | Yes — supports tools, auto tool execution with `max_turns`. |
| Connection pooling | Unknown — not documented. |

**Pros:**
- Very lightweight — minimal dependencies, simple codebase.
- OpenAI-format I/O — matches our existing format.
- Tool support including auto-execution.
- MIT license.

**Cons:**
- **No async support.** Remora is fully async (`asyncio`). A sync-only library would require wrapping all calls in `asyncio.to_thread()` or similar, adding latency and complexity.
- **Immature.** v0.1.7, released Dec 2024. Small community. Risk of abandonment or breaking changes.
- **No `extra_body` passthrough documented.** vLLM grammar constraints may not work.
- **No connection pooling.** Each call likely creates a new HTTP session.
- **No streaming support documented.**

**Verdict: Not suitable.** The lack of async support is a hard blocker for Remora's architecture.

---

#### 9.1.4 instructor

**What it is:** A structured output extraction library. Wraps LLM clients to extract Pydantic model instances from LLM responses. Auto-retries on validation failure.

**API Style:**
```python
import instructor

client = instructor.from_provider("openai/gpt-4o-mini")
user = client.chat.completions.create(
    response_model=User,  # Pydantic model
    messages=[{"role": "user", "content": "Extract: John is 30"}],
)
# user is a User(name="John", age=30) instance
```

**Fit for Remora: NOT APPLICABLE (complementary)**

| Criterion | Assessment |
|-----------|------------|
| Per-call model swapping | Yes (via provider prefix). |
| `extra_body` passthrough | Depends on underlying client. |
| Async support | Yes. |
| Purpose | Structured extraction, NOT general LLM transport. |

**Pros:**
- Could be useful for specific Remora features (extracting structured data from LLM responses).
- Works WITH other clients (OpenAI, Anthropic, LiteLLM), not instead of them.

**Cons:**
- **Not a transport layer.** It sits ON TOP of an LLM client, not in place of one. It doesn't solve the multi-provider routing problem.
- Adds Pydantic validation overhead to every call.

**Verdict: Not a replacement.** Instructor is a structured extraction tool, not a multi-provider abstraction. It's complementary — could potentially be used WITH whatever transport we choose, but doesn't address the core requirement.

---

#### 9.1.5 magentic

**What it is:** A decorator-based LLM integration library. Define functions decorated with `@prompt("...")` that return structured output. Multiple backend support.

**API Style:**
```python
from magentic import prompt

@prompt("Create a greeting for {name}")
def greet(name: str) -> str: ...

result = greet("World")  # Calls LLM, returns string
```

**Fit for Remora: LOW**

| Criterion | Assessment |
|-----------|------------|
| Per-call model swapping | Via context manager: `with OpenaiChatModel("gpt-4o"): ...` |
| `extra_body` passthrough | Not exposed in the decorator API. |
| Async support | Yes — `@prompt_chain` with async functions. |
| OpenAI-format input | **No.** Uses decorator-based prompt definitions, not message arrays. |
| Tool/function calling | Has `@prompt_chain` for multi-step, but not OpenAI tool format. |

**Pros:**
- Interesting programming model for simple LLM tasks.
- Supports LiteLLM as a backend — so transitively supports many providers.

**Cons:**
- **Completely different programming model.** Decorator-based prompt functions are incompatible with Remora's agent loop (`AgentKernel.step()` sending message arrays with tool calls).
- **No control over message format.** The decorator abstracts away the message array entirely.
- **Not a transport layer.** It's a higher-level abstraction that makes its own design choices about how to call LLMs.

**Verdict: Not suitable.** The decorator-based model is fundamentally incompatible with Remora's message-array + tool-call agent architecture.

---

#### 9.1.6 PydanticAI

**What it is:** A full GenAI agent framework from the Pydantic team. Model-agnostic, supports many providers, with typed tools, dependency injection, evals, and OpenTelemetry observability.

**API Style:**
```python
from pydantic_ai import Agent

agent = Agent('anthropic:claude-sonnet-4-6', system_prompt="Be helpful")

@agent.tool
def get_weather(city: str) -> str:
    return f"Sunny in {city}"

result = await agent.run("What's the weather in Paris?")
```

**Fit for Remora: NOT APPLICABLE (competing framework)**

| Criterion | Assessment |
|-----------|------------|
| Per-call model swapping | Yes — agents specify their model. |
| `extra_body` passthrough | Available via `model_settings`. |
| Async support | Yes — first-class async. |
| Purpose | **Full agent framework** — competes with `structured_agents`, not just the transport layer. |

**Pros:**
- Excellent developer experience, typed tools, good documentation.
- Model-agnostic, supports all major providers.
- Built by the Pydantic team — likely to be well-maintained.

**Cons:**
- **This is a competing agent framework.** Adopting PydanticAI would mean replacing `structured_agents` entirely, not just swapping the transport layer. That's a much larger scope change.
- **Different agent loop model.** PydanticAI manages its own tool execution loop, system prompts, dependency injection, etc. Remora's `AgentKernel` has its own loop with `ModelAdapter`, `ConstraintPipeline`, `Observer`, etc.
- **No vLLM grammar constraint support.** PydanticAI doesn't have an equivalent to the `ConstraintPipeline` + `extra_body` grammar approach that's central to Remora's local model usage.
- **Massive scope creep.** Switching agent frameworks is a rewrite, not a refactor.

**Verdict: Not suitable for the current goal.** PydanticAI is interesting for greenfield projects, but adopting it would mean rewriting Remora's agent architecture rather than adding multi-provider support to the existing architecture. Worth monitoring as a long-term consideration if we ever outgrow `structured_agents`.

---

### 9.2 Comparison Matrix

Requirements are derived from Section 2 and the specific constraints identified in the structured-agents deep study.

| Requirement | Custom (Sections 3-7) | LiteLLM | LLM (datasette) | aisuite | instructor | magentic | PydanticAI |
|---|---|---|---|---|---|---|---|
| **Per-call provider/model swap** | Yes (ProviderRegistry) | Yes (model prefix) | Yes (get_model) | Yes (prefix) | N/A | Context mgr | Yes |
| **`extra_body` passthrough** | Yes (direct SDK) | Likely (needs test) | No | Unknown | N/A | No | Via settings |
| **Async support** | Yes (native SDKs) | Yes (acompletion) | Yes | **NO** | Yes | Yes | Yes |
| **OpenAI-format input** | Yes (adapters) | Yes (native) | **NO** | Yes | N/A | **NO** | **NO** |
| **OpenAI-format output** | Yes (CompletionResponse) | Yes (ModelResponse) | **NO** | Yes | N/A | **NO** | **NO** |
| **Tool/function calling** | Yes (OpenAI format) | Yes (passthrough) | **NO** | Yes | N/A | Different | Own format |
| **Connection pooling** | Yes (registry-managed) | Internal (httpx) | Plugin-dependent | Unknown | N/A | Unknown | Internal |
| **Dependency weight** | Light (per-SDK) | **HEAVY** | Medium + plugins | Light | Light | Medium | Heavy |
| **We own the code** | Yes (Remora code) | **NO** | **NO** | **NO** | **NO** | **NO** | **NO** |
| **vLLM grammar constraints** | Yes (ConstraintPipeline) | Needs verification | **NO** | **NO** | **NO** | **NO** | **NO** |
| **Streaming** | Future (Protocol ext) | Yes (built-in) | N/A | Unknown | N/A | Yes | Yes |
| **Cost tracking** | Manual (Observer) | Built-in | **NO** | **NO** | **NO** | **NO** | OTel-based |
| **Retry/fallback** | Manual | Built-in Router | **NO** | **NO** | Validation retry | **NO** | **NO** |
| **Maturity** | N/A (custom) | High (37k stars) | Medium (CLI focus) | **Low** (v0.1.7) | Medium | Low (2.4k) | Medium-High |

**Legend:** Bold **NO** = hard blocker or serious gap. Bold **HEAVY** / **Low** = significant concern.

**Key Takeaways:**

1. **LiteLLM is the only viable library candidate.** It's the only one that satisfies all three hard requirements simultaneously: async support, OpenAI-format I/O, and tool/function calling passthrough.

2. **Four libraries are eliminated outright:**
   - LLM (datasette): No OpenAI-format I/O, no tool calling
   - aisuite: No async support
   - magentic: Incompatible programming model
   - PydanticAI: Competing framework, not a transport layer

3. **instructor is complementary, not competing.** It could be used alongside either the custom or LiteLLM approach.

4. **The custom approach has one clear advantage: full control.** We own every line of code, can debug any issue, and have zero external dependency risk. The trade-off is more code to write and maintain (~500 lines).

5. **LiteLLM has one clear advantage: breadth.** 100+ providers with zero per-provider code. The trade-off is a large external dependency we don't control.

6. **The `extra_body` question is the critical unknown for LiteLLM.** If LiteLLM faithfully passes `extra_body` to vLLM for the `hosted_vllm/` prefix, it works. If it strips or transforms it, we have a deal-breaker for our primary use case (local vLLM with grammar constraints).

---

### 9.3 Integration Approaches for Top Candidate (LiteLLM)

Given that LiteLLM is the only viable library candidate, this section details three concrete integration options with increasing levels of adoption.

#### 9.3.1 Option A: LiteLLM Inside structured-agents

**Concept:** Replace `OpenAICompatibleClient` in `structured_agents/client/openai.py` with a new `LiteLLMClient` that wraps `litellm.acompletion()`. Everything else in structured-agents stays the same — kernel, adapter, parsers, grammar pipeline.

**What changes in structured-agents:**

```python
# structured_agents/client/litellm_client.py (NEW file, ~60 lines)

import litellm
from .protocol import CompletionResponse, LLMClient

class LiteLLMClient:
    """LLM client using LiteLLM for multi-provider support."""
    
    def __init__(self, model: str, api_key: str = "", base_url: str = ""):
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
    
    async def chat_completion(
        self, messages, tools=None, tool_choice="auto",
        max_tokens=4096, temperature=0.1, extra_body=None, model=None,
    ) -> CompletionResponse:
        kwargs = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["api_base"] = self._base_url
        if extra_body:
            kwargs["extra_body"] = extra_body  # Pass through for vLLM
        
        response = await litellm.acompletion(**kwargs)
        
        # Convert LiteLLM ModelResponse → CompletionResponse
        choice = response.choices[0]
        return CompletionResponse(
            content=choice.message.content,
            tool_calls=choice.message.tool_calls,  # Already OpenAI format
            usage=...,  # Map response.usage
            finish_reason=choice.finish_reason,
            raw_response=response.model_dump(),
        )
    
    async def close(self):
        pass  # LiteLLM manages its own connections
```

**What changes in Remora:** Almost nothing. `build_client()` returns `LiteLLMClient` instead of `OpenAICompatibleClient`. Model names in config use LiteLLM's prefix convention: `hosted_vllm/Qwen/Qwen3-4B`, `anthropic/claude-sonnet-4-20250514`, `openai/gpt-4o`.

**What stays the same:**
- `AgentKernel` — unchanged (still takes any `LLMClient`)
- `ModelAdapter` — unchanged (messages already OpenAI format)
- `ConstraintPipeline` — unchanged (generates `extra_body`, still passed through)
- `ResponseParser` — unchanged (response already in OpenAI format)
- `ProviderRegistry` — **NOT NEEDED.** LiteLLM's prefix routing replaces it entirely.
- `ProviderConfig` — **NOT NEEDED.** LiteLLM handles per-provider config internally.
- `create_kernel()` — minimal change (just pass full model string like `anthropic/claude-sonnet-4-20250514`)
- `SwarmExecutor` — still pools a single client; the `LiteLLMClient` is model-agnostic

**Pros:**
- **Smallest change.** One new file in structured-agents, minor updates to Remora config.
- **No ProviderRegistry.** LiteLLM replaces the entire custom abstraction from Sections 3-7.
- **Per-call provider swapping is free.** Just change the model string: `model="anthropic/claude-3-5-sonnet"` vs `model="hosted_vllm/Qwen/Qwen3-4B"`.
- **Unified connection management.** LiteLLM handles HTTP clients internally.

**Cons:**
- **Tight coupling of structured-agents to LiteLLM.** The library we own now depends on LiteLLM. If LiteLLM breaks, structured-agents breaks.
- **structured-agents loses generality.** Currently it depends only on the `openai` package (lightweight). Adding LiteLLM as a dependency makes it heavier and harder to use independently.
- **Per-provider API keys via config.** LiteLLM expects API keys via environment variables (`ANTHROPIC_API_KEY`, etc.) or passed per-call. Our `remora.yaml` would need to set env vars or pass keys through.

---

#### 9.3.2 Option B: LiteLLM Inside ProviderRegistry (Hybrid)

**Concept:** Keep the `ProviderRegistry` concept from Sections 3-5 of this document, but instead of writing per-provider client implementations (`AnthropicClient`, `GoogleClient`, etc.), write a SINGLE `LiteLLMProviderClient` that wraps `litellm.acompletion()`. The registry provides the config management, naming, and pooling; LiteLLM provides the provider translation.

**What changes in Remora:**

```python
# src/remora/core/providers/litellm_provider.py (NEW, ~80 lines)

import litellm
from structured_agents.client.protocol import CompletionResponse, LLMClient

class LiteLLMProviderClient:
    """Provider client using LiteLLM for API translation.
    
    Each instance is configured for a specific named provider
    (with its own API key, base URL, model prefix, etc.)
    but delegates the actual HTTP/translation to LiteLLM.
    """
    
    def __init__(self, provider_name: str, provider_type: str,
                 api_key: str, base_url: str, default_model: str,
                 timeout: float = 300.0):
        self.model = default_model
        self._provider_type = provider_type
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        # Build the LiteLLM model prefix based on provider type
        self._model_prefix = self._resolve_prefix(provider_type)
    
    def _resolve_prefix(self, provider_type: str) -> str:
        """Map our provider type names to LiteLLM model prefixes."""
        prefix_map = {
            "openai_compatible": "openai",
            "openai": "openai",
            "anthropic": "anthropic",
            "google": "vertex_ai",  # or "gemini"
            "bedrock": "bedrock",
            "groq": "groq",
        }
        return prefix_map.get(provider_type, provider_type)
    
    def _full_model_name(self, model: str | None) -> str:
        """Prepend the LiteLLM prefix to the model name."""
        m = model or self.model
        if "/" in m and m.split("/")[0] in ("openai", "anthropic", "vertex_ai", 
                                             "bedrock", "groq", "hosted_vllm"):
            return m  # Already has a prefix
        return f"{self._model_prefix}/{m}"
    
    async def chat_completion(
        self, messages, tools=None, tool_choice="auto",
        max_tokens=4096, temperature=0.1, extra_body=None, model=None,
    ) -> CompletionResponse:
        kwargs = {
            "model": self._full_model_name(model),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": self._timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["api_base"] = self._base_url
        if extra_body:
            kwargs["extra_body"] = extra_body
        
        response = await litellm.acompletion(**kwargs)
        return self._to_completion_response(response)
    
    def _to_completion_response(self, response) -> CompletionResponse:
        choice = response.choices[0]
        # ... normalize to CompletionResponse ...
    
    async def close(self):
        pass
```

**What changes in the ProviderRegistry:**

The `ProviderRegistry` from Section 3.4 stays almost exactly as designed. The only difference is that ALL provider types map to `LiteLLMProviderClient` instead of per-provider implementations:

```python
# Instead of:
register_provider_type("anthropic", _build_anthropic)       # Custom AnthropicClient
register_provider_type("google", _build_google)             # Custom GoogleClient

# We have:
register_provider_type("anthropic", _build_litellm_provider)  # LiteLLMProviderClient
register_provider_type("google", _build_litellm_provider)     # LiteLLMProviderClient
register_provider_type("openai", _build_litellm_provider)     # LiteLLMProviderClient
register_provider_type("openai_compatible", _build_litellm_provider)  # Same
```

Or even simpler — the factory function is the same for all types:

```python
def _build_litellm_provider(config: ProviderConfig) -> LLMClient:
    return LiteLLMProviderClient(
        provider_name=config.name,
        provider_type=config.type,
        api_key=config.api_key,
        base_url=config.base_url,
        default_model=config.default_model,
        timeout=config.timeout,
    )
```

**What stays the same:**
- `ProviderRegistry` — config management, naming, pooling (Section 3.4)
- `ProviderConfig` — provider configuration model (Section 3.2)
- `remora.yaml` format — multi-provider config (Section 5.1)
- `bundle.yaml` per-agent provider override (Section 4.2)
- `create_kernel()` — accepts registry + provider_name (Section 4.4)
- `SwarmExecutor` flow — uses registry (Section 4.5)
- `structured_agents` — **UNCHANGED.** LiteLLM is a Remora dependency, not a structured-agents dependency.

**Pros:**
- **Best of both worlds.** We keep our config management, naming, and pooling architecture. LiteLLM handles the messy provider translation.
- **structured-agents stays clean.** No LiteLLM dependency in the library we own. It continues to use `OpenAICompatibleClient` + `openai` SDK only.
- **The registry adds value.** Named providers, connection pooling by name, config management, `remora.yaml` integration — these are Remora-specific concerns that LiteLLM doesn't handle.
- **Eliminates ~240 lines of custom provider code.** No `AnthropicClient`, no `GoogleClient`, no per-provider message/tool conversion logic.
- **Per-provider API keys are explicit.** Each named provider in `remora.yaml` has its own `api_key` field — passed to LiteLLM per-call. No magic env var conventions.
- **Fallback path.** If LiteLLM doesn't work for a provider, we can write a custom client for just that one provider and register it alongside the LiteLLM-based ones.

**Cons:**
- **Still need ProviderRegistry code.** ~150 lines of registry + config infrastructure. More code than Option A.
- **Dual model naming.** Our config uses `model_name: claude-sonnet-4-20250514` with a separate `type: anthropic`. Internally we prepend `anthropic/` for LiteLLM. This translation layer is simple but exists.
- **LiteLLM as a Remora dependency.** Still a large external dep. Same version-pinning and churn risks.

---

#### 9.3.3 Option C: LiteLLM Replacing the Entire Client Layer

**Concept:** Use LiteLLM directly everywhere. No `ProviderRegistry`, no `LLMClient` Protocol wrapper, no `OpenAICompatibleClient`. All code calls `litellm.acompletion()` directly with model prefix strings.

**What changes:**
- `AgentKernel.step()` calls `litellm.acompletion()` directly instead of `self._client.chat_completion()`.
- Or: `AgentKernel` wraps LiteLLM in a minimal function, but there's no `LLMClient` abstraction.
- `SwarmExecutor` and `ChatSession` call LiteLLM directly.
- `build_client()` is removed. No client protocol.

**Pros:**
- Simplest possible code — just call `litellm.acompletion()` everywhere.
- Zero abstraction layers between Remora and the LLM API.

**Cons:**
- **Destroys the `LLMClient` Protocol.** structured-agents is designed around the `LLMClient` Protocol. Removing it means rewriting the kernel.
- **No mockability.** Testing requires mocking `litellm.acompletion()` globally instead of injecting a mock `LLMClient`.
- **No separation of concerns.** LLM configuration details (API keys, base URLs, model prefixes) leak into every file that calls the LLM.
- **Makes structured-agents useless.** The library exists specifically to provide the kernel + adapter + tool execution loop with pluggable `LLMClient`. Bypassing the protocol removes the reason for having the library.
- **Tightest possible coupling to LiteLLM.** Every Remora file that touches LLMs depends directly on LiteLLM. Switching away from LiteLLM in the future would be a massive refactor.

**Verdict: Not recommended.** This option sacrifices all of structured-agents' architecture for marginal simplification. The `LLMClient` Protocol is a good abstraction that enables testing, mocking, and future flexibility.

---

#### 9.3.4 Comparison of Options A/B/C

| Aspect | Option A (LiteLLM in s-a) | Option B (LiteLLM in Registry) | Option C (LiteLLM direct) |
|--------|--------------------------|-------------------------------|--------------------------|
| **Lines of new code** | ~60 (LiteLLMClient) | ~230 (Registry + LiteLLMProviderClient) | ~0 (but rewrites ~200) |
| **Lines eliminated** | ~240 (no custom providers) | ~240 (no custom providers) | ~500 (no registry, no protocol) |
| **structured-agents impact** | Adds LiteLLM dep | **None** | Gutted / rewritten |
| **ProviderRegistry needed** | No | Yes | No |
| **Named provider config** | No (model prefix strings) | Yes (`remora.yaml` providers section) | No |
| **Per-provider API keys** | Env vars or per-call | `remora.yaml` per provider | Scattered |
| **Testability** | Good (mock LiteLLMClient) | Best (mock at Protocol level) | Poor (mock global function) |
| **LiteLLM coupling** | Medium (in s-a) | Low (in Remora only) | Total |
| **Fallback to custom** | Revert entire client | Per-provider (register custom) | Complete rewrite |
| **vLLM grammar risk** | If extra_body breaks, all breaks | Can fall back to OpenAICompatibleClient for vLLM | Same as A |
| **Config ergonomics** | Model prefixes in config | Named providers in config | Model prefixes everywhere |

**Recommended: Option B.**

Rationale:
1. **Preserves structured-agents.** The library stays clean, depends only on `openai`, and remains useful independently of Remora. We can update/publish it without LiteLLM.
2. **Best fallback story.** If LiteLLM doesn't handle vLLM `extra_body` correctly, we register the existing `OpenAICompatibleClient` for `openai_compatible` type and only use LiteLLM for providers that need translation (Anthropic, Google, Bedrock). This hybrid is trivial with the registry pattern.
3. **Best config ergonomics.** Named providers in `remora.yaml` are clearer than model prefix strings scattered through `bundle.yaml` files.
4. **Best testability.** The `LLMClient` Protocol remains the test boundary. Mock at the protocol level, not at LiteLLM's internal function.
5. **Incremental adoption.** Start with the existing `OpenAICompatibleClient` for vLLM (proven), add LiteLLM-backed providers for Anthropic/Google. No big-bang switch.

---

### 9.4 How Library Approach Changes v1 Architecture

This section walks through Sections 3-7 of this document and identifies what changes under Option B (the recommended hybrid approach).

#### Section 3 (ProviderRegistry) — Mostly Unchanged

| Component | v1 (Custom) | v2 (Hybrid with LiteLLM) | Delta |
|-----------|-------------|--------------------------|-------|
| `ProviderConfig` | As designed | **Unchanged.** Same data class. | None |
| `ProviderRegistry` | As designed | **Unchanged.** Same registry pattern. | None |
| `register_provider_type()` | Maps types to per-provider factories | Maps types to factories — but most map to `_build_litellm_provider` | Simplified |
| **Provider Type Registry** | 4+ factory functions (openai_compat, anthropic, google, bedrock) | **2 factory functions**: `_build_openai_compatible` (existing, for vLLM/direct OpenAI), `_build_litellm_provider` (universal, for everything LiteLLM handles) | **Simplified from 4+ to 2** |
| `AnthropicClient` (~120 lines) | Hand-written, message/tool conversion | **ELIMINATED.** `LiteLLMProviderClient` handles it. | **-120 lines** |
| `GoogleClient` (~100 lines) | Hand-written, SDK integration | **ELIMINATED.** `LiteLLMProviderClient` handles it. | **-100 lines** |
| `BedrockClient` (future) | Would need hand-writing | **ELIMINATED.** `LiteLLMProviderClient` handles it. | **-100+ lines avoided** |
| `LiteLLMProviderClient` | N/A | **NEW.** ~80 lines, universal provider client. | **+80 lines** |

**Net: -240+ lines of provider-specific client code, replaced by ~80 lines of universal LiteLLM wrapper.**

#### Section 4 (Per-Call Model Resolution) — Unchanged

The resolution hierarchy, `ModelSpec`, `_resolve_model_spec()`, extended `bundle.yaml`, and updated `create_kernel()` signature are **all unchanged**. These are Remora-level concerns that exist regardless of whether the underlying transport is custom or LiteLLM.

The only subtle difference: when `LiteLLMProviderClient.chat_completion(model=...)` receives a model name like `claude-sonnet-4-20250514`, it internally prepends the LiteLLM prefix (e.g., `anthropic/claude-sonnet-4-20250514`) before calling `litellm.acompletion()`. This is transparent to the caller.

#### Section 5 (Config Design) — Unchanged

The `remora.yaml` format, `Config` class extensions, `build_registry_from_config()`, and backward compatibility logic are **all unchanged.** The config layer doesn't know or care whether the registered clients use custom SDKs or LiteLLM internally.

#### Section 6 (Impact Analysis) — Simplified

| File | v1 Change | v2 Change | Difference |
|------|-----------|-----------|------------|
| `providers/__init__.py` | ~150 lines, 4+ factory registrations | ~150 lines, 2 factory registrations | Slightly simpler |
| `providers/openai_compat.py` | ~20 lines | **Unchanged** — still wraps `OpenAICompatibleClient` | None |
| `providers/anthropic.py` | ~120 lines (custom AnthropicClient) | **ELIMINATED** — handled by LiteLLMProviderClient | **-120 lines** |
| `providers/google.py` | ~100 lines (custom GoogleClient) | **ELIMINATED** — handled by LiteLLMProviderClient | **-100 lines** |
| `providers/litellm_provider.py` | N/A | **NEW** ~80 lines (universal LiteLLM wrapper) | **+80 lines** |
| `core/config.py` | ~15 lines added | **Unchanged** | None |
| `core/kernel_factory.py` | ~20 lines changed | **Unchanged** | None |
| `core/swarm_executor.py` | ~40 lines changed | **Unchanged** | None |
| `core/chat.py` | ~10 lines changed | **Unchanged** | None |
| `lsp/runner.py` | ~30 lines changed | **Unchanged** | None |

**v1 total: ~390 new + ~115 modified = ~505 lines of change.**
**v2 total: ~230 new + ~115 modified = ~345 lines of change.** (Plus LiteLLM as a dependency.)

**Net savings: ~160 lines of custom code eliminated.** More importantly, the eliminated code is the hardest code to write and maintain (per-provider SDK integration with message/tool format translation).

#### Section 7 (Migration Path) — Simplified

Phase 1 (Core Abstraction) is **unchanged** — still introduces `ProviderRegistry` with only `openai_compatible` type.

Phase 2 (Anthropic Provider) is **dramatically simplified:**
- v1: Write `AnthropicClient` (~120 lines), handle message conversion, tool conversion, response normalization, auth. Write integration tests against the Anthropic API.
- v2: Register `"anthropic"` type mapped to `_build_litellm_provider`. Add `litellm` to dependencies. Test that `LiteLLMProviderClient` works for Anthropic. **~5 lines of registration code instead of ~120 lines of client code.**

Phase 3 (LSP Runner) is **unchanged** — the runner doesn't care about the transport.

Phase 4 (Additional Providers) becomes **trivial:**
- v1: Write `GoogleClient`, `BedrockClient`, each ~100 lines with SDK-specific code.
- v2: Already done — `LiteLLMProviderClient` handles them all. Just add config entries.

---

### 9.5 Revised Recommendation

After analyzing 6 libraries and 3 integration approaches, the recommendation is:

**Option B (Hybrid): ProviderRegistry + LiteLLM as the universal transport, with OpenAICompatibleClient retained for vLLM.**

This is the recommended approach because:

**1. It respects the critical constraint: vLLM `extra_body` passthrough.**

The primary Remora use case is local vLLM with grammar constraints via `extra_body`. The existing `OpenAICompatibleClient` is proven to work for this. By registering it as the `openai_compatible` provider type, we keep the proven path for the primary use case. LiteLLM is only used for providers where we need its translation capabilities (Anthropic, Google, Bedrock, etc.).

If LiteLLM turns out to handle `extra_body` correctly for vLLM (via the `hosted_vllm/` prefix), we could later unify everything behind `LiteLLMProviderClient`. But there's no rush — the hybrid gives us safety.

**2. It minimizes custom code while preserving architecture.**

The ProviderRegistry (~150 lines) provides real value: named providers, config management, connection pooling, backward compatibility. This is Remora-specific infrastructure that no library provides. On top of that, `LiteLLMProviderClient` (~80 lines) eliminates all per-provider client code (~340+ lines).

**3. It keeps structured-agents clean.**

No LiteLLM dependency in structured-agents. The library continues to define the `LLMClient` Protocol and provide `OpenAICompatibleClient`. Remora adds multi-provider support at its own layer. If we ever publish structured-agents as a standalone package, it has no baggage.

**4. It enables incremental adoption and per-provider fallback.**

The registry pattern means we can mix and match:
- `openai_compatible` type → `OpenAICompatibleClient` (proven, no LiteLLM)
- `anthropic` type → `LiteLLMProviderClient` (LiteLLM-based)
- `google` type → `LiteLLMProviderClient` (LiteLLM-based)
- Any future type → either LiteLLM or custom, per-provider decision

If LiteLLM has a bug with one provider, we write a custom client for just that provider and register it. No all-or-nothing commitment.

**5. The cost-benefit is favorable.**

| Metric | Custom Only (v1) | Hybrid (v2) |
|--------|-----------------|-------------|
| New code to write | ~390 lines | ~230 lines |
| Per-provider client code | ~320+ lines (and growing) | ~80 lines (universal) |
| New dependency | None (per-provider SDKs) | `litellm` (+ per-provider SDKs via LiteLLM) |
| Maintenance burden | High (must track SDK changes per provider) | Low (LiteLLM tracks SDK changes) |
| Adding a new provider | Write ~100 line client | Add config entry (~5 lines) |
| Risk profile | Low (we own everything) | Medium (LiteLLM dependency) |

The trade-off: we accept an external dependency (`litellm`) in exchange for eliminating the most complex and maintenance-heavy code (per-provider SDK integration). The ProviderRegistry insulates us from the dependency — if LiteLLM goes away, we only need to replace `LiteLLMProviderClient`, not restructure the entire system.

**What about the fully custom approach (Sections 3-7 as-is)?**

Still a valid option. The custom approach is ~160 more lines of code but zero external dependency risk. If the team's preference is maximum control and the provider set is small (just Anthropic + OpenAI + vLLM), the custom approach is perfectly viable. The ProviderRegistry infrastructure from Sections 3-5 is the same either way — the only question is what sits behind `register_provider_type()`.

**The decision point is:**
- If we expect to support **3-4 providers** → custom clients are manageable; external dependency may not be worth it.
- If we expect to support **6+ providers** or frequently add new ones → LiteLLM's breadth pays for itself.

---

### 9.6 Impact on structured-agents

We own the `structured-agents` library (source at `.context/structured-agents_v0.3.4/`). This section analyzes what happens to it under each approach.

#### Under the Recommended Approach (Option B: Hybrid)

**structured-agents is UNCHANGED.** Zero modifications.

| Component | Current State | Change Under Option B |
|-----------|--------------|----------------------|
| `LLMClient` Protocol | Defines `chat_completion()` | **No change.** New providers implement this protocol from Remora. |
| `OpenAICompatibleClient` | Wraps `AsyncOpenAI` | **No change.** Still used for `openai_compatible` provider type. |
| `build_client()` | Factory returning `OpenAICompatibleClient` | **No change.** Still used by legacy code paths. |
| `AgentKernel` | Takes any `LLMClient`, runs step loop | **No change.** Receives provider clients from Remora's registry. |
| `ModelAdapter` | Formats messages/tools, parses responses | **No change.** Messages are already OpenAI format regardless of provider. |
| `ConstraintPipeline` | Generates `extra_body` for vLLM | **No change.** `extra_body` passthrough is handled by the provider client. |
| `ResponseParser` | Parses response content + tool_calls | **No change.** All provider clients normalize to OpenAI-format responses. |
| Dependencies | `openai`, `pyyaml`, `pydantic` | **No change.** No LiteLLM dependency. |

This is the primary advantage of Option B: the library we own stays clean, lightweight, and independently usable. Anyone can use structured-agents with just `openai` installed for OpenAI-compatible endpoints. Remora adds multi-provider support at a higher layer.

#### What About Future structured-agents Development?

Three areas where structured-agents might evolve independently of the provider abstraction:

**1. Response Parser Registry.** Currently, `get_response_parser(model_name)` has a hardcoded dict mapping model name patterns to parsers. As more models are used, this could be opened up:

```python
# Current (hardcoded):
_ADAPTER_REGISTRY = {"qwen": QwenResponseParser, "function_gemma": QwenResponseParser}

# Possible future (extensible):
register_response_parser("qwen", QwenResponseParser)
register_response_parser("claude", DefaultResponseParser)  # If needed
```

This is independent of the provider question — it's about model-family quirks, not transport.

**2. Streaming Support.** If we add `chat_completion_stream()` to the `LLMClient` Protocol (see Section 8.1), that's a structured-agents change. Both custom and LiteLLM-based provider clients would need to implement it.

**3. `CompletionResponse` Extensions.** If we add fields like `thinking: str | None` (Section 8.2) for Anthropic thinking blocks, or `reasoning_tokens: int` for OpenAI o3, those are protocol-level changes in structured-agents.

#### What If We Chose Option A Instead? (LiteLLM Inside structured-agents)

For comparison, here's what would change:

| Component | Change Under Option A |
|-----------|----------------------|
| `LLMClient` Protocol | No change |
| `OpenAICompatibleClient` | **Deprecated** or kept as fallback |
| `build_client()` | **Returns `LiteLLMClient` instead** |
| `LiteLLMClient` | **NEW file** (~60 lines) |
| Dependencies | **Adds `litellm`** as a dependency |
| AgentKernel | No change |

This would work, but it means:
- Anyone using structured-agents independently must install LiteLLM (large dependency for a small library).
- If we publish structured-agents, it has an opinionated dependency on a specific LLM routing library.
- structured-agents' scope creeps from "agent kernel with OpenAI-compatible client" to "agent kernel with universal LLM routing."

**This is why Option B is preferred.** The abstraction boundary is cleaner: structured-agents handles the agent loop and OpenAI-compatible transport; Remora handles multi-provider routing and configuration.

#### Key Question: Should structured-agents Learn About Provider Prefixes?

**No.** Under Option B, structured-agents never sees LiteLLM model prefixes like `anthropic/claude-sonnet-4-20250514`. It sees plain model names like `claude-sonnet-4-20250514` passed via the `model` parameter on `chat_completion()`. The `LiteLLMProviderClient` in Remora prepends the prefix internally before calling LiteLLM.

This means `get_response_parser("claude-sonnet-4-20250514")` in structured-agents sees the raw model name, which is correct for parser selection (parsers are model-family-specific, not provider-specific).

---

### 9.7 Open Questions Specific to Library Approach

#### 9.7.1 `extra_body` Passthrough Verification (CRITICAL)

**Status: Unverified. Must test before committing to LiteLLM.**

The `ConstraintPipeline` generates payloads like:
```python
extra_body = {
    "structured_outputs": {
        "structural_tag": {
            "begin": "<tool_call>",
            "end": "</tool_call>",
            "type": "json",
            "json_schema": {...}
        }
    }
}
```

This is passed to `OpenAICompatibleClient.chat_completion()`, which passes it as `extra_body=` to `AsyncOpenAI.chat.completions.create()`. The OpenAI SDK sends it as additional JSON body keys in the HTTP request to vLLM.

**LiteLLM question:** When calling `litellm.acompletion(model="hosted_vllm/...", extra_body={...})`, does LiteLLM:
- (a) Pass `extra_body` through to the underlying `openai.ChatCompletion.create()` call? (We need this.)
- (b) Strip it? (Deal-breaker.)
- (c) Transform it? (Potentially deal-breaker.)

**How to verify:**
1. Read LiteLLM source for the `hosted_vllm` provider handling.
2. Write a minimal test: call `litellm.acompletion()` with `hosted_vllm/model` and `extra_body`, inspect the outgoing HTTP request.
3. If LiteLLM doesn't pass it through, we can still use Option B — just register `openai_compatible` type with the existing `OpenAICompatibleClient` (bypassing LiteLLM for vLLM), and only use LiteLLM for non-vLLM providers.

**Risk mitigation (Option B advantage):** Under Option B, vLLM can always use `OpenAICompatibleClient` directly. LiteLLM is only needed for providers that DON'T need `extra_body` (Anthropic, Google, etc.). This completely avoids the risk.

#### 9.7.2 LiteLLM Dependency Size

**Concern:** LiteLLM is a large package with many transitive dependencies.

**Rough dependency analysis:**
- `litellm` core: `openai`, `tokenizers`, `tiktoken`, `importlib-metadata`, `jinja2`, `aiohttp`, `click`, `python-dotenv`, etc.
- Provider SDKs are lazy-imported but LiteLLM's core still pulls in tokenizer libraries and other utilities.
- The full install size is significantly larger than `openai` alone.

**Mitigation:**
- Pin to a specific LiteLLM version in `pyproject.toml`.
- Make LiteLLM an optional extra: `remora[multi-provider]` installs it, base install does not.
- If only using `openai_compatible` providers (vLLM, Groq, Ollama), LiteLLM is not needed at all.

**Decision needed:** Is `litellm` always installed, or is it an optional extra activated only when non-OpenAI-compatible providers are configured?

Recommendation: **Optional extra.** `pip install remora[anthropic]` or `pip install remora[multi-provider]` installs LiteLLM. Base `pip install remora` only needs `openai`. This matches R6 from Section 2.3 ("No mandatory new dependencies").

#### 9.7.3 LiteLLM Version Pinning & Churn

**Concern:** LiteLLM releases very frequently (multiple times per week). Each release could introduce subtle behavior changes in how it translates requests for specific providers.

**Mitigation:**
- Pin to a specific minor version range: `litellm>=1.55,<1.60`.
- Run integration tests against pinned version in CI.
- Only bump the LiteLLM version deliberately, not automatically.
- The registry fallback pattern means a LiteLLM regression for one provider can be worked around by registering a custom client for that provider.

#### 9.7.4 LiteLLM Response Format Fidelity

**Concern:** Does LiteLLM's `ModelResponse` object preserve all the fields we need?

Required fields for `CompletionResponse`:
- `content: str | None` — Message text
- `tool_calls: list[dict] | None` — Tool calls in OpenAI format (`id`, `type`, `function.name`, `function.arguments`)
- `usage: TokenUsage | None` — `prompt_tokens`, `completion_tokens`, `total_tokens`
- `finish_reason: str` — `stop`, `tool_calls`, `length`, etc.

LiteLLM's `ModelResponse` mirrors OpenAI's `ChatCompletion`:
- `choices[0].message.content` → content
- `choices[0].message.tool_calls` → tool_calls (OpenAI format)
- `usage.prompt_tokens`, `usage.completion_tokens` → usage
- `choices[0].finish_reason` → finish_reason

**Assessment: HIGH FIDELITY.** LiteLLM's entire design goal is to return OpenAI-format responses regardless of the underlying provider. The `CompletionResponse` mapping should be straightforward.

**Edge case:** For providers that return tool calls in a different format (Anthropic's `tool_use` blocks), LiteLLM converts them to OpenAI format. This conversion may have subtle differences from what we'd write by hand. Testing is needed.

#### 9.7.5 Async Performance Characteristics

**Concern:** Does `litellm.acompletion()` add measurable latency compared to calling `AsyncOpenAI` directly?

**Expected overhead:** Minimal. LiteLLM's async path calls the provider's async SDK under the hood. For OpenAI-compatible providers, it calls `openai.AsyncOpenAI.chat.completions.create()` — the same thing `OpenAICompatibleClient` does. The overhead is function dispatch, parameter translation, and response wrapping — microseconds compared to the LLM inference time (seconds).

**Benchmark approach:** If concerned, benchmark:
1. Direct `AsyncOpenAI` call to local vLLM: N requests, measure p50/p99 latency.
2. `litellm.acompletion(model="hosted_vllm/...")` to the same vLLM: same N requests, same payload.
3. Compare. Difference should be negligible.

#### 9.7.6 Fallback Strategy if LiteLLM Becomes Unmaintained

**Scenario:** LiteLLM project goes dormant, stops updating for new provider API changes.

**Under Option B, the fallback is straightforward:**
1. Freeze the LiteLLM version pin.
2. For any provider where LiteLLM breaks, write a custom `LLMClient` implementation (like the `AnthropicClient` from Section 3.5.2) and register it with the `ProviderRegistry`.
3. Over time, replace all `LiteLLMProviderClient` registrations with custom clients.
4. Eventually remove the LiteLLM dependency entirely.

This is a gradual migration, not a crisis. The ProviderRegistry abstraction means each provider can be individually migrated from LiteLLM to custom with zero impact on other providers or the rest of the system.

**Under Option A (LiteLLM in structured-agents), the fallback is harder:** the entire client layer depends on LiteLLM, so you'd need to rewrite the client module.

**Under Option C (LiteLLM everywhere), the fallback is a full rewrite.**

This is another reason Option B is the most resilient choice.

#### 9.7.7 LiteLLM Proxy Server — Relevant or Overkill?

LiteLLM also offers a **Proxy Server** mode: a standalone HTTP server that acts as an AI Gateway, accepting OpenAI-format requests and routing to any provider. This is an alternative to using the LiteLLM Python SDK directly.

**Relevance to Remora:** Low for now. The proxy adds deployment complexity (another service to run) and is designed for multi-tenant scenarios (API key management, usage tracking, rate limiting across users). Remora is a single-user/team tool.

**When it might become relevant:** If Remora needs to run behind a shared gateway for cost management or if multiple Remora instances need centralized provider config. But this is a deployment concern, not an architecture concern. The SDK approach (Option B) can migrate to the proxy approach later if needed — the API format is the same.

---

### Section 9 Summary

**The library landscape is clear:**
- Of 6 libraries evaluated, only **LiteLLM** is a viable candidate for Remora's multi-provider abstraction.
- The other 5 fail on hard requirements: no async (aisuite), wrong API shape (LLM datasette, magentic), wrong scope (instructor is complementary, PydanticAI is a competing framework).

**The recommended integration is Option B: Hybrid ProviderRegistry + LiteLLM.**
- Keep the `ProviderRegistry` infrastructure from Sections 3-5 (config management, named providers, connection pooling, backward compatibility).
- Use a single `LiteLLMProviderClient` (~80 lines) as the universal transport for non-OpenAI-compatible providers.
- Keep `OpenAICompatibleClient` for vLLM (proven, direct, no `extra_body` risk).
- structured-agents stays unchanged — no LiteLLM dependency.

**What this changes vs. the v1 custom approach:**
- Eliminates ~240+ lines of per-provider client code (AnthropicClient, GoogleClient, etc.).
- Adds `litellm` as an optional dependency.
- Adds ~80 lines of `LiteLLMProviderClient`.
- All other architecture (registry, config, resolution, migration path) is unchanged.

**The critical verification before committing:** Test `extra_body` passthrough with LiteLLM's `hosted_vllm/` prefix. If it works, LiteLLM can also handle vLLM and we can simplify further. If it doesn't, the hybrid approach already has the fallback built in.
