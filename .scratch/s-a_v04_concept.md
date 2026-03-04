# structured-agents v0.4 — Architecture Concept

**Purpose:** Condensed before/after mental model for the structured-agents refactor.
**Full analysis:** `structured-agents_refactor_ideas.md` (2,600 lines)
**Key constraint:** structured-agents is only used inside Remora.

---

## Before (v0.3.4)

### Mental Model

structured-agents is a small (~1,438 lines, 21 files) library for running tool-using LLM agents. It has a clean core — `AgentKernel` runs a step loop (call LLM → parse response → execute tools → repeat) — but carries dead weight from its origins as a standalone tool.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│  Agent (from_bundle, run)         ← UNUSED by Remora │
│  AgentManifest / load_manifest    ← partially used   │
├─────────────────────────────────────────────────────┤
│                  AgentKernel                          │
│          client ─ adapter ─ tools ─ observer          │
├──────────┬───────────┬──────────────┬────────────────┤
│  Client  │  Adapter  │   Grammar    │    Events      │
│  Layer   │  Layer    │   Pipeline   │    System      │
│          │           │              │                │
│ OpenAI   │ Model     │ Constraint   │ 7 frozen       │
│ Compat.  │ Adapter   │ Pipeline     │ dataclasses    │
│ Client   │ (carries  │ (vLLM-only   │                │
│ (vLLM    │  parser + │  extra_body) │ Observer       │
│  only)   │  pipeline │              │ Protocol       │
│          │  + unused │              │                │
│ build_   │  format   │              │                │
│ client() │  fns)     │              │                │
├──────────┴───────────┴──────────────┴────────────────┤
│  Types: Message, ToolCall, ToolResult, ToolSchema,   │
│         TokenUsage, StepResult, RunResult             │
├─────────────────────────────────────────────────────┤
│  Tool Protocol    GrailTool / discover_tools()       │
│                   ↑ UNUSED by Remora                 │
└─────────────────────────────────────────────────────┘
```

### Problems

| Problem | Impact |
|---------|--------|
| **Single provider** — `OpenAICompatibleClient` wraps `AsyncOpenAI`, hardwired to one vLLM endpoint | Can't use Anthropic, OpenAI, Gemini, etc. |
| **Two execution paths** — Remora's LSP runner reimplements the entire agent loop outside the kernel | ~200 lines duplicated, features diverge, naming collisions (`ToolCall`, `LLMClient` mean different things) |
| **`ModelAdapter` is hollow** — Carries parser + pipeline, but its format functions are never overridden | Unnecessary indirection between kernel and parser |
| **Event type split** — s-a events are dataclasses, Remora events are Pydantic. Dual serialization everywhere | `EventStore` and `EventBus` have `isinstance` branches for two type systems |
| **Dead code** — `Agent` class, `GrailTool`, `discover_tools()`, `_ADAPTER_REGISTRY` never used by Remora | 35% of the codebase is unused |
| **Bugs** — Double `ModelRequestEvent` emission per turn, debug `print()` in client | Noisy events, console spam |
| **Misleading names** — `QwenResponseParser` handles all models, not just Qwen | Confusing for anyone reading the code |

### Concepts a developer must hold in their head (v0.3.4)

```
AgentKernel, ModelAdapter, ResponseParser, QwenResponseParser,
ConstraintPipeline, DecodingConstraint, LLMClient Protocol,
OpenAICompatibleClient, build_client, CompletionResponse,
Observer Protocol, NullObserver, CompositeObserver,
Agent, AgentManifest, load_manifest, _ADAPTER_REGISTRY,
Tool Protocol, GrailTool, discover_tools,
Message, ToolCall, ToolResult, ToolSchema, TokenUsage,
StepResult, RunResult, 7 event dataclasses,
4 exception types, 35+ __init__.py exports
```

---

## After (v0.4+)

### Mental Model

structured-agents is a focused kernel library (~1,000 lines, 16 files). It does one thing: run a tool-using agent loop against any LLM provider. LiteLLM handles provider routing via model string prefixes. The kernel owns the step loop, parser, and grammar constraints directly — no adapter indirection. Events are Pydantic models, consistent with Remora. Every Remora execution path (swarm, chat, LSP) goes through the same kernel.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                  AgentKernel                          │
│    client ─ response_parser ─ constraint_pipeline    │
│    tools ─ observer                                  │
├──────────┬───────────┬──────────────┬────────────────┤
│  Client  │  Parsing  │   Grammar    │    Events      │
│  Layer   │           │   Pipeline   │    System      │
│          │           │              │                │
│ LiteLLM  │ Default   │ Constraint   │ 7 frozen       │
│ Client   │ Response  │ Pipeline     │ Pydantic       │
│ (any     │ Parser    │ (applied     │ models         │
│  provider│           │  only for    │                │
│  via     │           │  hosted_vllm │ KernelEvent    │
│  prefix) │           │  models)     │ base class     │
│          │           │              │                │
│ build_   │           │              │ Observer       │
│ client() │           │              │ Protocol       │
├──────────┴───────────┴──────────────┴────────────────┤
│  Types: Message, ToolCall, ToolResult, ToolSchema,   │
│         TokenUsage, StepResult, RunResult             │
├─────────────────────────────────────────────────────┤
│  Tool Protocol (only)                                │
└─────────────────────────────────────────────────────┘
```

### What Changed

| Before | After | Why |
|--------|-------|-----|
| `OpenAICompatibleClient` (vLLM only) | `LiteLLMClient` (any provider) | Model prefix routes to provider: `anthropic/...`, `hosted_vllm/...`, `openai/...` |
| `ModelAdapter` wraps parser + pipeline | Parser and pipeline are direct kernel fields | Adapter added zero value — format functions were never overridden |
| `QwenResponseParser` | `DefaultResponseParser` | Name matches reality — it handles all models |
| Events are frozen dataclasses | Events are frozen Pydantic models with `KernelEvent` base | Unifies with Remora's event system. Single serialization path. |
| Grammar constraints always applied | Kernel checks model prefix, only applies for `hosted_vllm/` | Prevents sending vLLM-specific payloads to cloud providers |
| `Agent`, `AgentManifest`, `load_manifest()` | Removed — Remora owns manifest loading | Remora never used `Agent`. Manifest format is Remora-specific. |
| `GrailTool`, `discover_tools()` | Removed — Remora has its own | Dead code. Remora's version is richer. |
| LSP runner has its own agent loop | LSP runner uses `AgentKernel` | Eliminates ~200 lines of duplication, naming collisions, and feature divergence |
| Duplicate `ModelRequestEvent` per turn | Fixed — emitted once in `step()` | Bug fix |
| Debug `print()` in client | Removed | Cleanup |
| 21 files, ~1,438 lines, 35+ exports | 16 files, ~1,000 lines, ~28 exports | 30% smaller, every remaining line is used |

### Concepts a developer must hold in their head (v0.4+)

```
AgentKernel, ResponseParser, DefaultResponseParser,
ConstraintPipeline, DecodingConstraint, LLMClient Protocol,
LiteLLMClient, build_client, CompletionResponse,
Observer Protocol, NullObserver, CompositeObserver,
Tool Protocol,
Message, ToolCall, ToolResult, ToolSchema, TokenUsage,
StepResult, RunResult, 7 Pydantic event models (KernelEvent base),
2 exception types, ~28 __init__.py exports
```

Removed from the concept set: `ModelAdapter`, `Agent`, `AgentManifest`, `load_manifest`, `GrailTool`, `discover_tools`, `_ADAPTER_REGISTRY`, `QwenResponseParser`, `OpenAICompatibleClient`, `BundleError`, `AdapterError`.

---

## Data Flow — Before vs After

### Before (v0.3.4)

```
Remora config
  → build_client({base_url, api_key, model})
    → OpenAICompatibleClient (wraps AsyncOpenAI)
  → get_response_parser(model_name) → QwenResponseParser
  → ConstraintPipeline(grammar_config)
  → ModelAdapter(name, response_parser, constraint_pipeline)
  → AgentKernel(client, adapter, tools, observer)

kernel.run(messages, tools, max_turns)
  → kernel.step()
    → adapter.format_messages(messages) → list[dict]     # always identity
    → adapter.format_tools(tools) → list[dict]           # always identity
    → adapter.constraint_pipeline.constrain() → extra_body  # vLLM-specific
    → emit ModelRequestEvent  (1st — BUG: also emitted in run())
    → client.chat_completion(messages, tools, extra_body)
    → emit ModelResponseEvent
    → adapter.response_parser.parse(content, tool_calls)
    → execute tools → emit ToolCallEvent/ToolResultEvent
  → emit TurnCompleteEvent
  → repeat or terminate
→ RunResult
```

### After (v0.4+)

```
Remora config
  → build_client({model: "hosted_vllm/Qwen/Qwen3-4B", api_key, base_url})
    → LiteLLMClient
  → get_response_parser(model_name) → DefaultResponseParser
  → ConstraintPipeline(grammar_config)  # optional
  → AgentKernel(client, response_parser, constraint_pipeline, tools, observer)

kernel.run(messages, tools, max_turns)
  → kernel.step()
    → Message.to_openai_format() → list[dict]
    → ToolSchema.to_openai_format() → list[dict]
    → if model.startswith("hosted_vllm/"):
        constraint_pipeline.constrain() → extra_body
    → emit ModelRequestEvent  (once — bug fixed)
    → client.chat_completion(messages, tools, extra_body)
      → litellm.acompletion(model="hosted_vllm/...", ...)
    → emit ModelResponseEvent
    → response_parser.parse(content, tool_calls)
    → execute tools → emit ToolCallEvent/ToolResultEvent
  → emit TurnCompleteEvent
  → repeat or terminate
→ RunResult
```

Key differences: no ModelAdapter indirection, provider-aware constraints, single event emission, LiteLLM as transport.

---

## Remora Integration — Before vs After

### Before: Three Execution Paths

```
Path A: SwarmExecutor → kernel_factory → AgentKernel     ← full kernel
Path B: ChatSession   → kernel_factory → AgentKernel     ← full kernel
Path C: LSP Runner    → own LLMClient → own tool loop    ← BYPASSES kernel
```

### After: One Execution Path

```
Path A: SwarmExecutor → kernel_factory → AgentKernel
Path B: ChatSession   → kernel_factory → AgentKernel
Path C: LSP Runner    → kernel_factory → AgentKernel     ← UNIFIED
```

LSP runner tools (`rewrite_self`, `message_node`, `read_node`) become `Tool` Protocol implementations. The runner delegates LLM interaction to the kernel. Cascade prevention, trigger queue, and proposal creation stay in the runner.

---

## File Layout — Before vs After

### Before (21 files)

```
structured_agents/
├── __init__.py          (87 lines)
├── types.py             (167)
├── exceptions.py        (43)
├── kernel.py            (275)
├── agent.py             (167)         ← REMOVED
├── client/
│   ├── __init__.py      (7)
│   ├── protocol.py      (56)
│   └── openai.py        (115)        ← REMOVED
├── models/
│   ├── __init__.py      (14)         ← REMOVED (renamed to parsing/)
│   ├── adapter.py       (40)         ← REMOVED
│   └── parsers.py       (64)
├── grammar/
│   ├── __init__.py      (17)
│   ├── config.py        (20)
│   ├── pipeline.py      (99)
│   └── models.py        (11)
├── events/
│   ├── __init__.py      (28)
│   ├── observer.py      (30)
│   └── types.py         (75)
└── tools/
    ├── __init__.py      (7)
    ├── protocol.py      (17)
    └── grail.py         (99)         ← REMOVED
```

### After (16 files)

```
structured_agents/
├── __init__.py          (~60 lines)
├── types.py             (167)        — unchanged
├── exceptions.py        (~30)        — BundleError/AdapterError removed
├── kernel.py            (~260)       — response_parser + constraint_pipeline as direct fields
├── client/
│   ├── __init__.py      (~15)        — exports + build_client()
│   ├── protocol.py      (56)         — unchanged
│   └── litellm_client.py (~80)       — NEW
├── parsing/
│   ├── __init__.py      (~10)
│   └── parsers.py       (~80)        — DefaultResponseParser + get_response_parser()
├── grammar/
│   ├── __init__.py      (17)         — unchanged
│   ├── config.py        (20)         — unchanged
│   ├── pipeline.py      (99)         — unchanged
│   └── models.py        (11)         — unchanged
├── events/
│   ├── __init__.py      (28)         — unchanged
│   ├── observer.py      (30)         — unchanged
│   └── types.py         (~85)        — frozen Pydantic models (was dataclasses)
└── tools/
    ├── __init__.py      (~5)
    └── protocol.py      (17)         — unchanged
```

---

## Migration Phases (Summary)

| Phase | Scope | Effort | Risk |
|-------|-------|--------|------|
| **0** | Bug fixes: double event, debug prints, parser rename | 30 min | Very low |
| **1** | Add `LiteLLMClient` alongside old client | 2 hrs | Medium |
| **2** | Flatten `ModelAdapter`, move `get_response_parser`, provider-aware constraints | 1.5 hrs | Low-medium |
| **3** | Unify LSP runner onto `AgentKernel` | 4-6 hrs | Medium-high |
| **4** | Convert events to Pydantic | 1 hr | Low |
| **5** | Delete dead code (`Agent`, `GrailTool`, old client) | 30 min | Very low |
| | **Total** | **~10-12 hrs** | |

Each phase is independently shippable. Phase 3 is the bulk of the work and the biggest win.

---

## Gating Question

**`extra_body` passthrough with LiteLLM:** Does `litellm.acompletion(model="hosted_vllm/...", extra_body={"structured_outputs": {...}})` forward the payload to vLLM? This must be verified before Phase 1 ships. If it fails, `OpenAICompatibleClient` stays as a vLLM-only fallback.
