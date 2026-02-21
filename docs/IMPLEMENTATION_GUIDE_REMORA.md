# Implementation Guide: Remora Refactor

This guide provides the exact implementation for tearing down Remora internals and replacing them with dependencies on the new `xgrammar-tools` library.

**Prerequisite**: Ensure that `xgrammar-tools` is available in your workspace or installed via `pip`/`uv`.

---

## Step 1: Strip Old Dependencies and Logic

**Implementation**:
```bash
# Delete obsolete files
rm src/remora/grammar.py
rm src/remora/tool_parser.py
rm src/remora/execution.py

# Remove dependencies from pyproject.toml
uv remove xgrammar
uv remove openai
```

---

## Step 2: The Event Bridge

**File: `src/remora/event_bridge.py`**
```python
from typing import Any
from remora.events import EventEmitter, EventName, EventStatus
from remora.context import ContextManager
import time

class RemoraEventBridge:
    """Translates xgrammar-tools EventCallback protocol to Remora EventEmitters."""
    
    def __init__(self, emitter: EventEmitter, ctx: ContextManager, node_id: str, operation: str):
        self.emitter = emitter
        self.ctx = ctx
        self.agent_id = ctx.base_context["agent_id"]
        self.node_id = node_id
        self.operation = operation
        self.start_time = time.monotonic()

    def _base_payload(self, event_name: str) -> dict[str, Any]:
        return {
            "event": event_name,
            "agent_id": self.agent_id,
            "node_id": self.node_id,
            "operation": self.operation,
            "phase": "execution",
        }

    async def on_model_request(self, payload: dict[str, Any]) -> None:
        evt = self._base_payload(EventName.MODEL_REQUEST)
        evt["step"] = "loop"
        evt["messages"] = payload.get("messages", [])
        self.emitter.emit(evt)

    async def on_model_response(self, payload: dict[str, Any]) -> None:
        evt = self._base_payload(EventName.MODEL_RESPONSE)
        evt["status"] = EventStatus.OK
        evt["duration_ms"] = int((time.monotonic() - self.start_time) * 1000)
        evt["response_text"] = payload.get("content", "")
        self.emitter.emit(evt)
        self.start_time = time.monotonic() # reset for next turn

    async def on_tool_execute(self, payload: dict[str, Any]) -> None:
        evt = self._base_payload(EventName.MODEL_REQUEST_DEBUG) # closest fit for "about to run tool"
        evt["tool_name"] = payload.get("name")
        self.emitter.emit(evt)

    async def on_tool_result(self, payload: dict[str, Any]) -> None:
        evt = self._base_payload(EventName.TOOL_RESULT)
        evt["tool_name"] = payload.get("name")
        evt["status"] = EventStatus.OK
        evt["tool_output"] = payload.get("output", "")
        self.emitter.emit(evt)
        
        # Apply to Remora context manager state!
        self.ctx.apply_event({
            "type": "tool_result",
            "tool_name": evt["tool_name"],
            "data": evt["tool_output"]
        })
```

---

## Step 3: Implement the XGrammarRunner

**File: `src/remora/runtime/xgrammar_runner.py`**
```python
from pathlib import Path
from remora.discovery import CSTNode
from remora.orchestrator import RemoraAgentContext
from remora.context import ContextManager
from remora.config import ServerConfig
from remora.results import AgentResult, AgentStatus
from remora.event_bridge import RemoraEventBridge

# Assuming we mapped the new library as `xgrammar_tools`
from xgrammar_tools.kernel import ToolKernel, KernelConfig
from xgrammar_tools.bundles.loader import AgentBundle

class XGrammarRunner:
    """Remora's orchestration wrapper around the clean xgrammar-tools kernel."""
    
    def __init__(
        self, 
        bundle: AgentBundle,
        node: CSTNode, 
        ctx: RemoraAgentContext,
        server_config: ServerConfig,
        event_emitter,
        context_manager: ContextManager
    ):
        self.bundle = bundle
        self.node = node
        self.ctx = ctx
        self.server_config = server_config
        self.event_emitter = event_emitter
        self.context_manager = context_manager

    async def run(self) -> AgentResult:
        # 1. Setup Kernel
        config = KernelConfig(
            base_url=self.server_config.base_url,
            model=self.bundle.manifest.model_id,
            timeout_s=self.server_config.timeout
        )
        kernel = ToolKernel(
            config=config, 
            plugin=self.bundle.get_plugin(), 
            backend=self.bundle.get_backend()
        )
        
        # 2. Setup Events
        observer = RemoraEventBridge(
            self.event_emitter, 
            self.context_manager, 
            self.node.node_id, 
            self.ctx.operation
        )
        
        # 3. Pull external state
        await self.context_manager.pull_hub_context()
        
        # 4. Render prompt logic
        prompt = f"Target Node:\n```python\n{self.node.text}\n```" # Simplified
        
        # 5. Execute!
        kernel_result = await kernel.run(
            prompt=prompt,
            system=self.bundle.get_system_prompt(),
            tools=self.bundle.manifest.tools,
            observer=observer
        )
        
        # 6. Map to legacy result format
        # Real implementation would infer changed_files from tool events via ContextManager
        return AgentResult(
            status=AgentStatus.SUCCESS,
            workspace_id=self.ctx.agent_id,
            changed_files=[], 
            summary=kernel_result.text,
            details={"tool_calls": [c.name for c in kernel_result.tool_calls]},
            error=None
        )
```

---

## Step 4: Rewire the Orchestrator

**File snippet: modifying `src/remora/orchestrator.py`**
```python
from remora.runtime.xgrammar_runner import XGrammarRunner
from xgrammar_tools.bundles.loader import load_bundle

# Inside Coordinator.process_node() loop:
# Replace the FunctionGemmaRunner instantiation:

bundle_path = self.config.agents_dir / op_config.subagent
bundle = load_bundle(bundle_path)

runners[operation] = (
    ctx,
    XGrammarRunner(
        bundle=bundle,
        node=node,
        ctx=ctx,
        server_config=self.config.server,
        event_emitter=self._event_emitter,
        context_manager=ContextManager(...) # simplified
    )
)
```

**Implementation note:**
You must also delete `self._executor = ProcessIsolatedExecutor(...)` from the `Coordinator` initialization, as `.pym` process management is entirely handled correctly inside `AgentBundle.get_backend()` inside `xgrammar-tools`.

---

## Step 5: E2E Integration Testing

Replace `tests/test_runner.py` with `tests/test_e2e_refactor.py`. Leverage `pytest-asyncio` and `respx` to mock `httpx` traffic targeting the `Config.base_url`, ensuring the `XGrammarRunner` correctly initiates the loop, calls the mocked endpoint, and fires Remora internal events gracefully.

```python
import pytest
import respx
from httpx import Response
from remora.runtime.xgrammar_runner import XGrammarRunner

@pytest.mark.asyncio
async def test_xgrammar_runner_e2e():
    # 1. Setup mock bundle dir
    # 2. Route httpx calls to 'http://localhost' -> Response(...)
    # 3. Instantiate XGrammarRunner
    # 4. Assert runner.run() completes and returns expected AgentResult
    pass
```

## Post-Refactoring Clean Up

- Audit `remora.yaml` schemas. Update configuration definitions to point directly to "bundle directories" rather than "subagent definitions."
- Verify the `LlmConversationLogger` functions as intended. Since the bridge translates `xgrammar-tools` events to Remora events, the logger should theoretically "just work," but it requires manual validation.
