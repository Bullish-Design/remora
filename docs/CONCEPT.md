# Remora Concept

## Purpose

Remora is a local orchestration layer for running structured, tool-calling code agents on Python projects. It discovers code nodes with tree-sitter, runs specialized agent bundles (lint, test, docstring, sample_data) against each node, and stores changes in isolated Cairn workspaces that you can review or auto-merge.

## Core Ideas

### 1. Node-Level Agents

Remora breaks code into CST nodes (files, classes, functions, methods). Each node becomes a unit of work that can be processed independently and in parallel.

### 2. Structured-Agent Bundles

Each operation is defined as a **bundle** (`agents/<op>/bundle.yaml`) that includes:

- A model adapter ID for the OpenAI-compatible server (typically vLLM).
- Prompt templates for the initial system/user messages.
- A catalog of Grail tools (`.pym` scripts) and optional context providers.
- A termination tool (e.g., `submit_result`).

The bundle format is loaded by `structured-agents` and executed by Remora’s `KernelRunner`.

### 3. Multi-Turn Tool Calling

Agents iterate in a loop: call a tool, inspect the result, update context, and call another tool until `submit_result` is invoked or the turn limit is reached. This lets the model make incremental decisions rather than a single-pass output.

### 4. Two-Track Context

Remora maintains a **Decision Packet** (Short Track) that summarizes recent tool actions and errors. The Decision Packet is injected into prompts, while the full event stream remains available for debugging.

### 5. Hub Context (Optional)

The Hub daemon (`remora-hub`) maintains an indexed view of the codebase (`.remora/hub.db`). Remora can pull hub context per node to enrich prompts with signatures, docstrings, or call relationships.

## What Remora Does

- Finds Python code nodes with tree-sitter queries.
- Executes tool-calling agent bundles on each node.
- Captures results and workspace changes per operation.
- Emits structured events for dashboards and logs.
- Provides manual or automatic acceptance of changes.
