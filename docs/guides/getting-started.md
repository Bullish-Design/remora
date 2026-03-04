# Getting Started

> Install Remora, configure it for your project, and run it for the first time.

## Table of Contents

1. [Installation](#installation) -- Setting up the project with devenv and uv
2. [Project Setup](#project-setup) -- Creating remora.yaml and the .remora directory
3. [Starting an LLM Backend](#starting-an-llm-backend) -- Running vLLM or connecting to an external API
4. [First Run: Reconciliation](#first-run-reconciliation) -- Discovering your codebase
5. [Running the Swarm](#running-the-swarm) -- Starting the reactive agent loop
6. [Running with Neovim (LSP)](#running-with-neovim-lsp) -- Editor integration
7. [Verifying It Works](#verifying-it-works) -- Checking that agents are active

---

## Installation

Remora uses [devenv](https://devenv.sh/) and [uv](https://docs.astral.sh/uv/) for dependency management.

### With devenv (Recommended)

1. Install [devenv](https://devenv.sh/getting-started/) if you haven't already.
2. Clone the repository and enter the devenv shell:

```bash
git clone <remora-repo-url>
cd remora
devenv shell
```

3. Install dependencies with uv:

```bash
uv sync --extra dev
```

This installs Remora with all development dependencies. Available extras:
- `frontend` -- web service and dashboard
- `companion` -- companion tools
- `dev` -- development and testing dependencies (includes both of the above)

### With uv (without devenv)

If you have Python 3.13+ and uv installed:

```bash
uv sync
```

Or with optional extras:

```bash
uv sync --extra frontend --extra companion
```

### Requirements

- Python 3.13+
- An OpenAI-compatible LLM API (see [Starting an LLM Backend](#starting-an-llm-backend))

## Project Setup

### 1. Create `remora.yaml`

In your project root, create a `remora.yaml` file:

```yaml
# remora.yaml -- Remora project configuration

# Where to look for source files
discovery_paths:
  - "src/"

# LLM settings
model_base_url: "http://localhost:8000/v1"
model_api_key: "EMPTY"
model_default: "Qwen/Qwen3-4B-Instruct-2507-FP8"

# Agent bundles (optional -- uses defaults if not specified)
bundle_root: "agents"
bundle_mapping:
  function: "default"
  class: "default"
  file: "default"
```

All settings have sensible defaults. A minimal `remora.yaml` can be just:

```yaml
discovery_paths:
  - "src/"
```

This uses the default model URL (`http://localhost:8000/v1`) and default model (`Qwen/Qwen3-4B`).

### Environment Variable Expansion

Config values support `${VAR:-default}` syntax:

```yaml
model_base_url: "${REMORA_LLM_URL:-http://localhost:8000/v1}"
model_api_key: "${OPENAI_API_KEY:-EMPTY}"
model_default: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"
```

You can also set any config key directly via environment variables with the `REMORA_` prefix:

```bash
export REMORA_MODEL_BASE_URL="https://api.openai.com/v1"
export REMORA_MODEL_API_KEY="sk-..."
export REMORA_MODEL_DEFAULT="gpt-4o"
```

Environment variables override values in `remora.yaml`.

### 2. Create the `.remora` directory

```bash
mkdir -p .remora/events
```

This is where Remora stores its SQLite databases (events, subscriptions) and agent workspace data. Add it to `.gitignore`:

```bash
echo ".remora/" >> .gitignore
```

### 3. (Optional) Create extension configs

If you want to customize how agents behave for specific nodes:

```bash
mkdir -p .remora/models
```

See [Customization](customization.md) for how to write extension configs.

## Starting an LLM Backend

Remora needs an OpenAI-compatible LLM API. You have two options:

### Option A: Local vLLM (Recommended)

Install and start [vLLM](https://docs.vllm.ai/) with a Qwen model:

```bash
pip install vllm

vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_xml \
    --max-num-seqs 32 \
    --max-model-len 32768 \
    --enable-prefix-caching
```

This starts a server at `http://localhost:8000/v1` (the default `model_base_url`).

Key vLLM flags:
- `--enable-auto-tool-choice` -- enables the model to decide when to call tools
- `--tool-call-parser qwen3_xml` -- use the XML-based tool parser (required for Qwen3 tool calling)
- `--enable-prefix-caching` -- caches common prompt prefixes for faster inference

### Option B: External API

Point Remora at any OpenAI-compatible API:

```yaml
# remora.yaml
model_base_url: "https://api.openai.com/v1"
model_api_key: "${OPENAI_API_KEY}"
model_default: "gpt-4o"
```

Or for Anthropic (via an OpenAI-compatible proxy):

```yaml
model_base_url: "https://your-anthropic-proxy.example.com/v1"
model_api_key: "${ANTHROPIC_API_KEY}"
model_default: "claude-sonnet-4-20250514"
```

See [LLM Configuration](llm-configuration.md) for detailed model setup.

## First Run: Reconciliation

Before starting the full swarm, run reconciliation to discover your codebase:

```bash
remora swarm reconcile
```

Output:

```
Reconciliation complete:
  Created: 42
  Orphaned: 0
  Total: 42
```

This parses all files in your `discovery_paths`, identifies code nodes (functions, classes, files, etc.), and creates agents for each one in the EventStore.

### List discovered agents

```bash
remora swarm list
```

Output:

```
Agents (42):
  a1b2c3d4e5f6... | function | src/utils.py | idle
  f7e8d9c0b1a2... | class    | src/models.py | idle
  ...
```

## Running the Swarm

### Headless mode (no editor)

```bash
remora swarm start
```

This starts:
1. Reconciliation (discovers all nodes)
2. The `AgentRunner` (polls for triggered agents and runs them)
3. The EventStore bridge (watches for new events)

The swarm runs in the foreground. Press `Ctrl+C` to stop.

### With web UI

```bash
remora serve --port 8420
```

This starts the Remora service with a web dashboard at `http://localhost:8420`, including:
- Agent graph visualization
- Event timeline debugger
- Agent status and chat interface

## Running with Neovim (LSP)

### Start with LSP mode

```bash
remora swarm start --lsp
```

This starts the LSP server on stdio, which Neovim connects to directly. You need to configure Neovim to use Remora as an LSP client.

### Neovim Configuration

Add to your Neovim config (lua):

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = { "python", "markdown", "toml" },
  callback = function()
    vim.lsp.start({
      name = "remora",
      cmd = { "remora", "swarm", "start", "--lsp" },
      root_dir = vim.fs.root(0, { "remora.yaml", "pyproject.toml", ".git" }),
    })
  end,
})
```

Or if you use a Neovim plugin manager that supports LSP config, configure it with:
- Command: `remora swarm start --lsp`
- Root markers: `remora.yaml`, `pyproject.toml`, `.git`
- File types: `python`, `markdown`, `toml`

### What You Get in Neovim

Once connected, you will see:

- **Code lenses** above each function and class showing agent status
- **Hover information** with agent metadata when you hover over a function/class
- **Code actions** to chat with agents, request rewrites, and manage subscriptions
- **Diagnostics** when agents propose code changes

## Verifying It Works

### Check reconciliation output

After starting, you should see:

```
Reconciling swarm...
Swarm reconciled: 42 new, 0 orphaned, 42 total
```

### Check agent list

```bash
remora swarm list
```

If this shows agents with `idle` status, discovery is working.

### Test an event emission

```bash
remora swarm emit AgentMessageEvent '{"to_agent": "", "from_agent": "cli", "content": "hello"}'
```

This emits a test event into the EventStore.

### Check the EventStore database

The EventStore is at `.remora/events/events.db`. You can query it directly:

```bash
sqlite3 .remora/events/events.db "SELECT count(*) FROM events;"
sqlite3 .remora/events/events.db "SELECT count(*) FROM nodes;"
```

---

**Next steps:**
- [Programming Workflow](programming-workflow.md) -- using Remora for coding in Neovim
- [Notetaking Workflow](notetaking-workflow.md) -- using Remora for markdown notes
- [Customization](customization.md) -- creating custom tools, queries, and extensions
- [LLM Configuration](llm-configuration.md) -- detailed model setup
