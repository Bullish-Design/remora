# Context

Remora integration tests were failing with `turso.lib.OperationalError: database is locked` under concurrent workspace reads/writes. AgentFS reads update inode `atime`, so reads are writes at the DB level.

Current status:
- Highest-level Remora mitigation has been implemented by serializing workspace operations per agent workspace.
- Same-agent concurrent workspace creation now also serialized.
- Target tests in `tests/integration/cairn/test_concurrent_safety.py` pass after the Remora changes.

Next if we still want true "disable atime" behavior from configuration:
- Implement `read_atime_policy` in FSdantic.
- Pass through in Cairn `open_workspace`.
- Expose config in Remora and wire through.
