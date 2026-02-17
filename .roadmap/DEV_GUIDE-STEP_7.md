# DEV GUIDE STEP 7: Coordinator — FunctionGemmaRunner Dispatch

## Goal
Wire the orchestration layer: implement `Coordinator.process_node()` to spawn one `FunctionGemmaRunner` per requested operation, run them concurrently with a semaphore, and aggregate results into a `NodeResult`.

## Why This Matters
The coordinator is the glue between node discovery and the FunctionGemma runner layer. Unlike the previous monolithic `.pym` coordinator, this is a straightforward Python async class. Its main job is concurrency management and result aggregation. Getting the semaphore and error isolation right here ensures that one failed runner never silently kills its siblings.

## Implementation Checklist
- Implement `Coordinator` class with `process_node(node, operations, config) -> NodeResult`.
- For each enabled operation in `operations`: load `SubagentDefinition` from the path in `OperationConfig.subagent`.
- Spawn a `FunctionGemmaRunner` per operation; collect them and run with `asyncio.gather(return_exceptions=True)`.
- Wrap all runner execution in an `asyncio.Semaphore(config.runner.max_concurrent_runners)`.
- Collect both successful `AgentResult` objects and exceptions into `NodeResult`.
- Implement `NodeResult` model.

## Suggested File Targets
- `remora/orchestrator.py`
- `remora/models.py` (for `NodeResult`, `AnalysisSummary`)

## NodeResult Model

```python
class NodeResult(BaseModel):
    node_id: str
    node_name: str
    file_path: Path
    operations: dict[str, AgentResult]  # op name → result
    errors: list[dict]                  # Op-level errors (failed runners, init errors)

    @property
    def all_success(self) -> bool:
        return all(r.status == "success" for r in self.operations.values())
```

## Coordinator Pseudocode

```python
class Coordinator:
    def __init__(self, config: RemoraConfig, cairn_client: CairnClient):
        self.config = config
        self.cairn_client = cairn_client
        self._semaphore = asyncio.Semaphore(config.runner.max_concurrent_runners)

    async def process_node(
        self, node: CSTNode, operations: list[str]
    ) -> NodeResult:
        runners: dict[str, FunctionGemmaRunner] = {}
        errors = []

        for op in operations:
            op_config = self.config.operations.get(op)
            if not op_config or not op_config.enabled:
                continue
            definition_path = self.config.agents_dir / op_config.subagent
            try:
                definition = load_subagent_definition(
                    definition_path, agents_dir=self.config.agents_dir
                )
                runners[op] = FunctionGemmaRunner(
                    definition=definition,
                    node=node,
                    workspace_id=f"{op}-{node.node_id}",
                    cairn_client=self.cairn_client,
                )
            except Exception as e:
                errors.append({"operation": op, "phase": "init", "error": str(e)})

        async def run_with_limit(op: str, runner: FunctionGemmaRunner):
            async with self._semaphore:
                return op, await runner.run()

        raw = await asyncio.gather(
            *[run_with_limit(op, r) for op, r in runners.items()],
            return_exceptions=True,
        )

        results: dict[str, AgentResult] = {}
        for item in raw:
            if isinstance(item, Exception):
                errors.append({"phase": "run", "error": str(item)})
            else:
                op, result = item
                results[op] = result

        return NodeResult(
            node_id=node.node_id,
            node_name=node.name,
            file_path=node.file_path,
            operations=results,
            errors=errors,
        )
```

## Implementation Notes
- The coordinator is now a plain Python class, not a Cairn `.pym` agent. The Cairn sandboxing is handled by the runners' tool dispatch — not by the coordinator itself.
- `asyncio.Semaphore` must be created in the same event loop as the coroutines that acquire it. Create it in `__init__` or lazily on first use within the running event loop.
- `return_exceptions=True` in `asyncio.gather` is essential: without it, a single runner exception cancels all other concurrent runners.
- Each operation that fails at the `init` phase (bad YAML, missing GGUF) is added to `errors` but does not prevent other operations from running.

## Testing Overview
- **Unit test (mock runners):** `process_node` with 3 mocked runners returns `NodeResult` with 3 operation results.
- **Unit test:** Semaphore limits concurrency: with `max_concurrent_runners=2` and 4 runners, at most 2 run simultaneously.
- **Unit test:** One runner raising an exception is captured in `errors`; other runners still complete.
- **Unit test:** Disabled operation (`enabled: false`) is not spawned.
- **Unit test:** Bad YAML path for a subagent is recorded in `errors.phase=init`; other operations proceed.
