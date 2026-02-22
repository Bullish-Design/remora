# Structured Agents Functionality Refactor

This guide details the necessary changes to the `structured-agents` library to support advanced model flexibility and dynamic LoRA adapter routing required by Remora.

## Context and Rationale

`structured-agents` is designed to be a modular, predictable core for agent loops. However, as Remora evolves, it requires tighter, more dynamic control over the inference process than the current library supports out-of-the-box.

Specifically, Remora needs:
1. **Dynamic Model Plugins:** The ability for Remora's configuration to override the default plugin specified in an agent's bundle manifest (e.g., swapping a `function_gemma` plugin for a generic `openai` plugin).
2. **Per-Call LoRA Adapter Routing:** The ability to dynamically change the target model (and thereby the vLLM LoRA adapter) on a *turn-by-turn* basis mid-session, rather than locking the model at the time the client is instantiated. This allows tools or prompts to dictate which adapter handles the next inference step.

The following changes implement these capabilities within `structured-agents` while maintaining its protocol-driven extensibility.

---

## 1. Dynamic Plugin Resolution

**Objective:** Allow a consumer (like Remora) to optionally override the plugin specified in a bundle's manifest.

Currently, `AgentBundle.get_plugin()` strictly reads from `self.manifest.model.plugin`. We need to provide an optional argument to override this.

### Step 1.1: Modify `AgentBundle`
In `src/structured_agents/bundles/loader.py`, update the `get_plugin` method:

```python
    def get_plugin(self, override_name: str | None = None) -> ModelPlugin:
        """Get the appropriate model plugin for this bundle.
        
        Args:
            override_name: Optional plugin name to use instead of the manifest's default.
        """
        plugin_name = override_name or self.manifest.model.plugin
        return get_plugin(plugin_name)
```

**Why this matters:** This tiny change allows Remora's `KernelRunner` to read its own configuration (`RemoraConfig.operations[xyz].model_plugin`) and pass it to the bundle, cleanly decoupling the executed plugin from the static bundle definition.

---

## 2. Dynamic LoRA Adapter Routing (Per-Call Model Overrides)

**Objective:** Allow the `AgentKernel` to change the `model` parameter sent to the OpenAI-compatible client on a turn-by-turn basis. In vLLM, the `model` parameter is used to dynamically route requests to specific, pre-loaded LoRA adapters.

Currently, `OpenAICompatibleClient` locks the model name during initialization (`self._config.model`). We need to open this up to accept per-call overrides.

### Step 2.1: Update Client Protocols

In `src/structured_agents/client/protocol.py`, add the `model` parameter to the `LLMClient` protocol:

```python
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict[str, Any] | None = None,
        model: str | None = None,  # Add this parameter
    ) -> CompletionResponse:
```

Next, implement this in `src/structured_agents/client/openai_compat.py`:

```python
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict[str, Any] | None = None,
        model: str | None = None,  # Add this parameter
    ) -> CompletionResponse:
        """Make a chat completion request."""
        try:
            kwargs: dict[str, Any] = {
                "model": model or self._config.model,  # Use override if provided
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
```

**Why this matters:** This satisfies the vLLM requirement for targeting specific LoRA adapters via the `model` payload parameter without requiring the instantiation of a brand new client.

### Step 2.2: Pass Overrides Through the Kernel

The `AgentKernel` orchestrates the loop and manages the context. It needs to extract the target model from that context and pass it to the client.

In `src/structured_agents/kernel.py`, update `step()` to accept the parameter:

```python
    # Update step() arguments
    async def step(
        self,
        messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        context: dict[str, Any] | None = None,
        turn: int = 1,
        model: str | None = None,  # Add this parameter
    ) -> StepResult:
        # ... later in step() ...
        response = await self._client.chat_completion(
            messages=formatted_messages,
            tools=formatted_tools,
            tool_choice=self.config.tool_choice if resolved_tools else "none",
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            extra_body=extra_body,
            model=model,  # Pass it down
        )
```

Finally, update the loop in `AgentKernel.run()` to extract this override dynamically from the turn's context provided by Remora. Still in `src/structured_agents/kernel.py`:

```python
                context = await self._build_context(context_provider)
                
                # Extract optional model override from context
                step_model_override = context.get("model_override")

                messages = self.history_strategy.trim(
                    messages, self.max_history_messages
                )

                step_result = await self.step(
                    messages=messages,
                    tools=resolved_tools,
                    context=context,
                    turn=turn_count,
                    model=step_model_override,  # Pass extracted override
                )
```

**Why this matters:** `context_provider` is an asynchronous callback provided by Remora (specifically `KernelRunner._provide_context`). By checking `context.get("model_override")`, `structured-agents` allows Remora to dynamically dictate the destination adapter just-in-time before the inference call is made.
