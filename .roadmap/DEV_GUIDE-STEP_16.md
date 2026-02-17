# DEV GUIDE STEP 16: Accept / Reject / Retry Workflow

## Goal
Implement the workspace change control methods on `RemoraAnalyzer`: `accept`, `reject`, and `retry`. These let users act on individual operation results without touching workspaces for operations they haven't reviewed yet.

## Why This Matters
The accept/reject/retry workflow is the human authority gate. Every change the FunctionGemma models produce is staged in an isolated Cairn workspace; nothing reaches the stable codebase until the user explicitly accepts it. This step wires the result layer to Cairn's merge/discard APIs and provides the `retry` path for re-running a specific operation with modified configuration.

## Implementation Checklist
- Implement `RemoraAnalyzer` class with `accept`, `reject`, and `retry` methods.
- `accept(node_id, operation)` — calls Cairn to merge the operation's workspace into stable.
- `reject(node_id, operation)` — calls Cairn to discard the operation's workspace; stable is unchanged.
- `retry(node_id, operation, config_override)` — discards the existing workspace, re-runs the `FunctionGemmaRunner` for that operation with config_override applied, stores new workspace.
- Track workspace state: PENDING → ACCEPTED | REJECTED | RETRYING.
- Expose `bulk_accept(operations=None)` and `bulk_reject(operations=None)` for batch operations.

## Suggested File Targets
- `remora/analyzer.py`

## RemoraAnalyzer Interface

```python
class RemoraAnalyzer:
    def __init__(self, config: RemoraConfig, cairn_client: CairnClient):
        self.config = config
        self.cairn = cairn_client
        self._results: AnalysisResults | None = None

    async def analyze(self, paths: list[Path]) -> AnalysisResults:
        """Run full analysis pipeline on given paths."""
        ...

    async def accept(self, node_id: str, operation: str) -> None:
        """Merge operation workspace into stable workspace."""
        workspace_id = self._get_workspace_id(node_id, operation)
        await self.cairn.merge(workspace_id)

    async def reject(self, node_id: str, operation: str) -> None:
        """Discard operation workspace; stable unchanged."""
        workspace_id = self._get_workspace_id(node_id, operation)
        await self.cairn.discard(workspace_id)

    async def retry(
        self,
        node_id: str,
        operation: str,
        config_override: dict | None = None,
    ) -> AgentResult:
        """Discard existing workspace and re-run the operation."""
        await self.reject(node_id, operation)
        node = self._get_node(node_id)
        op_config = self._build_op_config(operation, config_override or {})
        # Re-run just this one operation
        runner = self._build_runner(node, operation, op_config)
        result = await runner.run()
        # Update stored results
        self._update_result(node_id, operation, result)
        return result

    async def bulk_accept(
        self,
        node_id: str | None = None,
        operations: list[str] | None = None,
    ) -> None:
        """Accept all pending workspaces matching the given filters."""
        ...

    async def bulk_reject(
        self,
        node_id: str | None = None,
        operations: list[str] | None = None,
    ) -> None:
        """Reject all pending workspaces matching the given filters."""
        ...
```

## Workspace State Tracking

```python
from enum import Enum

class WorkspaceState(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RETRYING = "retrying"
```

Track state in a simple dict keyed by `(node_id, operation)`. State must persist across `retry` calls. After `accept` or `reject`, state transitions to ACCEPTED or REJECTED and further accept/reject calls on the same workspace are no-ops with a warning.

## Implementation Notes
- `config_override` in `retry` is applied by merging the override dict into the operation's `OperationConfig`. This lets the user change settings like `max_turns`, `style`, or any domain-specific parameter without editing the config file.
- Cairn's merge API may fail if there are conflicts with the stable workspace (e.g., another accept already modified the same file). Handle this gracefully: log the conflict, leave both workspaces intact, and surface an error message to the user.
- `bulk_accept(operations=["lint"])` should accept all lint workspaces across all nodes. This is the primary path for operations with `auto_accept=true` in config.

## Testing Overview
- **Unit test (mocked Cairn):** `accept()` calls `cairn.merge()` with correct workspace ID.
- **Unit test (mocked Cairn):** `reject()` calls `cairn.discard()` with correct workspace ID.
- **Unit test:** `retry()` calls `reject()` then spawns a new runner with the overridden config.
- **Unit test:** `retry()` with `{"max_turns": 30}` passes `max_turns=30` to the new runner.
- **Unit test:** Calling `accept()` on an already-accepted workspace is a no-op with a warning (not an error).
- **Unit test:** `bulk_accept(operations=["lint"])` accepts all lint workspaces and no others.
