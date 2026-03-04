# Companion Demo — Assumptions

> Load this file before making design decisions.

---

## Audience

1. **Primary:** Developers evaluating Remora for their own projects
2. **Secondary:** Conference/meetup demo attendees
3. **Tertiary:** Potential contributors to the project

---

## Demo Context

- **Setting:** Live demo, likely screen-shared
- **Duration:** 5-7 minutes of active demonstration
- **Setup time:** Should work out-of-the-box with minimal config
- **Network:** Assume local-only (no API calls required)

---

## User Scenarios

### Scenario 1: Developer Exploring Unfamiliar Codebase
- Opens a file they've never seen
- Wants to quickly understand: what is this, what relates to it, what tests it
- Value: Reduced time to comprehension

### Scenario 2: Researcher Writing a Report
- Writing markdown about a technical topic
- Wants related notes, definitions, sources surfaced automatically
- Value: Reduced context-switching, better connections

### Scenario 3: Developer Returning to Work
- Comes back to a project after days/weeks
- Wants to remember where they left off, what was in progress
- Value: Session continuity, reduced ramp-up time

---

## Technical Constraints

1. **Local-first:** No required API calls, everything runs on user's machine
2. **Performance:** Sidebar update < 500ms for light operations
3. **Resource usage:** Should not noticeably slow down the editor
4. **Privacy:** No data leaves the machine
5. **Cross-platform:** Should work on Linux, macOS (Windows nice-to-have)

---

## Existing Infrastructure

- **Remora:** Agent orchestration, event system, Cairn workspace
- **Neovim:** Editor with LSP support
- **Obsidian:** Markdown knowledge base with wikilinks
- **vLLM/Ollama:** Local LLM inference (optional for some agents)

---

## Non-Goals

1. **Not a chatbot:** No conversational interface, just ambient context
2. **Not an IDE:** No code actions, refactoring, completion
3. **Not real-time collaboration:** Single-user focus
4. **Not cloud-sync:** Local workspace only

---

## Quality Bar

For demo purposes:
- Works reliably with prepared sample content
- Gracefully handles edge cases (empty files, binary files)
- Visually impressive timeline visualization
- Clear audit trail from input to output

---

## Success Metrics

1. **"Wow" reaction:** Audience impressed by emergence/traceability
2. **Understandability:** Architecture clear from watching the demo
3. **Credibility:** System does what it claims, no smoke and mirrors
4. **Inspiration:** Viewers see how they could build similar systems
