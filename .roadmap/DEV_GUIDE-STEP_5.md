# DEV GUIDE STEP 5: FunctionGemmaRunner — Model Loading + Context

## Goal
Implement the FunctionGemmaRunner's initialization: load the GGUF model via llama-cpp-python, build the model cache, and construct the initial message list from the subagent definition and CSTNode.

## Why This Matters
The runner is the core new component in Remora. This step establishes everything that happens before the first inference call: model loading, caching (to avoid reloading 288MB multiple times), and initial context rendering. Getting model loading and caching right here prevents significant performance problems when processing many nodes concurrently.

## Implementation Checklist
- Implement `ModelCache` singleton that caches `Llama` instances by model path string.
- Implement `FunctionGemmaRunner.__init__` / `__post_init__` that:
  - Validates GGUF path exists, raises `AGENT_002` if not
  - Fetches `Llama` instance from `ModelCache`
  - Initializes `self.messages: list[dict] = []`
  - Initializes `self.turn_count: int = 0`
- Implement `_build_initial_messages()`:
  - Appends `{"role": "system", "content": definition.initial_context.system_prompt}`
  - Appends `{"role": "user", "content": definition.initial_context.render(node)}`

## Suggested File Targets
- `remora/runner.py`

## ModelCache

```python
class ModelCache:
    _instances: dict[str, Llama] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, model_path: str, **kwargs) -> Llama:
        with cls._lock:
            if model_path not in cls._instances:
                cls._instances[model_path] = Llama(model_path=model_path, **kwargs)
            return cls._instances[model_path]

    @classmethod
    def clear(cls) -> None:
        """For testing: clear all cached instances."""
        with cls._lock:
            cls._instances.clear()
```

## FunctionGemmaRunner Skeleton

```python
@dataclass
class FunctionGemmaRunner:
    definition: SubagentDefinition
    node: CSTNode
    workspace_id: str
    cairn_client: CairnClient

    def __post_init__(self):
        if not self.definition.model.exists():
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase="model_load",
                error_code="AGENT_002",
                message=f"GGUF not found: {self.definition.model}",
            )
        self.model = ModelCache.get(
            str(self.definition.model),
            n_ctx=4096,
            n_threads=2,
            verbose=False,
        )
        self.messages: list[dict] = []
        self.turn_count: int = 0
        self._build_initial_messages()

    def _build_initial_messages(self) -> None:
        self.messages = [
            {
                "role": "system",
                "content": self.definition.initial_context.system_prompt,
            },
            {
                "role": "user",
                "content": self.definition.initial_context.render(self.node),
            },
        ]
```

## Llama Initialization Parameters
- `n_ctx=4096` — context window; sufficient for most code analysis tasks
- `n_threads=2` — conservative; leaves headroom for concurrent runners
- `verbose=False` — suppress llama.cpp progress logs during normal operation
- `n_gpu_layers=0` — CPU-only by default; expose as a config option for future GPU support

## Implementation Notes
- `ModelCache` must be thread-safe since multiple runners may initialize concurrently. Use a `threading.Lock` around the load check and assignment.
- The `AGENT_002` error should not be a raised Python exception mid-loop — return it as a failed `AgentResult` so the coordinator can handle it gracefully without crashing other runners. Model this carefully.
- `CairnClient` is a placeholder at this step; mock it in tests. The actual Cairn integration happens in Step 6.

## Testing Overview
- **Unit test:** Runner initializes without error given a mock valid GGUF path (mock `Llama` constructor).
- **Unit test:** `ModelCache.get(path)` called twice with the same path returns the same object.
- **Unit test:** `ModelCache` is thread-safe: concurrent `get()` calls don't create duplicate instances.
- **Unit test:** Missing GGUF path raises `AGENT_002` with correct fields.
- **Unit test:** `_build_initial_messages()` produces messages with correct roles and rendered content.
