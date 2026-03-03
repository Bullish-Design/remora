# Notetaking Workflow

> Using Remora as an AI-assisted knowledge management system for Markdown notes.

## Table of Contents

1. [Overview](#overview) -- How Remora treats Markdown files
2. [What Gets Discovered](#what-gets-discovered) -- Sections, todos, frontmatter, and file-level agents
3. [Sections as Agents](#sections-as-agents) -- Each heading becomes an autonomous agent
4. [Todos as Agents](#todos-as-agents) -- Checkbox items that an agent can reason about
5. [Frontmatter and Metadata](#frontmatter-and-metadata) -- YAML frontmatter for note-level context
6. [Working with Note Agents in Neovim](#working-with-note-agents-in-neovim) -- Chat, rewrite, and the panel for Markdown
7. [The Reactive Cascade for Notes](#the-reactive-cascade-for-notes) -- How editing one section can trigger reactions in others
8. [Example Workflow](#example-workflow) -- End-to-end walkthrough of a note management session

---

## Overview

Remora does not limit itself to source code. Every Markdown file in your project is also parsed by tree-sitter, and the structural elements -- sections, todos, frontmatter blocks -- become agents in the same swarm as your code.

This means your project notes, design documents, meeting minutes, and task lists are all part of the reactive graph. A section in a design document can have its own agent that understands its content, responds to questions, and reacts when related code or other sections change.

The notetaking workflow uses the same keybindings, the same agent panel, and the same reactive cascade as the programming workflow. The only difference is what gets discovered and what the agents know about.

---

## What Gets Discovered

When Remora parses a Markdown file, it uses tree-sitter queries to extract these node types:

| Node Type | What It Matches | Example |
|-----------|----------------|---------|
| `section` | A heading and all its content (paragraphs, subsections) | `## Architecture` and everything under it |
| `heading` | Just the heading line itself | `### API Design` |
| `todo` | A checkbox list item | `- [ ] Implement caching layer` |
| `frontmatter` | YAML frontmatter block | The `---` delimited block at the top of a file |
| `code_block` | A fenced code block | ` ```python ... ``` ` |
| `file` | The entire document | The whole `.md` file |

Each of these becomes an `AgentNode` in the event store. The most useful ones for the notetaking workflow are **sections**, **todos**, and **file**-level agents.

---

## Sections as Agents

Every heading in a Markdown file creates a `section` agent. The agent's scope includes the heading and all content under it until the next heading at the same or higher level.

For example, in this document:

```markdown
# Project Plan

## Goals
We want to build a fast, reliable API.

## Timeline
- Q1: Design phase
- Q2: Implementation

### Milestones
- Alpha release by March
- Beta release by May

## Risks
Network latency may be a concern.
```

Remora discovers these section agents:

- **Project Plan** -- the entire document (level 1)
- **Goals** -- "We want to build a fast, reliable API."
- **Timeline** -- the list and the Milestones subsection
- **Milestones** -- the two bullet points
- **Risks** -- "Network latency may be a concern."

Each agent knows its own text content. You can chat with the "Goals" agent to ask it to elaborate, or request a rewrite of the "Timeline" section to add more detail.

---

## Todos as Agents

Checkbox list items (task list items) are discovered as `todo` agents:

```markdown
- [ ] Implement caching layer
- [x] Write API specification
- [ ] Add integration tests for payment flow
```

Each of these three lines becomes its own agent. The agent's name is the text of the todo item. This is useful because:

- You can chat with a todo to ask what implementing it would involve.
- An agent for a design section that mentions caching could react when the "Implement caching layer" todo is checked off.
- You can request a rewrite of a todo to refine its description.

### Checked vs. Unchecked

Both checked (`[x]`) and unchecked (`[ ]`) items are discovered. The agent's source code contains the full list item text including the checkbox marker, so the LLM knows whether the task is complete.

---

## Frontmatter and Metadata

YAML frontmatter blocks at the top of Markdown files are discovered as `frontmatter` agents:

```markdown
---
title: API Design Document
tags: [api, architecture, v2]
status: draft
owner: alice
---

# API Design Document
...
```

The frontmatter agent captures the entire YAML block. This is useful for Obsidian-style workflows where metadata drives organization. The agent knows the title, tags, status, and any other fields you define.

While frontmatter agents can respond to chat and rewrite requests like any other agent, their primary value is providing context to the file-level agent and to extensions that match based on metadata.

---

## Working with Note Agents in Neovim

The same keybindings from the [programming workflow](./programming-workflow.md) work in Markdown files:

| Keybinding | What It Does in Markdown |
|------------|-------------------------|
| `<leader>rc` | Chat with the section/todo/file agent at your cursor |
| `<leader>rr` | Request a rewrite of the section at your cursor |
| `<leader>ry` | Accept a proposed rewrite |
| `<leader>rn` | Reject a proposal with feedback |
| `<leader>ra` | Toggle the agent panel |

### Cursor Resolution

When you press `<leader>rc` inside a Markdown file, Remora finds the most specific agent at your cursor position:

- Cursor on a todo item? You are talking to the todo agent.
- Cursor in a paragraph under a heading? You are talking to the section agent for that heading.
- Cursor in frontmatter? You are talking to the frontmatter agent.
- Cursor at the top of the file outside any section? You are talking to the file-level agent.

### The Agent Panel for Notes

The agent panel works identically to the code workflow. It shows the section name (or todo text) as the agent name, the node type (`section`, `todo`, `frontmatter`, or `file`), available tools, and the chat history.

---

## The Reactive Cascade for Notes

The reactive cascade works for Markdown just as it does for code. When you edit a section, Remora detects the change during reconciliation and emits events that other agents can react to.

### Example Scenarios

**Design doc updates code agents.** If a section in your design document describes the interface for a module, and you update that section, agents for the corresponding code functions could react by proposing updates to match the new design.

**Cross-section reactions.** A "Summary" section agent could react when you edit the "Details" section, proposing to update the summary to reflect the new content.

**Todo completion triggers updates.** When you check off a todo item (`[ ]` to `[x]`), agents watching that change can react. A project status section agent might propose updating the progress count.

### What Triggers It

Same as for code:

- Saving the Markdown file triggers reconciliation via `textDocument/didSave`.
- Running `remora swarm reconcile` manually forces a full re-scan.
- The swarm loop reconciles on its configured interval.

---

## Example Workflow

Here is a walkthrough of using Remora with a project notes file.

### 1. Open a Markdown File

Open a file like `docs/design.md` in Neovim. Remora's LSP starts for Markdown files automatically (it is configured for `python`, `markdown`, and `toml` filetypes).

### 2. Explore the Structure

Press `<leader>ra` to open the agent panel. Navigate to different headings -- the panel updates to show each section's agent.

### 3. Ask About a Section

Place your cursor in the "Architecture" section and press `<leader>rc`. Type:

```
What are the main components described in this section?
```

The agent responds based on the section's content.

### 4. Refine a Section

Press `<leader>rr` on a sparse section. When prompted:

```
Expand this section with more detail about error handling strategies
```

The agent proposes a rewrite with additional content. Review it in the agent panel (the diff shows added lines in green) and press `<leader>ry` to accept.

### 5. Work with Todos

Navigate to a todo item:

```markdown
- [ ] Define API rate limiting strategy
```

Press `<leader>rc` and ask:

```
What approaches should we consider for rate limiting?
```

The agent provides analysis. You can then press `<leader>rr` to have it rewrite the todo into a more detailed description, or create new sub-items.

### 6. Watch Cross-Reactions

Edit the "Architecture" section to add a new component. Save the file. If a "Summary" section agent is subscribed to changes in the same file, it may propose an update to reflect the new component in the summary.

Review and accept or reject as needed. The notetaking workflow follows the same human-in-the-loop pattern as the coding workflow.
