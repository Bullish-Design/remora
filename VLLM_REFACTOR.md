# vLLM Server Refactor Plan

This document is the authoritative plan for transitioning Remora from an
Ollama-based, client-local inference model to a vLLM server hosted on the
user's Tailscale network. It covers every file that changes, everything new
that must be created, and a section on server-side opportunities — ways the
hosted container can take over work currently done by the client library.

---

## Table of Contents

1. [What We're Changing and Why](#1-what-were-changing-and-why)
2. [Architecture Transition](#2-architecture-transition)
3. [Changes to Existing Code](#3-changes-to-existing-code)
4. [Changes to Existing Documentation](#4-changes-to-existing-documentation)
5. [New Code to Create](#5-new-code-to-create)
6. [New Documentation to Create](#6-new-documentation-to-create)
7. [Server-Side Opportunities](#7-server-side-opportunities)
8. [Migration Checklist](#8-migration-checklist)

---

## 1. What We're Changing and Why

### Current state

The remora library currently uses the `llm` Python library with the
`llm-ollama` plugin to call a locally-running Ollama instance for inference.
Each `FunctionGemmaRunner` instantiates a model handle via `llm.get_model()`
and drives a multi-turn conversation loop with blocking executor calls.

This works for single-user development, but it has a fundamental ceiling: Ollama
was designed for one-at-a-time, pull-model-then-run usage. Under the concurrent
load that remora is designed for — dozens of tiny agent instances firing async
requests simultaneously — Ollama queues requests sequentially and lacks the
scheduling primitives to keep the GPU fully saturated.

### What changes

We replace Ollama with a self-hosted vLLM server running `google/functiongemma-270m-it`
with Multi-LoRA support. The server lives in a Docker container on the user's
Windows/Linux machine and is reachable from any device on their Tailscale
network. The remora client library becomes a thin HTTP client talking to the
vLLM OpenAI-compatible API.

### What stays the same

- CST node discovery (pydantree, tree-sitter queries) — runs on client
- Subagent YAML definitions and tool schemas — stays in `agents/`
- Cairn sandbox for tool execution (`.pym` scripts) — must run client-side
  because tools read/write the user's local filesystem
- Multi-turn conversation loop logic — stays in `FunctionGemmaRunner`
- Result formatting, accept/reject workflow — unchanged
- All existing unit tests (mock the HTTP client, not the llm library)

---

## 2. Architecture Transition

### Before (Ollama / local)

```
User's machine
─────────────────────────────────────────────────
CLI → Coordinator → FunctionGemmaRunner
                         │
                         ├─ llm.get_model() ──► Ollama process (localhost)
                         │                        └─ GGUF model loaded in RAM
                         │
                         └─ CairnClient ──► .pym tool scripts
                                              └─ user's filesystem
```

### After (vLLM / Tailscale)

```
User's machine (client)              Tailscale network
──────────────────────────           ─────────────────────────────────────────
CLI → Coordinator                    function-gemma-server:8000
        └─ FunctionGemmaRunner            │
               │                          ├─ vLLM (OpenAI-compatible API)
               ├─ openai.AsyncOpenAI ────►│   ├─ base model (FunctionGemma 270M)
               │   (HTTP over Tailscale)  │   ├─ LoRA adapter: lint
               │                          │   ├─ LoRA adapter: test
               └─ CairnClient ──► .pym    │   ├─ LoRA adapter: docstring
                    tool scripts           │   └─ LoRA adapter: sample_data
                    └─ user's filesystem  └─ Tailscale sidecar (networking)
```

### Key properties of the new model

- **No local model weights required.** The client only needs Python + network access.
- **Concurrency handled server-side.** vLLM's continuous batching and PagedAttention
  absorb all simultaneous requests from multiple `FunctionGemmaRunner` instances.
- **Adapter selection via `model` parameter.** The client selects which LoRA adapter
  to invoke by setting the `model` field in the API request (e.g., `"lint"`,
  `"docstring"`). No separate server process per adapter.
- **Tailscale provides security.** No API key management, no TLS configuration;
  the VPN mesh handles access control.

---

## 3. Changes to Existing Code

### 3.1 `remora/config.py`

**What changes:**

Add a new `ServerConfig` Pydantic model and wire it into `RemoraConfig`.
Remove the `model_id` global field from `RemoraConfig` (it moves into
`ServerConfig` as the default adapter name). Update `OperationConfig.model_id`
to be the adapter name passed to vLLM rather than an `llm`-plugin model string.

```python
class ServerConfig(BaseModel):
    base_url: str = "http://function-gemma-server:8000/v1"
    api_key: str = "EMPTY"
    timeout: int = 120
    default_adapter: str = "google/functiongemma-270m-it"
```

`RemoraConfig`:
- Remove `model_id: str = "ollama/functiongemma-4b-it"`
- Add `server: ServerConfig = Field(default_factory=ServerConfig)`
- `OperationConfig.model_id` is now an adapter name (e.g. `"lint"`) or `None`
  to fall back to `server.default_adapter`

`RunnerConfig`:
- `max_concurrent_runners` can stay but its meaning changes: it now limits
  how many *tool executions* run concurrently on the client, not how many
  inference requests are in-flight (vLLM handles those itself). Consider
  raising the default from `4` to `16` or removing the semaphore entirely
  for the MVP.

**Error codes affected:**
- `CONFIG_003`, `CONFIG_004` — unchanged
- New warning: if `server.base_url` uses a hostname that is not reachable,
  emit a clear warning on startup rather than letting the first HTTP call fail
  silently.

---

### 3.2 `remora/runner.py`

**What changes — this is the biggest single change.**

The `llm` import, `llm.get_model()`, model caching, and all `llm.Model`/
`llm.Conversation` API calls are replaced with an `openai.AsyncOpenAI` client.

**Imports to remove:**
- `import llm` and the `_MissingLLM` shim

**Imports to add:**
- `from openai import AsyncOpenAI`
- `from openai import APIConnectionError, APITimeoutError`

**`FunctionGemmaRunner` dataclass changes:**

```python
@dataclass
class FunctionGemmaRunner:
    definition: SubagentDefinition
    node: CSTNode
    workspace_id: str
    cairn_client: CairnClient
    server_config: ServerConfig          # NEW: replaces model_id
    adapter_name: str | None = None      # NEW: LoRA adapter to request
    messages: list[dict[str, Any]] = field(init=False)
    turn_count: int = field(init=False)
    _http_client: AsyncOpenAI = field(init=False)
    _system_prompt: str = field(init=False)
    _model_target: str = field(init=False)
```

`__post_init__`:
- Remove `llm.get_model()` call
- Instantiate `AsyncOpenAI(base_url=server_config.base_url, api_key=server_config.api_key)`
- Resolve `_model_target = adapter_name or server_config.default_adapter`
- Build system prompt and initial message as before (no change to that logic)
- On connection failure (caught in `run()`), raise `AgentError` with `AGENT_002`

`run()` method:
- Replace `self._prompt(conversation, message)` with a direct call to
  `self._http_client.chat.completions.create()`
- No more `_start_conversation()` — maintain `self.messages` list manually
  (already started in `__post_init__`)
- The multi-turn loop logic remains identical; only the "how do I get a
  response from the model" part changes

`_prompt()` replacement:

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

**Remove entirely:**
- `_start_conversation()`
- `_response_text()` static method
- The `_use_native_tools` flag and native-tools branching (vLLM exposes the
  OpenAI tool-calling interface natively; for MVP keep the existing JSON-in-
  text approach to minimise changes to agent YAML files and the parser)

**`AGENT_002` error** — change the message from "Model not available in Ollama"
to "Cannot reach vLLM server at {base_url}".

**`_parse_tool_calls()`** — no change needed; FunctionGemma's tool-calling
output format is the same regardless of the serving backend.

---

### 3.3 `remora/orchestrator.py`

**What changes:**

`Coordinator.__init__` takes a `ServerConfig` instead of relying on a global
model_id from `RemoraConfig.model_id`. Thread through `server_config` when
constructing `FunctionGemmaRunner` instances.

```python
class Coordinator:
    def __init__(
        self,
        config: RemoraConfig,
        cairn_client: CairnClient,
    ) -> None:
        self.config = config
        self.cairn_client = cairn_client
        self._semaphore = asyncio.Semaphore(config.runner.max_concurrent_runners)
```

In `process_node()`, change runner construction:

```python
runners[operation] = FunctionGemmaRunner(
    definition=definition,
    node=node,
    workspace_id=f"{operation}-{node.node_id}",
    cairn_client=self.cairn_client,
    server_config=self.config.server,      # NEW
    adapter_name=op_config.model_id,       # adapter name or None
)
```

Remove the `model_id` resolution chain that was: `op_config.model_id or
definition_model_id or self.config.model_id`.

---

### 3.4 `pyproject.toml`

**Dependencies to remove:**
```
llm
llm-ollama
```

**Dependencies to add:**
```
openai>=1.0
```

The `llm` library was also used as a dev/smoke-test tool (`llm -m ollama/...`).
That workflow is replaced by `curl` or the `test_connection.py` script (see
`server/` directory). Remove the Ollama verification step from Milestone 1 of
the roadmap.

**Optional dev deps** — keep `httpx` if it isn't already pulled in by `openai`;
it is used for mocking HTTP calls in tests.

---

### 3.5 `remora.yaml.example`

**Add `server` section; remove `model_id` top-level field:**

```yaml
# remora.yaml.example

root_dirs:
  - "."

queries:
  - function_def
  - class_def

agents_dir: "agents"

# vLLM server on your Tailscale network
server:
  base_url: "http://function-gemma-server:8000/v1"
  api_key: "EMPTY"
  timeout: 120
  default_adapter: "google/functiongemma-270m-it"

operations:
  lint:
    enabled: true
    subagent: "lint/lint_subagent.yaml"
    # model_id here is the LoRA adapter name on the server
    # omit to use server.default_adapter
    # model_id: "lint"
  test:
    enabled: true
    subagent: "test/test_subagent.yaml"
  docstring:
    enabled: true
    subagent: "docstring/docstring_subagent.yaml"
    style: "google"
  sample_data:
    enabled: false
    subagent: "sample_data/sample_data_subagent.yaml"

runner:
  max_turns: 20
  max_concurrent_runners: 16   # raised: vLLM handles actual inference concurrency
  timeout: 300

cairn:
  timeout: 120
```

---

### 3.6 `agents/*/lint_subagent.yaml` (and all subagent YAMLs)

**What changes:**

Remove the `model:` field from each subagent YAML (or leave it as a comment).
The model/adapter selection now lives in `remora.yaml` under `operations.<name>.model_id`
and `server.default_adapter`. The subagent YAML should no longer be the source
of truth for which model to call.

Before:
```yaml
model: ollama/functiongemma-4b-it
```

After: field removed or commented out. The `SubagentDefinition.model_id` field
in `remora/subagent.py` becomes optional with `None` as the default, and the
fallback chain uses `server.default_adapter` rather than a hardcoded Ollama string.

---

### 3.7 `README.md`

**What changes:**

Replace the Ollama setup section entirely. New flow:
1. Ensure Tailscale is installed on this machine and the server machine
2. Start the server (see `server/README.md`)
3. Verify with `uv run server/test_connection.py`
4. Configure `remora.yaml` with the server's Tailscale hostname
5. Run `remora analyze <path>`

---

## 4. Changes to Existing Documentation

### 4.1 `docs/ARCHITECTURE.md`

**Sections that need rewriting:**

- **Technology Stack table** — replace `llm`, `llm-ollama`, `Ollama` rows with
  `openai` Python SDK, `vLLM`, `Docker + Tailscale`
- **FunctionGemma Runner section** — rewrite the model initialization and
  prompting subsections to describe HTTP calls rather than `llm.Model`
- **Concurrency Model section** — the client-side semaphore still limits tool
  execution parallelism, but the "model caching" and "operation-level
  parallelism" notes about Ollama's single-model-at-a-time limitation should
  be replaced with a description of vLLM's server-side batching
- **Local execution / zero network egress** core principle — this changes.
  Replace with "server-local execution: all inference runs on hardware you own,
  reachable only over your private Tailscale network"
- Add a new **Server Architecture** subsection describing the Tailscale sidecar
  pattern and the Docker Compose stack

**Sections that do not need to change:**

- Node discovery layer (pydantree / tree-sitter)
- Cairn execution layer
- Subagent definition system / YAML format
- Workspace management
- Accept/reject/retry workflow
- CLI layer

---

### 4.2 `docs/SPEC.md`

**Sections that need updating:**

- **Configuration Schema** — add `ServerConfig` model spec; update `model_id`
  description in `OperationConfig` to read "LoRA adapter name to request from
  the vLLM server"; remove the global `model_id` from `RemoraConfig` spec
- **Error Codes** — update `AGENT_002` description from "Model not available in
  Ollama" to "vLLM server not reachable or adapter not found"; add new
  `SERVER_001` for unreachable server at startup
- **Extension Points** section — replace "custom `llm` plugins" with "custom
  LoRA adapters registered with the vLLM server"

---

### 4.3 `docs/OLLAMA_SETUP_GUIDE.md`

Archive this file. Rename it to `docs/archive/OLLAMA_SETUP_GUIDE.md` and add a
header note:

```
# [ARCHIVED] Ollama Setup Guide
This guide applied to the pre-vLLM version of remora. See docs/SERVER_SETUP.md
for the current setup procedure.
```

Do not delete it — it remains useful as historical reference for anyone who
wants to run a development-only local setup without the server.

---

### 4.4 `.roadmap/ROADMAP.md`

**Milestones to update:**

- **Milestone 1** (Project Skeleton): Remove `llm-ollama` from dependency list;
  add `openai`; replace the Ollama smoke test with a server connectivity check
- **Milestone 2** (Configuration System): Add `ServerConfig` to the deliverable
  list; update verification step
- **Milestone 5** (Runner — Model Loading): Rewrite; model loading is now
  "instantiate `AsyncOpenAI` client and verify connectivity"
- **Milestone 12** (Runner Adaptation for `llm` library): Rename this milestone.
  It was about replacing `llama-cpp-python` with the `llm` library. It now
  becomes "Replace `llm` library with `openai` HTTP client"; update all
  deliverable and verification bullets accordingly
- **Milestone 13** (End-to-End Integration Test): Update skip condition from
  "when Ollama is not reachable" to "when vLLM server is not reachable"

**New milestone to add** (insert before Milestone 1, or as Milestone 0):

```markdown
## 0. vLLM Server Setup

**Goal:** Get the vLLM inference server running and reachable over Tailscale.

**Deliverables:**
- `server/` directory committed to the repo with Dockerfile, Dockerfile.tailscale,
  docker-compose.yml, entrypoint.sh, update.sh
- Base model (`google/functiongemma-270m-it`) downloading and loading successfully
- Server reachable at `http://function-gemma-server:8000/v1`

**Verification:**
- `uv run server/test_connection.py` prints success message
- `docker logs -f vllm-gemma` shows model fully loaded
- Server hostname resolves from a second Tailscale-connected machine
```

---

## 5. New Code to Create

### 5.1 `server/` Directory

This directory contains everything needed to stand up and maintain the vLLM
inference server. It is self-contained and can be deployed to any Linux machine
(physical or WSL2) with Docker and an NVIDIA GPU.

```
server/
├── Dockerfile              # vLLM container
├── Dockerfile.tailscale    # Ops-ready Tailscale sidecar (git + docker CLI)
├── docker-compose.yml      # Full stack
├── entrypoint.sh           # vLLM startup script (LoRA flags commented for easy toggling)
├── update.sh               # One-command redeploy via SSH
├── test_connection.py      # PEP 723 script; run with `uv run server/test_connection.py`
└── README.md               # Setup guide
```

#### `server/Dockerfile`

```dockerfile
FROM vllm/vllm-openai:latest

WORKDIR /app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
```

#### `server/Dockerfile.tailscale`

Wraps the stock Tailscale image to add `git` and the Docker CLI so you can
SSH in and redeploy without ever touching the Windows desktop.

```dockerfile
FROM tailscale/tailscale:latest

RUN apk update && \
    apk add --no-cache git docker-cli docker-cli-compose bash

WORKDIR /app
```

#### `server/docker-compose.yml`

```yaml
services:
  tailscale:
    build:
      context: .
      dockerfile: Dockerfile.tailscale
    container_name: tailscale-vllm
    hostname: function-gemma-server
    environment:
      - TS_AUTHKEY=tskey-auth-YOUR_KEY_HERE
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_SSH=true
    volumes:
      - tailscale-data:/var/lib/tailscale
      - /dev/net/tun:/dev/net/tun
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/app
    cap_add:
      - net_admin
      - sys_module
    restart: unless-stopped

  vllm-server:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: vllm-gemma
    network_mode: service:tailscale
    depends_on:
      - tailscale
    environment:
      - HUGGING_FACE_HUB_TOKEN=hf_YOUR_TOKEN_HERE
      - VLLM_CACHE_ROOT=/models/cache
      - HF_HOME=/models/cache
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      # Adjust drive letters to match your SSD layout.
      # WSL2 sees Windows drives under /mnt/ (D: → /mnt/d/)
      - /mnt/d/AI_Models/base:/models/base
      - /mnt/e/AI_Models/adapters:/models/adapters
      - /mnt/d/AI_Models/cache:/models/cache
    ipc: host
    restart: unless-stopped

volumes:
  tailscale-data:
```

#### `server/entrypoint.sh`

```bash
#!/bin/bash

# Serving only the base model by default.
# The model is pulled from Hugging Face on first boot and cached to /models/cache.
# Uncomment the Multi-LoRA section once your fine-tuned adapters are trained.

python3 -m vllm.entrypoints.openai.api_server \
    --model google/functiongemma-270m-it \
    --max-num-seqs 256 \
    --enable-prefix-caching

    # -----------------------------------------------------------------------
    # MULTI-LORA CONFIGURATION (uncomment when LoRA adapters are ready)
    # -----------------------------------------------------------------------
    # --enable-lora \
    # --max-loras 20 \
    # --max-lora-rank 32 \
    # --lora-modules \
    #     lint=/models/adapters/lint \
    #     test=/models/adapters/test \
    #     docstring=/models/adapters/docstring \
    #     sample_data=/models/adapters/sample_data
```

#### `server/update.sh`

Run this after SSH-ing into the Tailscale sidecar to pull and redeploy.

```bash
#!/bin/bash
# update.sh — run from inside the tailscale container via:
#   ssh root@function-gemma-server
#   ./update.sh

echo "Pulling latest changes from Git..."
git pull origin main

echo "Rebuilding and restarting vLLM container..."
docker compose up -d --build vllm-server

echo "Tailing vLLM logs..."
docker logs -f vllm-gemma
```

#### `server/test_connection.py`

PEP 723 inline-dependency script. Run from any Tailscale-connected machine
with `uv run server/test_connection.py` — no virtualenv needed.

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "openai",
# ]
# ///

import asyncio
from openai import AsyncOpenAI

SERVER_URL = "http://function-gemma-server:8000/v1"
MODEL_NAME = "google/functiongemma-270m-it"


async def test_base_model() -> None:
    print(f"Connecting to vLLM at {SERVER_URL} over Tailscale...")

    client = AsyncOpenAI(base_url=SERVER_URL, api_key="EMPTY")

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with: 'Connection successful.'"},
            ],
            max_tokens=20,
            temperature=0.1,
        )
        reply = response.choices[0].message.content or ""
        print(f"SUCCESS: {reply.strip()}")
    except Exception as exc:
        print(f"FAILED: {exc}")
        print("Is the container fully booted? Is Tailscale connected?")


if __name__ == "__main__":
    asyncio.run(test_base_model())
```

---

### 5.2 `remora/client.py` (new file)

A thin wrapper around `AsyncOpenAI` that owns the connection and is shared
across all `FunctionGemmaRunner` instances spawned by a `Coordinator`. This
prevents each runner from opening its own connection pool.

```python
"""Shared async HTTP client for vLLM communication."""

from __future__ import annotations

from openai import AsyncOpenAI
from remora.config import ServerConfig


def build_client(server_config: ServerConfig) -> AsyncOpenAI:
    """Return a configured AsyncOpenAI client for the vLLM server."""
    return AsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
    )
```

The `Coordinator` creates one client on init and passes it down to each
`FunctionGemmaRunner`, replacing the per-runner instantiation pattern.

---

### 5.3 `remora/errors.py` additions

Add two new error codes:

```python
SERVER_001 = "SERVER_001"   # vLLM server not reachable at startup
SERVER_002 = "SERVER_002"   # Adapter not found on vLLM server
```

`AGENT_002` remains but its message text changes (see §3.2).

---

## 6. New Documentation to Create

### 6.1 `docs/SERVER_SETUP.md`

A complete, self-contained guide for setting up the vLLM server. Target
audience: developer who has the repo checked out and wants to get the server
running for the first time.

**Sections to include:**

1. **Prerequisites** — NVIDIA GPU with drivers, Docker Desktop (WSL2 backend),
   Tailscale installed on both the server machine and the dev machine
2. **Storage layout** — how to map SSD drives; which drives to use for base
   model vs adapters vs cache; the Docker ext4.vhdx tip
3. **Configuration** — where to put the `TS_AUTHKEY` and `HF_TOKEN`;
   what the volume mount paths mean
4. **First boot** — `docker compose up -d --build`; how to watch the model
   download via `docker logs -f vllm-gemma`
5. **Verification** — `uv run server/test_connection.py`
6. **Subsequent deploys** — SSH into `function-gemma-server`, run `./update.sh`
7. **Enabling LoRA adapters** — uncomment the multi-LoRA flags in
   `entrypoint.sh`; where to place adapter directories; how to reference
   adapters from `remora.yaml`
8. **Troubleshooting** — common errors (OOM, adapter not found, Tailscale not
   connected)

### 6.2 `server/README.md`

A shorter quick-reference version of `docs/SERVER_SETUP.md`. Four sections:
prerequisites, bring-up commands, verify, and redeploy.

---

## 7. Server-Side Opportunities

This section documents functionality that currently runs on the client that
could be relocated to the Docker container, along with the trade-offs of each.
These are options for future enhancements — none are required for MVP.

---

### 7.1 Subagent Definition Serving (High Value / Low Complexity)

**Current:** Each user must have a complete `agents/` directory on their local
machine with all YAML files, `.pym` tool scripts, and context providers.

**Opportunity:** The vLLM container could also run a simple FastAPI or Flask
app (or even just an nginx static file server) that serves the `agents/`
directory over HTTP. The remora client would fetch the subagent YAML on first
use and cache it locally.

**Benefits:**
- Update agent definitions in one place (the server repo) and all users get
  them automatically on next run.
- The client package becomes smaller — no bundled YAML files, no `agents/`
  directory requirement.
- Enables centralized prompt engineering: change the system prompt or tool
  schema, push to the server, all connected clients benefit.

**Considerations:**
- `.pym` tool scripts still need to run locally (they touch the user's
  filesystem), so the client would still need those.
- Alternatively, the client could fetch only the YAML portion and look for
  `.pym` scripts at a local override path, falling back to server-provided
  defaults.

---

### 7.2 System Prompt Construction (Medium Value / Low Complexity)

**Current:** `FunctionGemmaRunner._build_system_prompt()` assembles the full
system prompt string on the client, embedding the full JSON tool schema blob
into it.

**Opportunity:** The server could expose a `/v1/system-prompt/{adapter-name}`
endpoint that returns the pre-built system prompt for a given adapter. Since
the tool schemas are static per adapter, this string is the same for every
request using that adapter — prime territory for server-side caching.

**Benefits:**
- Removes JSON schema serialization from the client hot path.
- Server can cache the result indefinitely; clients get a pre-computed string.
- Keeps the system prompt logic co-located with the model and adapter
  definitions on the server, where it is easier to version and update.

**Considerations:**
- For MVP, this optimization is not meaningful — the serialization is trivial.
- Only worth doing once the number of connected clients is large enough that
  the repeated serialization cost registers.

---

### 7.3 Prefix Caching Exploitation (High Value / Zero Code Required)

**Current:** vLLM's `--enable-prefix-caching` flag is already in
`server/entrypoint.sh`. This is an existing server-side feature, not new
code.

**Opportunity:** Structure the system prompt so that the shared prefix (system
prompt + tool schema block) is maximally long and identical across all requests
for the same adapter. This turns vLLM's prefix cache into a major throughput
multiplier: the expensive prefill computation for the tool schema is performed
exactly once per adapter per server restart, then served from cache for all
subsequent requests.

**Benefits:**
- Zero client code changes. This is purely about how you construct the message list.
- Benchmark potential: with a 2 KB shared system prompt across 100 concurrent
  requests, the server effectively does 1 prefill computation instead of 100.

**What to do:**
- Keep the system prompt and tool schema at the very beginning of the message
  list, before any node-specific content.
- The node-specific `initial_context` (which varies per request) should come
  after the static portion in the user turn, not baked into the system prompt.
- This may require minor restructuring of how `_build_system_prompt()` and
  `InitialContext.render()` currently work.

---

### 7.4 Adapter Hot-Loading via Server API (Medium Value / Medium Complexity)

**Current:** LoRA adapters are registered at server startup via `--lora-modules`
flags in `entrypoint.sh`. Adding a new adapter requires restarting the container.

**Opportunity:** vLLM exposes a `POST /v1/load_lora_adapter` API endpoint that
allows registering new adapters without restarting. The remora client (or a
separate management CLI) could call this endpoint to hot-load a newly trained
adapter.

**Benefits:**
- Training a new LoRA adapter and making it available takes seconds, not
  minutes (no container restart).
- Enables a future "train and deploy" workflow: `remora train lint --push-to-server`.

**What to do:**
- Add a `server.py` management script in `server/` that wraps the vLLM
  adapter API.
- Wire it into the training pipeline once adapters are being trained.

---

### 7.5 Request Routing / Adapter Dispatch (Low Value for MVP)

**Current:** The client selects an adapter by setting the `model` parameter in
the API request. This is a one-line decision in `FunctionGemmaRunner`.

**Opportunity:** An intermediate routing layer (a tiny FastAPI proxy in front
of vLLM) could inspect the request, select the best adapter based on metadata
(e.g., file type, operation type, measured node complexity), and forward to
vLLM with the appropriate `model` parameter.

**Benefits:**
- Decouples adapter selection from the client. Clients could send generic
  requests without knowing adapter names.
- Enables server-side A/B testing between adapter versions.
- Could dynamically load-balance across adapter variants.

**Considerations:**
- Adds a hop and latency.
- For MVP, the client is the right place to select adapters — it has full
  context about the node type and operation being performed.
- Worth revisiting once adapter training is mature and multiple adapter versions
  exist.

---

### 7.6 Cairn Workspace Hosting (Speculative / High Complexity)

**Current:** Cairn creates copy-on-write workspaces on the user's local
filesystem. All `.pym` tool scripts read and write files through this local
sandbox.

**Opportunity:** For users running remora in a pure CI/remote context (e.g.,
analyzing a Git repository that lives on a remote server), the entire Cairn
sandbox could run on the server container. The vLLM container would receive a
tarball of the target code, run the tools, and return the diff.

**Benefits:**
- Enables fully remote analysis without the user having the code locally.
- Opens the door to a server-as-a-service model.

**Considerations:**
- This is a significant architectural change. The `.pym` tool scripts have deep
  OS-level access to the workspace path; porting them to a remote execution
  model requires a well-defined RPC protocol.
- Security surface expands significantly: the server now receives and executes
  arbitrary code.
- Not appropriate for MVP. File this as a long-term architectural option.

---

## 8. Migration Checklist

Use this checklist to track implementation progress.

### Code changes

- [ ] `remora/config.py` — add `ServerConfig`, remove global `model_id`
- [ ] `remora/runner.py` — replace `llm` with `openai.AsyncOpenAI`
- [ ] `remora/orchestrator.py` — pass `server_config` to runner
- [ ] `remora/client.py` — create shared client module
- [ ] `remora/errors.py` — add `SERVER_001`, `SERVER_002`
- [ ] `pyproject.toml` — remove `llm`, `llm-ollama`; add `openai`
- [ ] `remora.yaml.example` — add `server` section
- [ ] `agents/*/lint_subagent.yaml` — remove or comment `model:` field
- [ ] `agents/*/test_subagent.yaml` — same
- [ ] `agents/*/docstring_subagent.yaml` — same
- [ ] `agents/*/sample_data_subagent.yaml` — same
- [ ] `README.md` — replace Ollama setup with server pointer

### Server directory

- [ ] `server/Dockerfile`
- [ ] `server/Dockerfile.tailscale`
- [ ] `server/docker-compose.yml`
- [ ] `server/entrypoint.sh`
- [ ] `server/update.sh`
- [ ] `server/test_connection.py`
- [ ] `server/README.md`

### Documentation updates

- [ ] `docs/ARCHITECTURE.md` — rewrite inference layer, concurrency model, tech stack
- [ ] `docs/SPEC.md` — update config schema, error codes, extension points
- [ ] `docs/OLLAMA_SETUP_GUIDE.md` → move to `docs/archive/`
- [ ] `.roadmap/ROADMAP.md` — update milestones 0 (new), 1, 2, 5, 12, 13
- [ ] `docs/SERVER_SETUP.md` — create new

### Tests

- [ ] Update unit tests for `runner.py` — mock `AsyncOpenAI.chat.completions.create`
  instead of `llm.get_model()` and `llm.Model.conversation()`
- [ ] Update `tests/conftest.py` integration skip condition from Ollama reachability
  check to vLLM server reachability check
- [ ] Update `test_config.py` — add `ServerConfig` validation tests
- [ ] Add `tests/test_client.py` — verify `build_client()` produces correct configuration

### Deployment smoke test

- [ ] `docker compose up -d --build` succeeds in `server/`
- [ ] `docker logs -f vllm-gemma` shows model fully loaded
- [ ] `uv run server/test_connection.py` returns success from dev machine
- [ ] `ssh root@function-gemma-server ./update.sh` completes without error
- [ ] `remora analyze <path>` succeeds against a Python file in the repo
