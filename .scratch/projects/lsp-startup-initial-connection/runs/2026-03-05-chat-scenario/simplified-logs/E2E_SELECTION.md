# E2E Scenario Selection
## Selected Scenario
`chat`

## Rationale
The issue is about the initial LSP startup connection taking too long or failing entirely (`REMORA_CLIENTS=0` headless output). The `chat` scenario triggers the `RemoraChat` command which relies on the `get_client_with_retry` loop. The skill instructions mention: "For chat-delivery issues, default to chat" and "startup can false-pass on UI/init notifications". After running `startup`, the `REMORA_CLIENTS=0` headless check verified it was failing to start, so switching to `chat` gets us the full execution trace including user commands.

## Command Run
```bash
devenv shell -- python -m e2e.run --scenario chat
```
