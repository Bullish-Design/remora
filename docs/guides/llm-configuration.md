# LLM Configuration

> Connecting Remora to language models — local or remote

## Table of Contents

1. [Overview](#1-overview) — How Remora talks to LLMs and what you can configure
2. [Quick Start](#2-quick-start) — Minimal configuration to get a model running
3. [Running vLLM Locally](#3-running-vllm-locally) — Setting up a local Qwen model with vLLM
4. [Using External APIs](#4-using-external-apis) — OpenAI, Anthropic, and other providers
5. [Configuration Reference](#5-configuration-reference) — All model-related fields in `remora.yaml`
6. [Model Resolution Order](#6-model-resolution-order) — How Remora decides which model to use
7. [Per-Bundle Model Overrides](#7-per-bundle-model-overrides) — Different models for different agent types
8. [Response Parsers](#8-response-parsers) — How model output gets parsed into tool calls
9. [Connection Pooling and Performance](#9-connection-pooling-and-performance) — Client reuse and concurrency
10. [Timeouts and Limits](#10-timeouts-and-limits) — Controlling agent execution bounds
11. [Environment Variables](#11-environment-variables) — All `REMORA_*` overrides and `${VAR}` expansion
12. [Troubleshooting](#12-troubleshooting) — Common issues and fixes

---

## 1. Overview

Remora communicates with language models through an **OpenAI-compatible API**. Any server that implements the `/v1/chat/completions` endpoint works — vLLM with a local GPU, a cloud-hosted OpenAI endpoint, or a proxy that translates other providers into the OpenAI format.

The model configuration has three layers:

1. **Project-level** — `remora.yaml` sets the default base URL, API key, and model name.
2. **Bundle-level** — Each agent bundle's `bundle.yaml` can override the model name for that agent type.
3. **Environment-level** — `REMORA_*` environment variables override everything, and `${VAR:-default}` patterns expand inside `remora.yaml` values.

All agent execution flows through the `SwarmExecutor`, which resolves the final model name, reuses a shared HTTP client, builds the prompt, and delegates to an `AgentKernel` for the actual LLM call.

---

## 2. Quick Start

The minimal configuration to start using Remora with a language model:

```yaml
# remora.yaml
model_base_url: "http://localhost:8000/v1"
model_default: "Qwen/Qwen3-4B"
model_api_key: ""
```

If you are running vLLM locally on the default port, this is all you need — Remora defaults to `http://localhost:8000/v1` with an empty API key.

For an external API like OpenAI:

```yaml
model_base_url: "https://api.openai.com/v1"
model_default: "gpt-4o"
model_api_key: "${OPENAI_API_KEY}"
```

The `${OPENAI_API_KEY}` syntax reads the value from your shell environment at startup (see [Section 11](#11-environment-variables)).

---

## 3. Running vLLM Locally

[vLLM](https://docs.vllm.ai/) is the recommended way to run a local model. It provides an OpenAI-compatible API server with high throughput, batched inference, and native tool calling support.

### Basic Setup

```bash
# Install vLLM
pip install vllm

# Serve a Qwen3 model with tool calling enabled
vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice
```

The two flags are **required** for Remora's tool calling to work:

| Flag | Purpose |
|------|---------|
| `--enable-auto-tool-choice` | Lets the model decide when to call tools |
| `--tool-call-parser qwen3_xml` | Parses Qwen3's XML-style tool call output |

> **Note:** Use `qwen3_xml` instead of `qwen3_coder`. The `qwen3_coder` parser has a known bug that causes endless generation with structured output. See [QwenLM/Qwen3#1700](https://github.com/QwenLM/Qwen3/issues/1700).

### Performance Flags

For production or heavy use, add these:

```bash
vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice \
    --max-num-seqs 32 \
    --max-model-len 32768 \
    --enable-prefix-caching
```

| Flag | Purpose |
|------|---------|
| `--max-num-seqs 32` | Maximum concurrent sequences (batch size). Increase if running many agents concurrently. |
| `--max-model-len 32768` | Maximum context length in tokens. 32K is sufficient for most Remora use cases. |
| `--enable-prefix-caching` | Caches shared prompt prefixes across requests. Helps when multiple agents share similar system prompts. |

### GPU Memory

The 4B parameter FP8 model requires roughly 4-6 GB of VRAM. For larger models:

| Model | Approximate VRAM |
|-------|-----------------|
| Qwen3-4B-FP8 | ~5 GB |
| Qwen3-8B-FP8 | ~9 GB |
| Qwen3-14B-FP8 | ~16 GB |

If you are memory-constrained, vLLM supports quantization via AWQ and GPTQ formats. Pass the quantized model name directly:

```bash
vllm serve Qwen/Qwen3-4B-AWQ --tool-call-parser qwen3_xml --enable-auto-tool-choice
```

### Verifying the Server

Once vLLM is running, test the endpoint:

```bash
curl http://localhost:8000/v1/models
```

You should see your model listed. Remora will connect to this endpoint automatically with default settings.

---

## 4. Using External APIs

Remora works with any OpenAI-compatible endpoint. Change `model_base_url` and `model_api_key` to point at the provider.

### OpenAI

```yaml
# remora.yaml
model_base_url: "https://api.openai.com/v1"
model_default: "gpt-4o"
model_api_key: "${OPENAI_API_KEY}"
```

### Any OpenAI-Compatible Provider

Many providers (Together AI, Groq, Fireworks, etc.) expose an OpenAI-compatible API:

```yaml
# remora.yaml
model_base_url: "https://api.together.xyz/v1"
model_default: "meta-llama/Llama-3-70b-chat-hf"
model_api_key: "${TOGETHER_API_KEY}"
```

### Anthropic (via Proxy)

Anthropic's API is not OpenAI-compatible natively. To use Claude models, run a proxy that translates between the two formats (e.g., [LiteLLM](https://github.com/BerriAI/litellm)):

```bash
litellm --model anthropic/claude-sonnet-4-20250514 --port 4000
```

Then point Remora at the proxy:

```yaml
model_base_url: "http://localhost:4000/v1"
model_default: "anthropic/claude-sonnet-4-20250514"
model_api_key: "${ANTHROPIC_API_KEY}"
```

### Key Requirement

The endpoint must support the `/v1/chat/completions` route and return `tool_calls` in the response when tools are provided. Most OpenAI-compatible servers handle this. If tool calling does not work with a provider, agents will still run but will only produce text responses — they will not be able to use Grail tools.

---

## 5. Configuration Reference

All model-related fields in `remora.yaml`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model_base_url` | string | `"http://localhost:8000/v1"` | Base URL of the OpenAI-compatible API endpoint |
| `model_default` | string | `"Qwen/Qwen3-4B"` | Default model name sent in API requests |
| `model_api_key` | string | `""` | API key. Use `"EMPTY"` or `""` for local servers |
| `timeout_s` | float | `300.0` | HTTP request timeout in seconds |
| `max_turns` | int | `8` | Maximum turns (model call + tool execution cycles) per agent run |
| `max_concurrency` | int | `4` | Maximum number of agents executing simultaneously |
| `truncation_limit` | int | `1024` | Maximum character length for agent response output |
| `chat_history_limit` | int | `5` | Number of recent events to include as chat history in prompts |

All string values support `${VAR:-default}` environment variable expansion (see [Section 11](#11-environment-variables)).

### Full Example

```yaml
# remora.yaml — model configuration
model_base_url: "${REMORA_MODEL_BASE_URL:-http://localhost:8000/v1}"
model_default: "${REMORA_MODEL_DEFAULT:-Qwen/Qwen3-4B}"
model_api_key: "${REMORA_MODEL_API_KEY:-EMPTY}"

timeout_s: 300.0
max_turns: 8
max_concurrency: 4
truncation_limit: 1024
chat_history_limit: 5
```

---

## 6. Model Resolution Order

When an agent runs, Remora determines which model to use through a priority chain. The first non-empty value wins:

```
1. bundle.yaml  →  model.id    (highest priority)
2. bundle.yaml  →  model.name
3. bundle.yaml  →  model.model
4. remora.yaml  →  model_default
5. REMORA_MODEL_DEFAULT env var (lowest priority)
```

In code, this happens in `SwarmExecutor._resolve_model_name()`:

1. Read the agent's `bundle.yaml` file.
2. Look for a `model` key. If it is a dictionary, check `model.id`, then `model.name`, then `model.model`.
3. If none of those are set, fall back to `config.model_default` (which itself may come from the `REMORA_MODEL_DEFAULT` environment variable via Pydantic's `env_prefix`).

### Example

Given this `remora.yaml`:

```yaml
model_default: "Qwen/Qwen3-4B"
```

And this `agents/lint/bundle.yaml`:

```yaml
name: lint
model:
  id: "Qwen/Qwen3-8B"
```

- Agents mapped to the `lint` bundle will use `Qwen/Qwen3-8B`.
- All other agents will use `Qwen/Qwen3-4B`.

---

## 7. Per-Bundle Model Overrides

Each agent bundle can specify its own model, allowing you to use different models for different tasks. This is configured in `bundle.yaml` under the `model` key.

### Model Fields in bundle.yaml

The `model` key can be a simple string (the plugin name) or a dictionary:

```yaml
# Simple — just selects the response parser
model: "qwen"

# Dictionary — override the actual model used for API calls
model:
  plugin: "qwen"          # Response parser (how output is parsed)
  id: "Qwen/Qwen3-8B"    # Model name sent in API requests (overrides remora.yaml)
```

The override fields, checked in order:

| Field | Purpose |
|-------|---------|
| `model.id` | Primary override — the model identifier sent to the API |
| `model.name` | Alternative name field (same effect as `id`) |
| `model.model` | Another alternative (same effect) |
| `model.plugin` | Selects the response parser, not the API model name |

Only the first non-empty value among `id`, `name`, and `model` is used for the API call. The `plugin` field separately controls which response parser handles the output.

### Use Case: Larger Model for Complex Tasks

```yaml
# agents/docstring/bundle.yaml — simple tasks, small model is fine
name: docstring
model:
  plugin: qwen
# No id/name/model → uses remora.yaml model_default (e.g., Qwen3-4B)
```

```yaml
# agents/refactor/bundle.yaml — complex tasks, use a larger model
name: refactor
model:
  plugin: qwen
  id: "Qwen/Qwen3-14B"
```

### Grammar Configuration

The `model` section in `bundle.yaml` can also include grammar constraints for structured output:

```yaml
model:
  plugin: qwen
  grammar:
    mode: ebnf                    # "ebnf", "structural_tag", or "json_schema"
    allow_parallel_calls: false   # Whether the model can call multiple tools at once
    args_format: escaped_strings  # How tool arguments are formatted
    send_tools_to_api: true       # Whether to include tool schemas in the API request
```

The `send_tools_to_api` flag is important: when set to `false`, tool schemas are not sent to the model API (useful when grammar constraints handle tool formatting entirely).

---

## 8. Response Parsers

When the model returns a response, Remora needs to extract text content and tool calls from it. This is handled by **response parsers**, selected automatically based on the model name.

### Parser Registry

| Parser key | Parser class | Notes |
|-----------|-------------|-------|
| `qwen` | `QwenResponseParser` | Default. Handles native `tool_calls` and XML-format fallback. |
| `function_gemma` | `QwenResponseParser` | Same parser — Gemma models use compatible output format. |
| *(any other)* | `QwenResponseParser` | Fallback. All unknown model names default to Qwen parsing. |

The parser is selected in `create_kernel()` via `get_response_parser(model_name)`. Since all entries currently resolve to `QwenResponseParser`, the parser works universally with any model that produces OpenAI-compatible `tool_calls` or Qwen-style XML tool call format:

```
<function=tool_name><parameter=key>value</parameter></function>
```

### How Parsing Works

1. The kernel receives a model response.
2. If the response contains `tool_calls` (native format from vLLM), those are used directly.
3. If `tool_calls` is empty but the response content contains XML-style tool call syntax, the parser extracts tool calls from the raw text.
4. This dual-path approach means tool calling works even when vLLM's parser does not extract the calls properly.

### Which Parser Does My Bundle Use?

The `model.plugin` field in `bundle.yaml` is passed to `get_response_parser()`. Since `load_manifest()` reads this field:

- `model: "qwen"` → `QwenResponseParser`
- `model: { plugin: "qwen" }` → `QwenResponseParser`
- `model: { plugin: "function_gemma" }` → `QwenResponseParser` (same class)

In practice, you do not need to change the parser. It works for all currently supported models.

---

## 9. Connection Pooling and Performance

Remora creates a **single HTTP client** when the `SwarmExecutor` initializes. This client is reused across all agent runs, avoiding the overhead of creating a new connection for each request.

### How It Works

When `SwarmExecutor.__init__()` runs, it calls `build_client()` once with the project-level configuration:

```python
self._client = build_client({
    "base_url": config.model_base_url,
    "api_key": config.model_api_key or "EMPTY",
    "model": config.model_default,
    "timeout": config.timeout_s,
})
```

This client is then passed to every `create_kernel()` call. The kernel uses the shared client for its API requests and does not create its own.

### Benefits

- **Connection reuse** — HTTP keep-alive connections are maintained across requests.
- **Lower latency** — No TCP/TLS handshake overhead per agent run.
- **Resource efficiency** — A single connection pool serves all concurrent agents.

### Concurrency

The `max_concurrency` setting (default `4`) controls how many agents can execute simultaneously. Each concurrent agent shares the same HTTP client. vLLM handles batching on the server side — multiple concurrent requests are batched together for efficient GPU utilization.

For best throughput with a local vLLM server:

- Set `max_concurrency` to match or slightly exceed your vLLM `--max-num-seqs` setting.
- Enable `--enable-prefix-caching` on the vLLM server if agents share similar system prompts.

---

## 10. Timeouts and Limits

Several settings control how long agents can run and how much output they produce.

| Setting | Default | Description |
|---------|---------|-------------|
| `timeout_s` | `300.0` | HTTP request timeout in seconds. If a single model call takes longer than this, it is aborted. |
| `max_turns` | `8` | Maximum number of turns per agent run. One turn = one model call + optional tool execution. |
| `max_concurrency` | `4` | Maximum agents running at the same time. |
| `truncation_limit` | `1024` | Agent response text is truncated to this many characters before being stored. |
| `max_trigger_depth` | `5` | Maximum depth of reactive cascades. Prevents infinite loops where agent A triggers agent B which triggers agent A. |
| `trigger_cooldown_ms` | `1000` | Minimum milliseconds between re-triggering the same agent. |

### Tuning Tips

**Timeout too short?** If you see frequent timeouts with a slow model or long prompts, increase `timeout_s`. For large models (14B+) or cloud APIs with high latency, 600 seconds may be appropriate.

**Agents running too long?** Reduce `max_turns`. Most agents complete useful work in 3-5 turns. Setting `max_turns: 3` keeps agents fast and focused.

**Cascade loops?** If agents keep triggering each other, `max_trigger_depth` is your safety net. The default of 5 allows moderate cascades while preventing runaway chains. `trigger_cooldown_ms` adds a time-based damper.

The `max_turns` setting can also be overridden per bundle in `bundle.yaml`:

```yaml
# bundle.yaml
max_turns: 3
```

If `bundle.yaml` specifies `max_turns`, it takes priority over the `remora.yaml` value.

---

## 11. Environment Variables

Remora supports environment variables at two levels.

### Pydantic `REMORA_*` Prefix

Every config field can be set via an environment variable with the `REMORA_` prefix. Pydantic reads these automatically and they override `remora.yaml` values:

| Environment Variable | Config Field | Example |
|---------------------|-------------|---------|
| `REMORA_MODEL_BASE_URL` | `model_base_url` | `http://localhost:8000/v1` |
| `REMORA_MODEL_DEFAULT` | `model_default` | `Qwen/Qwen3-4B` |
| `REMORA_MODEL_API_KEY` | `model_api_key` | `sk-...` |
| `REMORA_TIMEOUT_S` | `timeout_s` | `600.0` |
| `REMORA_MAX_TURNS` | `max_turns` | `5` |
| `REMORA_MAX_CONCURRENCY` | `max_concurrency` | `8` |

These are read at process startup and take effect immediately.

### `${VAR:-default}` Expansion in YAML

String values in `remora.yaml` support shell-style variable expansion:

```yaml
model_api_key: "${MY_API_KEY}"              # Required — fails if MY_API_KEY is unset
model_api_key: "${MY_API_KEY:-EMPTY}"       # With default — uses "EMPTY" if unset
model_base_url: "${VLLM_URL:-http://localhost:8000/v1}"
```

The expansion happens when `remora.yaml` is loaded, before Pydantic validation. This is useful for:

- Keeping secrets out of config files.
- Switching between local and remote models by changing a single environment variable.
- CI/CD environments where different machines need different URLs.

### Priority Order

When the same field is set in multiple places:

```
REMORA_* env var  >  remora.yaml (after ${VAR} expansion)  >  built-in default
```

Pydantic's `REMORA_*` environment variables always win over `remora.yaml` file values.

---

## 12. Troubleshooting

### "Connection refused" when starting the swarm

The model endpoint is not reachable. Check that:

1. vLLM (or your API server) is running.
2. `model_base_url` in `remora.yaml` matches the server's address and port.
3. There is no firewall blocking the connection.

Test with:

```bash
curl http://localhost:8000/v1/models
```

### Agent runs produce no tool calls

The model is responding with text but not calling tools.

- Ensure vLLM was started with `--enable-auto-tool-choice` and `--tool-call-parser qwen3_xml`.
- Verify the bundle has tools configured (an `agents_dir` with `.pym` scripts or a `tools` section in `bundle.yaml`).
- Check that `grammar.send_tools_to_api` is not set to `false` unless you are using grammar constraints to handle tool formatting.

### Timeouts during agent execution

The model call exceeds `timeout_s` (default 300 seconds).

- Increase `timeout_s` in `remora.yaml`.
- Reduce prompt length by lowering `chat_history_limit`.
- Use a faster model or increase GPU resources.
- Lower `--max-model-len` on the vLLM server to reduce per-request compute.

### Endless generation with vLLM

The model generates output indefinitely and never returns.

- Switch from `--tool-call-parser qwen3_coder` to `--tool-call-parser qwen3_xml`. The `qwen3_coder` parser has a known bug.
- Ensure `max_turns` is set to a reasonable value (default 8).

### Wrong model being used

An agent is using a different model than expected.

- Check the model resolution order (see [Section 6](#6-model-resolution-order)). `bundle.yaml` overrides take priority over `remora.yaml`.
- Run with `REMORA_LOG_LEVEL=DEBUG` or check logs for `"Using model: ..."` messages from the SwarmExecutor.

### API key errors with external providers

The provider returns a 401 or 403 error.

- Verify `model_api_key` is set correctly. Use `${VAR}` expansion to read from the environment.
- For local vLLM servers, use `""` or `"EMPTY"` — Remora sends `"EMPTY"` as the key when the field is blank.

### Empty responses from agents

The model returns but the response content is empty.

- If using grammar constraints, switch from `structural_tag` mode to `ebnf` mode in `bundle.yaml`. The `structural_tag` mode has compatibility issues with some vLLM versions.
- Check that `truncation_limit` is not set too low (default 1024 characters).
