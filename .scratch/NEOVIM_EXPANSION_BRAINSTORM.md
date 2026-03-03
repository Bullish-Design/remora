# Neovim Expansion Brainstorm

> Feature ideas for extending the Remora Neovim experience beyond the current LSP panel + agent chat workflow.

---

## Table of Contents

1. [Kanata Layer Integration — Modal Agent Modes](#1-kanata-layer-integration--modal-agent-modes)
   - Bind Kanata keyboard layers to Remora agent modes so physical key behavior changes when you enter an "agent interaction" context. Shift your entire keyboard ergonomics based on whether you're coding, chatting with agents, reviewing proposals, or navigating the swarm graph.

2. [Playwright Web Clipper — In-Editor Research Browser](#2-playwright-web-clipper--in-editor-research-browser)
   - A headless Playwright-based CLI that fetches URLs, scrapes them to clean markdown, tags/indexes them locally, and surfaces them as context to agents. Turn Neovim into a research station where you clip docs, Stack Overflow answers, and API references without leaving the editor.

3. [Agent Timeline Debugger — Event Replay Visualization](#3-agent-timeline-debugger--event-replay-visualization)
   - A horizontal timeline panel in Neovim that shows agent activity as a swimlane diagram. Scrub through time, inspect individual events, see which agents triggered which, and replay event chains to debug reactive loops.

4. [Multi-Agent Conversation Theater — Structured Group Chat](#4-multi-agent-conversation-theater--structured-group-chat)
   - A split-pane conversation view where you can watch (and intervene in) multi-agent discussions in real time. Agents addressing each other appear as threaded messages. You can pin agents to a "room," inject directives, and watch coordination happen live.

5. [Ambient Knowledge Graph Navigator — Telescope for the Swarm](#5-ambient-knowledge-graph-navigator--telescope-for-the-swarm)
   - A Telescope-style fuzzy finder that searches not just files but agents, events, subscriptions, and relationships. Navigate the swarm by concept ("show me all agents that subscribe to ContentChangedEvent") rather than by file path.

6. [Voice-Driven Agent Interaction — Whisper-to-Agent Pipeline](#6-voice-driven-agent-interaction--whisper-to-agent-pipeline)
   - Use local Whisper STT to speak commands and questions to agents. Dictate instructions hands-free, hear agent responses via TTS, and use voice as a parallel input channel alongside keyboard.

7. [Project Ritual System — Automated Workflow Orchestration](#7-project-ritual-system--automated-workflow-orchestration)
   - Define named "rituals" (multi-step automated workflows) that chain agent actions, shell commands, and human checkpoints. Run a ritual like `:RemoraRitual morning-review` and watch agents lint, test, summarize changes, and prepare a status report — all triggered from a single command.

---

## 1. Kanata Layer Integration — Modal Agent Modes

### The Core Idea

Kanata is a software keyboard remapper that supports dynamic layers — you can switch your entire keyboard layout at runtime via IPC commands. The idea is to bridge Kanata's layer system with Remora's modal contexts so that when you enter an agent-focused mode in Neovim, your *physical keyboard* reshapes itself around agent interaction.

This is not just "more keybindings." It is the keyboard *becoming a different instrument* depending on what Remora mode you are in.

### How It Would Work

**Kanata side:** Define layers in your `kanata.kbd` config:

```lisp
;; Normal coding layer (default)
(deflayer coding
  ...normal layout...
)

;; Agent interaction layer — activated when Remora panel is open
(deflayer remora-agent
  ;; Home row becomes agent commands:
  ;;   a = accept proposal
  ;;   r = reject proposal  
  ;;   c = chat with agent at cursor
  ;;   s = send message to another agent
  ;;   t = toggle tools view
  ;;   g = open graph navigator
  ;;   n = next agent (jump to next code lens)
  ;;   p = previous agent
  ...remapped layout...
)

;; Proposal review layer — activated when viewing a diff
(deflayer remora-review
  ;;   y = accept hunk
  ;;   n = reject hunk
  ;;   e = edit proposal
  ;;   j/k = navigate hunks
  ;;   q = dismiss
  ...review-focused layout...
)
```

**Neovim side:** The Lua plugin sends layer-switch commands to Kanata's TCP/Unix socket IPC when Remora state changes:

```lua
-- In panel.lua open():
kanata.switch_layer("remora-agent")

-- In panel.lua close():
kanata.switch_layer("coding")

-- When entering proposal review:
kanata.switch_layer("remora-review")
```

**The IPC bridge:** A small Lua module (`remora/kanata.lua`) that manages the socket connection to Kanata's control port. It sends `layer-switch` commands and can query current layer state.

### Why This Is Interesting

- **Muscle memory separation.** Agent interaction is cognitively different from coding. Giving it its own physical keyboard layer means you don't accidentally trigger agent commands while coding (or vice versa). The layer IS the mode indicator — you feel it in your fingers.
- **Ergonomic density.** In the agent layer, every home-row key maps to a high-frequency agent action. No leader key, no chord. Just `a` for accept, `r` for reject. The layer context makes single-key bindings unambiguous.
- **Visual + haptic feedback loop.** Kanata layers can trigger OS-level actions (LED changes on supported keyboards, status bar updates). Combined with Neovim's highlight changes, you get multi-sensory mode awareness.
- **Scales to more contexts.** Beyond agent/review, you could have layers for graph navigation, web clipper, ritual execution — each with its own ergonomic key mapping.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `kanata.lua` | `src/remora/lsp/nvim/lua/remora/kanata.lua` | IPC bridge to Kanata daemon |
| Layer definitions | User's `kanata.kbd` | Keyboard layer configs (documented, not shipped) |
| Layer triggers | `panel.lua`, `init.lua` | Fire layer switches on Remora state changes |
| Config | `setup(opts)` | `kanata_socket` path, layer names, enable/disable toggle |

### Open Questions

- Should layer switching be opt-in (explicit setup option) or auto-detected (probe for Kanata socket)?
- How to handle Kanata not running (graceful no-op)?
- Should the Remora panel show current Kanata layer as a status indicator?
- Could we use Kanata's `tap-hold` or `one-shot` modifiers to create agent-specific combos (e.g., hold CapsLock to temporarily enter agent layer)?

---

## 2. Playwright Web Clipper — In-Editor Research Browser

### The Core Idea

You are deep in a function, an agent suggests checking the `httpx` retry API, and you need to look it up. Today you switch to a browser, search, read, copy-paste relevant bits back. The web clipper eliminates that context switch: run `:RemoraClip https://www.python-httpx.org/advanced/` from Neovim and the page is fetched via headless Playwright, converted to clean markdown, saved locally with tags, and optionally injected into the current agent's context.

The result is a local library of clipped web content — searchable, taggable, and available as agent context — that lives alongside your project.

### How It Would Work

**CLI tool:** A Python script (`remora-clip`) that wraps Playwright:

```bash
# Basic clip — fetch, convert to markdown, save locally
remora-clip https://docs.python.org/3/library/asyncio.html

# Clip with tags
remora-clip https://stackoverflow.com/q/12345 --tag asyncio --tag error-handling

# Clip with CSS selector (only grab specific content)
remora-clip https://fastapi.tiangolo.com/tutorial/first-steps/ --select "article.md-content"

# Clip and immediately pipe to an agent
remora-clip https://httpx.readthedocs.io/en/latest/api/ --to-agent <agent_id>
```

**Storage:** Clips are saved as markdown files in `.remora/clips/`:

```
.remora/clips/
  index.db                  # SQLite: url, title, tags, timestamp, file path
  2026-03-02_python-httpx-advanced.md
  2026-03-02_stackoverflow-12345.md
```

Each clip file has YAML frontmatter:

```yaml
---
url: https://www.python-httpx.org/advanced/
title: "Advanced Usage - HTTPX"
clipped_at: 2026-03-02T14:30:00
tags: [httpx, retry, http-client]
selector: null
---
# Advanced Usage - HTTPX
...clean markdown content...
```

**Neovim commands:**

| Command | Action |
|---------|--------|
| `:RemoraClip <url>` | Clip a URL to the local library |
| `:RemoraClipSearch <query>` | Fuzzy search clips by title/tag/content (Telescope picker) |
| `:RemoraClipInject` | Pick a clip and inject its content into the current agent's context |
| `:RemoraClipBrowse` | Open the clip index in a floating buffer |

**Agent integration:** Clips become available as agent context through a new tool:

```python
class ReadClipTool(SwarmTool):
    """Read a saved web clip by URL or search query."""
    # Agents can search the clip index and read clipped content
    # as part of their reasoning about your code.
```

### Why This Is Interesting

- **Zero context-switch research.** You never leave Neovim. The clip is markdown, so it renders naturally in a buffer with treesitter highlighting.
- **Agents get web context.** When an agent needs to understand an external API, a design pattern, or a library's behavior, you can feed it a clip instead of hoping it "knows" from training data. This is grounded, current information.
- **Persistent knowledge base.** Clips accumulate over time. Six months from now, when you're working on a similar problem, the clip is still there — tagged, searchable, and ready.
- **Playwright handles JS-rendered content.** Unlike curl or simple HTTP fetchers, Playwright renders the full page including JavaScript-generated content (SPAs, dynamic docs, etc.).
- **Selective scraping.** The `--select` CSS selector option lets you grab just the article body, ignoring nav, ads, and chrome.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `remora-clip` CLI | `src/remora/clip/cli.py` | Playwright fetch + markdown conversion |
| Clip index DB | `.remora/clips/index.db` | SQLite index of all clips |
| `ReadClipTool` | `src/remora/core/tools/clip.py` | Agent tool for reading clips |
| `clip.lua` | `src/remora/lsp/nvim/lua/remora/clip.lua` | Neovim commands + Telescope picker |
| Markdown converter | `src/remora/clip/convert.py` | HTML-to-markdown (using markdownify or similar) |

### Open Questions

- Should clips be project-scoped (`.remora/clips/`) or global (`~/.remora/clips/`)?
- How to handle authentication (logged-in-only pages)?
- Should we support "live clips" that auto-refresh on a schedule (e.g., watching a changelog page)?
- Maximum clip size? Truncation strategy for very long pages?
- Integration with `readability` algorithm (Mozilla's) for article extraction?

---

## 3. Agent Timeline Debugger — Event Replay Visualization

### The Core Idea

The EventLog is the heart of Remora — every agent action, trigger, tool call, and message is recorded as an immutable event. But right now, you can only see this as raw data in SQLite or as the live stream in the panel. The timeline debugger turns the EventLog into a visual, interactive, scrubbable timeline inside Neovim.

Think of it as "Chrome DevTools Network tab" for agent activity — a horizontal swimlane where each agent is a lane, events are markers, and causal chains are drawn as arrows between them.

### How It Would Work

**The timeline buffer:** A custom Neovim buffer type (`remora://timeline`) rendered with virtual text and extmarks. Each row is an agent, each column position is a timestamp, and events are rendered as colored markers:

```
Time:   14:30:00    14:30:01    14:30:02    14:30:03    14:30:04
        ────────────────────────────────────────────────────────
calc_total  [S]─────────[T]──[T]──[C]
                         │
get_user            [M]──┘──────────────[S]──[T]──[C]
                                              │
test_calc                                [M]──┘──────[S]──[E]

[S] = AgentStartEvent   [T] = ToolCallEvent   [C] = AgentCompleteEvent
[M] = AgentMessageEvent  [E] = AgentErrorEvent
```

**Interaction:**

| Key | Action |
|-----|--------|
| `h/l` | Scroll timeline left/right (time axis) |
| `j/k` | Move between agent lanes |
| `<CR>` | Inspect event at cursor (show full payload in floating window) |
| `f` | Follow mode: auto-scroll to latest events (live tail) |
| `z` | Zoom in/out on time axis |
| `c` | Show causal chain: highlight all events connected by correlation_id |
| `/` | Search events by type, agent name, or content |
| `r` | Replay: step through events one by one, showing their effect |

**Data source:** The timeline reads directly from the EventStore's events table via the LSP server. A new LSP command (`remora.getTimeline`) returns events within a time range, grouped by agent_id.

**Replay mode:** The killer feature. Select an event chain (by correlation_id), then press `r` to step through it one event at a time. Each step highlights the causal event, shows which subscription matched, and jumps to the relevant source code in the main editor pane. You can watch a cascade unfold in slow motion.

### Why This Is Interesting

- **Debugging reactive systems is hard.** When agent A triggers B triggers C and something goes wrong, you need to trace the causal chain. The timeline makes causality visible.
- **Performance profiling.** See how long agent turns take, which agents are triggered most frequently, and where bottlenecks form.
- **Subscription debugging.** "Why did this agent wake up?" The timeline shows exactly which event matched which subscription.
- **Teaching tool.** New users can watch the swarm operate to build intuition about reactive patterns.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `timeline.lua` | `src/remora/lsp/nvim/lua/remora/timeline.lua` | Buffer rendering + interaction |
| `remora.getTimeline` | `src/remora/lsp/handlers/commands.py` | LSP command to fetch event data |
| Timeline renderer | `timeline.lua` | Convert event data to swimlane visualization |
| Replay engine | `timeline.lua` | Step-through replay with source navigation |

### Open Questions

- How to handle hundreds of agents? Collapsible groups by file? Auto-hide idle agents?
- Should the timeline persist across sessions (replay yesterday's activity)?
- How to render in a terminal-width-constrained buffer? Adaptive compression?
- Should we show the timeline in a horizontal split (bottom) or a dedicated tab?

---

## 4. Multi-Agent Conversation Theater — Structured Group Chat

### The Core Idea

Right now, the panel shows one agent at a time. But agents talk to *each other* — `AgentMessageEvent` flows between agents, coordination happens behind the scenes. The conversation theater is a multi-pane chat view where you can watch (and participate in) group conversations between agents.

Think of it as a Slack-like interface inside Neovim, but the participants are code agents. You are the human in the room.

### How It Would Work

**Rooms:** A "room" is a group of agents having a conversation. Rooms can form automatically (agents in the same file, agents connected by edges) or manually (you drag agents into a room).

```
:RemoraTheater open           -- Open theater for agents in current file
:RemoraTheater room <name>    -- Create/join a named room
:RemoraTheater add <agent_id> -- Add an agent to the current room
:RemoraTheater watch           -- Open a global feed of all agent messages
```

**The theater buffer:** A split-pane layout:

```
┌──────────────────────────────────┐┌──────────────────┐
│  Conversation                     ││  Participants     │
│                                   ││                  │
│  calc_total (14:30:01):          ││  * calc_total    │
│    I've been asked to add         ││    function      │
│    input validation. Checking     ││    idle          │
│    what get_user expects...       ││                  │
│                                   ││  * get_user      │
│  get_user (14:30:02):            ││    function      │
│    I return Optional[User]. If    ││    running       │
│    None, the caller should        ││                  │
│    handle missing user case.      ││  * test_calc     │
│                                   ││    function      │
│  calc_total (14:30:03):          ││    idle          │
│    Got it. I'll add a guard       ││                  │
│    clause. Proposing rewrite...   ││  ──────────────  │
│                                   ││  [You] Human     │
│  > You: Looks good, but also     ││                  │
│    add a log.warning for the      ││                  │
│    None case.                     ││                  │
│                                   ││                  │
├──────────────────────────────────┤│                  │
│  Message: _                       ││                  │
└──────────────────────────────────┘└──────────────────┘
```

**Human intervention:** You can type messages in the theater input, and they are broadcast to all agents in the room as `HumanChatEvent` with a `room_id` tag. Agents see your message and can respond. This lets you steer multi-agent coordination in real time.

**Auto-rooms:** When a correlation chain involves multiple agents, the theater can automatically create a transient room for that chain. "Show me what agents are collaborating right now" becomes a first-class query.

### Why This Is Interesting

- **Visibility into agent coordination.** Right now, inter-agent messages are invisible unless you dig through the EventLog. The theater makes them a first-class UI.
- **Human-in-the-loop for multi-agent workflows.** You can watch agents negotiate, then step in when they're going off-track. The human becomes a participant, not just an approver.
- **Debugging coordination failures.** When agents deadlock, miscommunicate, or loop, you can see it happening in real time in the theater.
- **The "war room" pattern.** For complex refactors, spin up a theater with all affected agents and orchestrate the change conversationally.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `theater.lua` | `src/remora/lsp/nvim/lua/remora/theater.lua` | Multi-pane chat UI |
| Room manager | `src/remora/core/rooms.py` | Server-side room tracking |
| `remora.getRoom` | `src/remora/lsp/handlers/commands.py` | LSP command for room data |
| Room events | `src/remora/core/events.py` | `RoomCreatedEvent`, `RoomMessageEvent` |
| `$/remora/roomEvent` | LSP notification | Live room event push to client |

### Open Questions

- Should rooms persist across sessions or be ephemeral?
- How to handle rooms with many agents (10+)? Scroll, collapse, or summarize?
- Should the theater support threaded replies (like Slack threads)?
- Can agents create rooms themselves (e.g., a coordinator agent creates a room for a refactor)?

---

## 5. Ambient Knowledge Graph Navigator — Telescope for the Swarm

### The Core Idea

Telescope is the universal fuzzy finder for Neovim — files, buffers, git commits, LSP symbols. The knowledge graph navigator extends this metaphor to the Remora swarm. Instead of searching file paths, you search agents, events, subscriptions, relationships, and event chains.

The swarm is a rich, interconnected graph of entities. Navigating it by opening files and scanning code lenses is like navigating a city by walking — you need a map. This is the map.

### How It Would Work

**Telescope pickers:**

```
:RemoraFind agents            -- Fuzzy search all agents by name, type, status, extension
:RemoraFind events            -- Search events by type, agent, content, time range
:RemoraFind subscriptions     -- Search subscription patterns
:RemoraFind chains            -- Search correlation chains (event cascades)
:RemoraFind related <agent>   -- Show all agents connected to this one (callers, callees, subscribers)
:RemoraFind active            -- Show only currently running/pending agents
:RemoraFind errors            -- Show agents in error state with their last error event
```

**Rich preview:** Selecting an item in the picker shows a rich preview in the Telescope preview pane:

- **Agent preview:** Source code, status, subscriptions, last 5 events, extension info
- **Event preview:** Full payload, correlation chain visualization, triggering subscription
- **Subscription preview:** Pattern, matching agent, recent matches
- **Chain preview:** Mini-timeline of the entire correlation chain

**Navigation:** Pressing `<CR>` on a result navigates to it:
- Agent: Jump to source file at agent's start_line
- Event: Open in timeline debugger at that timestamp
- Subscription: Show agent with subscription highlighted
- Chain: Open timeline debugger filtered to that correlation_id

**Structured queries:** Beyond fuzzy search, support structured queries:

```
:RemoraFind agents status:error type:function
:RemoraFind events type:ToolCallEvent agent:calc_total after:14:30
:RemoraFind subscriptions event_type:ContentChangedEvent
```

### Why This Is Interesting

- **The swarm is too complex for file-based navigation.** With hundreds of agents, dozens of subscriptions, and thousands of events, you need a search-first interface.
- **Concept-level navigation.** "Show me everything that reacts to file saves" is a question about the swarm's behavior, not its file layout. The navigator answers behavioral questions.
- **Telescope integration means zero learning curve.** If you know Telescope (and every Neovim user does), you already know how to use this.
- **Connects all the other features.** The navigator is the entry point to the timeline, theater, and graph view. Find something, then drill into it.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `telescope_remora.lua` | `src/remora/lsp/nvim/lua/telescope/_extensions/remora.lua` | Telescope extension with custom pickers |
| `remora.search` | `src/remora/lsp/handlers/commands.py` | LSP command for searching swarm entities |
| Preview renderers | `telescope_remora.lua` | Rich previews for each entity type |
| Query parser | `telescope_remora.lua` | Parse structured queries (`status:error type:function`) |

### Open Questions

- Should we ship as a standalone Telescope extension or bundle it in the Remora plugin?
- How to keep the search responsive with large EventLogs (millions of events)? Pre-built indexes?
- Should results include "suggestions" (e.g., "3 agents have no subscriptions — they will never trigger")?
- Live updating? Should the picker refresh if new events arrive while it's open?

---

## 6. Voice-Driven Agent Interaction — Whisper-to-Agent Pipeline

### The Core Idea

Your hands are on the keyboard, your eyes are on the code, and you need to tell an agent to do something. Instead of switching to the panel, typing a message, and hitting enter — just speak.

A local Whisper STT model transcribes your speech, the transcript is sent to the agent at cursor, and the agent's response appears in the panel (or is read aloud via TTS). Voice becomes a parallel input channel that doesn't interrupt your keyboard workflow.

### How It Would Work

**Recording trigger:** A keybind (e.g., `<leader>rv`) starts recording from the microphone. Release (or press again) to stop. The audio is transcribed locally via whisper.cpp or faster-whisper.

```lua
-- Hold-to-talk:
vim.keymap.set("n", "<leader>rv", function()
    remora_voice.toggle_recording()
end, { desc = "Voice message to agent" })
```

**Transcription pipeline:**

```
Microphone -> WAV buffer -> Whisper STT (local) -> Text -> Agent chat input
```

The transcription runs as a background process. When it completes, the text is injected into the panel input (or sent directly to the agent if no panel is open).

**Voice commands vs. free-form speech:**

| Input | Interpretation |
|-------|---------------|
| "Accept" | Equivalent to `:RemoraAccept` |
| "Reject, tell it to use a try-except instead" | Reject + feedback message |
| "What does this function do?" | Chat message to agent at cursor |
| "Show me agents in error" | Opens `:RemoraFind errors` |
| "Clip this page" (while URL in clipboard) | Triggers `:RemoraClip` |

A lightweight command parser distinguishes between voice commands (short imperative phrases) and free-form chat (everything else).

**Optional TTS response:** When an agent completes a response, optionally read the first sentence aloud via a local TTS engine (piper, espeak, or macOS `say`). This completes the voice loop — you speak, the agent speaks back.

### Why This Is Interesting

- **Parallel input channel.** Voice doesn't compete with your keyboard. You can speak to an agent while your hands continue typing in a different buffer.
- **Faster for complex instructions.** "Refactor this to use the strategy pattern, extract the validation into a separate method, and make sure the tests still pass" is 3 seconds of speech vs. 30 seconds of typing.
- **Accessibility.** Voice input opens Remora to developers with RSI or other conditions that limit keyboard use.
- **The "pair programmer" feel.** Speaking to an agent that responds feels qualitatively different from typing at it. It's closer to pair programming with a human colleague.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `voice.lua` | `src/remora/lsp/nvim/lua/remora/voice.lua` | Recording control + transcription dispatch |
| `remora-voice` daemon | `src/remora/voice/daemon.py` | Background Whisper process (persistent, avoids model reload) |
| Command parser | `src/remora/voice/commands.py` | Distinguish voice commands from free-form speech |
| TTS output | `src/remora/voice/tts.py` | Optional text-to-speech for agent responses |
| Config | `setup(opts)` | Whisper model path, mic device, TTS enable/disable, language |

### Open Questions

- Whisper model size vs. accuracy vs. latency tradeoff? (tiny.en for speed, base.en for accuracy?)
- How to handle background noise / false activations?
- Should voice input work in insert mode (dictation) or only normal mode (commands)?
- Push-to-talk vs. voice activity detection?
- Privacy: all local, no cloud STT — but should we make this explicit in docs?
- Can we use the Kanata layer system to activate a "voice mode" layer?

---

## 7. Project Ritual System — Automated Workflow Orchestration

### The Core Idea

A "ritual" is a named, reusable sequence of steps that combines agent actions, shell commands, and human checkpoints. Instead of manually running `:RemoraChat` on five different agents and then running pytest, you define a ritual once and run it with a single command.

Rituals are the missing automation layer between "one agent doing one thing" and "the whole swarm orchestrating a complex workflow."

### How It Would Work

**Ritual definition:** YAML files in `.remora/rituals/`:

```yaml
# .remora/rituals/morning-review.yaml
name: morning-review
description: "Review overnight changes, run tests, summarize status"

steps:
  - name: check-git
    type: shell
    command: "git log --oneline --since='yesterday' --no-merges"
    capture: git_changes

  - name: run-tests
    type: shell
    command: "python -m pytest tests/ -q --tb=short"
    capture: test_output
    on_failure: continue   # Don't stop if tests fail

  - name: summarize-changes
    type: agent
    target: file:MONITOR.md
    message: |
      Here are the git changes since yesterday:
      ```
      {{ git_changes }}
      ```
      And the current test status:
      ```
      {{ test_output }}
      ```
      Please update the MONITOR.md with a morning status summary.
    wait: true

  - name: lint-changed
    type: agent_batch
    target: "changed_since:yesterday"  # All agents whose files changed
    message: "Your file was modified since yesterday. Review your own code for issues."
    concurrency: 4

  - name: human-review
    type: checkpoint
    prompt: "Morning review complete. Changes summarized, tests run. Continue?"
    show:
      - "{{ git_changes }}"
      - "{{ test_output }}"
```

**Neovim commands:**

```
:RemoraRitual morning-review       -- Run a ritual by name
:RemoraRitual list                 -- List available rituals
:RemoraRitual status               -- Show running ritual progress
:RemoraRitual cancel               -- Cancel current ritual
```

**Ritual progress panel:** When a ritual runs, a progress panel shows each step:

```
Ritual: morning-review
──────────────────────────────────────
[done] check-git              0.3s
[done] run-tests              12.1s  (2 failures)
[run]  summarize-changes      ...
[ ]    lint-changed
[ ]    human-review
```

**Step types:**

| Type | Description |
|------|-------------|
| `shell` | Run a shell command, capture output |
| `agent` | Send a message to a specific agent, optionally wait for completion |
| `agent_batch` | Send a message to multiple agents matching a pattern |
| `checkpoint` | Pause and ask the human for confirmation |
| `conditional` | Branch based on previous step output |
| `parallel` | Run multiple sub-steps concurrently |
| `clip` | Fetch a URL via the web clipper |

**Template variables:** Steps can reference output from previous steps via `{{ step_name }}` Jinja2 syntax. This lets you chain data through the ritual.

**Triggers:** Rituals can be triggered manually, on a schedule (cron-like), or reactively (on specific events):

```yaml
# Auto-run on git push
triggers:
  - type: event
    event_type: "FileSavedEvent"
    path_glob: ".git/refs/heads/*"
```

### Why This Is Interesting

- **Codified workflows.** "How do I deploy?" or "What's my morning routine?" becomes a YAML file anyone on the team can read and run.
- **Human + agent + shell in one flow.** Rituals bridge the gap between shell scripts (no agent involvement), manual agent interaction (tedious), and fully autonomous swarms (scary). You get checkpoints where you want them.
- **Composable.** Rituals can call other rituals as steps. Build a library of small rituals and compose them.
- **Discoverable.** `:RemoraRitual list` shows what automations are available. New team members can browse rituals to learn the project's workflows.
- **The backbone for CI-like local automation.** Instead of pushing to CI to see if tests pass, run the ritual locally. The agents can fix issues before you push.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Ritual runner | `src/remora/core/rituals.py` | YAML parser + step executor |
| `ritual.lua` | `src/remora/lsp/nvim/lua/remora/ritual.lua` | Neovim commands + progress panel |
| `remora.runRitual` | `src/remora/lsp/handlers/commands.py` | LSP command to start/query rituals |
| Ritual definitions | `.remora/rituals/*.yaml` | User-defined workflow files |
| Template engine | `src/remora/core/rituals.py` | Jinja2 variable substitution between steps |
| `$/remora/ritualProgress` | LSP notification | Live progress push to Neovim |

### Open Questions

- How to handle ritual failures? Retry logic? Rollback?
- Should rituals have access to the web clipper and voice systems?
- Maximum ritual duration before auto-cancel?
- Should rituals emit their own events to the EventLog (for auditability)?
- Can agents propose new rituals? ("I notice you do X, Y, Z every morning — want me to create a ritual?")
- How to share rituals across projects? A global ritual library?

---

## Cross-Cutting Themes

Several themes emerge across these ideas:

### Integration Density

Each feature is more powerful when combined with others. The web clipper provides context for agents. The timeline debugger visualizes what the ritual runner orchestrates. The knowledge graph navigator lets you find things the theater shows. The Kanata layers give you ergonomic access to all of them. These are not independent features — they form an ecosystem.

### The "Inner IDE" Pattern

Collectively, these features turn Neovim from "an editor with agent support" into a complete agent-native development environment:

| Traditional IDE Feature | Remora Equivalent |
|------------------------|-------------------|
| File explorer | Knowledge graph navigator |
| Debugger | Timeline debugger + event replay |
| Team chat | Conversation theater |
| Browser/docs | Web clipper |
| Build system | Ritual runner |
| Keyboard shortcuts | Kanata layers |
| Voice assistant | Whisper pipeline |

### Local-First

Every feature runs locally. No cloud STT, no SaaS browser, no external chat server. The EventLog, clip index, ritual definitions, and voice transcription all live on disk. This is privacy-respecting, low-latency, and works offline.

### Progressive Disclosure

None of these features are required. A user can use Remora with just the panel and code lenses. Each feature is opt-in, each has a single entry point command, and each degrades gracefully if dependencies are missing (no Kanata? no layer switching. No Playwright? no clipper. No microphone? no voice).

---

## Implementation Priority (Subjective)

| Priority | Feature | Why |
|----------|---------|-----|
| 1 | Ambient Knowledge Graph Navigator | Highest ROI — makes the existing swarm navigable |
| 2 | Agent Timeline Debugger | Essential for debugging reactive systems |
| 3 | Playwright Web Clipper | Immediately useful, low coupling to other features |
| 4 | Project Ritual System | Unlocks automation, but needs other features to shine |
| 5 | Multi-Agent Conversation Theater | High value but complex UI work |
| 6 | Kanata Layer Integration | Small surface area, big ergonomic payoff for Kanata users |
| 7 | Voice-Driven Agent Interaction | Cool but niche; depends on hardware/setup |
