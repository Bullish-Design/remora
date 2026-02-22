# Test Writing Guidelines

## DO: Test Observable Behavior

- Verify public method return values (`RemoraAnalyzer.analyze`, `Coordinator.process_node`).
- Assert event payloads emitted by `EventEmitter` implementations.
- Validate configuration merging and overrides.
- Use `TreeSitterDiscoverer` to confirm node extraction.

## DON'T: Test Implementation Details

- Avoid private attributes (prefixed with `_`).
- Avoid asserting internal task scheduling or queue sizes.
- Avoid coupling tests to internal logging output.

## Example: Testing Event Emission

```python
# Good: verify an event was emitted
emitted = []
emitter = lambda payload: emitted.append(payload)

# ... run a coordinator / kernel runner ...
assert any(e["event"] == "tool_call" for e in emitted)

# Bad: assert internal event buffer length
# assert len(runner._event_queue) == 3
```
