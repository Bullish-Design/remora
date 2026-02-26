# Ground-Up Refactor Analysis (2026-02-27)

## Grail 3.0.0 reality check
- `grail.load` accepts a `files` dict and the runtime `files` override documented in SPEC §2.2 & §9.3, so Idea 8's DataProvider can map directly to populating the virtual filesystem instead of inventing a new API.
- `GrailScript.run` already accepts `externals` alongside the inputs, which gives us a natural place to plug Idea 7's event-driven question/response handlers and still rely on Grail to enforce the required `Limits` presets.
- Grail v3 explicitly leaves snapshot/resume to future Monty support (SPEC §10), so checkpointing remains entirely in the Cairn layer as originally envisioned.

## structured-agents 0.3.4 reality check
- `Agent.from_bundle()` already exists, but its manifest loader only cares about `name`, `system_prompt`, `agents_dir`, `limits`, `model`, `grammar`, and `max_turns`, so any Remora-specific metadata (node types, priority hints, context requirements) still has to live outside the bundle manifest or be stitched in via a custom manifest extension before the bundle is passed to structured-agents.
- The bundle wiring hardcodes `STRUCTURED_AGENTS_BASE_URL` and `STRUCTURED_AGENTS_API_KEY` when building the HTTP client, which means server/model configuration comes from the environment unless we drop down to our own `AgentKernel` construction to inject Remora's config knobs.
- `discover_tools()` loads each `.pym` once with `grail.load(..., grail_dir=None)` and runs them with no custom `files` or `externals`, so Idea 8's DataProvider + Idea 7's event-based `ask_user` flow require us to wrap or replace the Grail tool implementation so we can pass the virtual filesystem and external helpers per call.
- The library already exposes typed kernel events (`KernelStartEvent`, `ModelResponseEvent`, `ToolCallEvent`, etc.), but Remora still needs to emit graph-level events and human-in-the-loop events, so our EventBus must implement the `Observer` interface and re-emit/extend those structured events as part of the unified taxonomy.

## Immediate plan adjustments
- Treat the bundle manifest as the structured-agents contract and keep Remora-specific metadata (node categories, execution priority, two-track hints) alongside it in our own data layer rather than relying on extra manifest fields that the loader ignores.
- Replace or wrap `discover_tools()` with a Remora-aware loader that instantiates Grail scripts with the right virtual filesystem (`files`) and an IPC-aware `externals` dict before handing each `GrailTool` (or our subclass) to the agent kernel.
- Manage the structured-agents client configuration explicitly (e.g., populate `STRUCTURED_AGENTS_BASE_URL/API_KEY` from `remora.yaml` or bypass the `Agent.from_bundle` helper) so the kernel uses the Remora-configured model server instead of the default environment values.
- Implement the unified `EventBus` as an `Observer` so we get every kernel event, then re-emit them alongside our graph events and human I/O events; this also becomes the natural place to satisfy Idea 7's `wait_for()` primitive.
