# Test Writing Guidelines

## DO: Test Observable Behavior
- Test public method return values
- Test that correct events are emitted
- Test that correct results are produced
- Test error conditions via exceptions or error return values

## DON'T: Test Implementation Details
- Avoid accessing private attributes (prefixed with `_`)
- Avoid asserting exact internal data structures
- Avoid counting exact method calls unless call count is the behavior
- Avoid testing intermediate states

## Example: Testing Event Emission

```python
# Good: Verify the event was emitted with expected data
events = []
runner.add_event_handler(lambda e: events.append(e))
await runner.run()
assert any(e.type == "tool_call" for e in events)

# Bad: Check internal event queue state
assert len(runner._event_queue) == 3
```
