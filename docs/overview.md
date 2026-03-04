# Remora

> A reactive agent swarm where every piece of your code becomes an autonomous AI agent.

## Table of Contents

1. [What Is Remora?](#what-is-remora) -- The core idea in plain terms
2. [How It Works (30-Second Version)](#how-it-works-30-second-version) -- The discovery-event-reaction loop
3. [What Can It Do?](#what-can-it-do) -- Concrete capabilities
4. [Two Worlds: Code and Notes](#two-worlds-code-and-notes) -- Programming vs. notetaking workflows
5. [Key Concepts](#key-concepts) -- Terms you will encounter throughout the docs
6. [System Requirements](#system-requirements) -- What you need to run Remora
7. [Where to Go Next](#where-to-go-next) -- Links to detailed guides

---

## What Is Remora?

Remora is a system that turns your source code into a swarm of AI agents. Every function, class, file, markdown section, or TODO item in your project becomes an autonomous agent that can:

- Understand its own source code and surrounding context
- React to changes in itself or related code
- Communicate with other agents through events
- Use tools to read files, write code, query the project, and more

Think of it this way: instead of asking a single AI chatbot about your entire codebase, Remora gives every meaningful piece of code its own dedicated AI that watches over it, understands its purpose, and can act when something relevant happens.

Remora runs as a background process alongside your editor. It integrates with Neovim as an LSP server, providing code lenses, hover information, chat capabilities, and rewrite proposals directly in your editing workflow.

## How It Works (30-Second Version)

Remora follows a three-step loop:

**1. Discovery** -- Remora uses tree-sitter to parse your source files and identify structural nodes: functions, classes, markdown sections, TODO items, TOML tables, and whole files. Each node gets a unique identity based on its file path and position.

**2. Events** -- When you edit code, Remora detects the change and emits events. Events flow through an EventStore (backed by SQLite) which is the single source of truth for all state. Agents can subscribe to specific event patterns to be notified when something relevant happens.

**3. Reaction** -- When an agent receives a triggering event, it runs an LLM turn. The agent's prompt includes its own source code, surrounding context, chat history, and the trigger event. The LLM can respond with text, call tools (read/write files, query other agents, subscribe to events, broadcast messages), or propose rewrites.

This loop is fully reactive. You write code. Remora discovers the structure. Changes trigger events. Agents react. Their reactions may trigger further events, creating cascades that ripple through related agents.

## What Can It Do?

**In your editor (Neovim + LSP):**
- Code lenses showing agent status above every function and class
- Hover information with agent metadata, tools, and subscriptions
- Chat with any agent directly (ask a function to explain itself, suggest improvements, or write its own tests)
- Accept or reject rewrite proposals that agents generate
- A web-based graph viewer showing the agent swarm and event timeline

**As a headless swarm:**
- Run without an editor via `remora swarm start`
- Reconcile and discover all nodes via `remora swarm reconcile`
- List all agents via `remora swarm list`
- Emit events programmatically via `remora swarm emit`

**For customization:**
- Define custom tools as Grail `.pym` scripts
- Add tree-sitter query files for new node types
- Write extension configs that give specific agents specialized prompts and tools
- Configure which LLM models agents use, per-project or per-agent

## Two Worlds: Code and Notes

Remora works with two kinds of content:

### Programming

For source code (Python, and extensible to other languages), Remora discovers:
- **Functions** -- each function becomes an agent
- **Classes** -- each class becomes an agent
- **Files** -- each file gets a file-level agent

These agents understand code structure, can propose refactors, write tests, explain logic, and react to changes in related code.

### Notetaking

For markdown files, Remora discovers:
- **Sections** -- each heading and its content becomes an agent
- **Todos** -- checkbox items (`- [ ] task`) become individual agents
- **Notes** -- files with frontmatter metadata (e.g., `type: todo`) become specialized agents
- **Files** -- each markdown file gets a file-level agent

This turns a collection of markdown files into a living knowledge base where TODO items can track their own completion, sections can summarize themselves, and notes can link to related content -- all powered by the same reactive agent architecture.

## Key Concepts

| Term | Meaning |
|------|---------|
| **AgentNode** | The data model for every agent. A Pydantic BaseModel with identity, source code, status, tools, subscriptions, and extension data. |
| **EventStore** | SQLite-backed append-only log of all events. The single source of truth for state. |
| **EventBus** | In-memory pub/sub for real-time event delivery to running agents. |
| **Discovery** | Tree-sitter parsing that turns source files into CSTNodes (concrete syntax tree nodes). |
| **Reconciliation** | The process of comparing discovered nodes against known agents and emitting create/remove events. |
| **Bundle** | A directory containing agent configuration: system prompt, tools, model settings. Mapped to node types via `bundle_mapping` in `remora.yaml`. |
| **Extension** | A Python class in `.remora/models/` that matches specific nodes and overrides their AgentNode fields (prompts, tools, tags). |
| **Subscription** | A pattern an agent registers to receive specific events (e.g., "notify me when any function in `utils.py` changes"). |
| **Grail Tool** | A `.pym` script that defines a tool agents can call. Uses the Grail scripting system. |
| **Kernel** | The `AgentKernel` from `structured-agents` that runs LLM turns with tool calling. |

## System Requirements

- **Python 3.13+**
- **Neovim 0.9+** (for LSP integration; optional for headless mode)
- **An OpenAI-compatible LLM API** -- either:
  - **vLLM** running locally (recommended: `Qwen/Qwen3-4B-Instruct-2507-FP8`)
  - Any external API that implements `/v1/chat/completions` (OpenAI, Anthropic via proxy, etc.)
- **SQLite** (bundled with Python)
- **tree-sitter** (installed as a Python dependency)

For the full development environment with Nix, see [Getting Started](guides/getting-started.md).

## Where to Go Next

| Guide | Description |
|-------|-------------|
| [Architecture](architecture.md) | How the system works internally -- events, discovery, projections, the reactive loop |
| [Getting Started](guides/getting-started.md) | Installation, configuration, and running Remora for the first time |
| [Programming Workflow](guides/programming-workflow.md) | Using Remora as an AI-assisted coding environment in Neovim |
| [Notetaking Workflow](guides/notetaking-workflow.md) | Using Remora for markdown notes, TODOs, and knowledge management |
| [Customization](guides/customization.md) | Writing custom tools, tree-sitter queries, and agent extensions |
| [LLM Configuration](guides/llm-configuration.md) | Setting up vLLM, external APIs, and per-agent model configuration |
