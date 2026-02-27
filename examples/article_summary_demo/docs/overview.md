# Remora Field Guide

## Why Remora

Remora is built to coordinate multiple specialized agents against a shared codebase.
The goal is to keep runs reproducible and observable while allowing agents to focus
on narrowly scoped tasks. The system emphasizes clear event streams, isolated
workspaces, and explicit bundles that define each agent's role.

## The Agent Pipeline

Each run starts with discovery, where tree-sitter extracts nodes like files,
functions, or Markdown sections. The executor then builds a dependency-aware graph
and runs agents in batches. Every step emits events that the UI can replay and
summarize for human operators.

## Human-in-the-Loop Moments

Some workflows need confirmation before applying changes or deciding on a strategy.
Remora exposes a human input channel that agents can use to request guidance.
This keeps automated analysis aligned with the human reviewer’s intent.
