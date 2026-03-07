# Assumptions

- AgentFS (`agentfs_sdk`) is external and not directly modifiable in this effort.
- FSdantic is under our control and is the best place to implement low-level behavior changes.
- Remora consumes FSdantic via Cairn (`CairnWorkspaceService` -> `cairn.runtime.workspace_manager` -> `Fsdantic.open`).
- Current lock failures are caused by AgentFS `read_file()` mutating `atime` on every read.
- Backward compatibility matters for external FSdantic users; default behavior should remain unchanged unless explicitly configured.
- Desired outcome: Remora can disable `atime` writes for workspace reads without forking AgentFS.
