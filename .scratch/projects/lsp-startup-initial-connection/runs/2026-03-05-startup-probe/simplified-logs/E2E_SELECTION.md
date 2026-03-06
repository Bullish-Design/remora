# E2E Scenario Selection
## Selected Scenario
`startup`

## Rationale
The issue is about the initial LSP startup connection taking too long or failing entirely (`REMORA_CLIENTS=0` headless output). The `startup` scenario directly tests the Neovim LSP connection phase and whether it correctly registers agents on initial buffer open. A headless probe proved that the attach is failing, so we're running it with recording.

## Command Run
```bash
devenv shell -- nv2 --headless remora_demo/companion/demo/harness.py "+lua vim.defer_fn(function() local clients=vim.lsp.get_clients({name='remora'}); print('REMORA_CLIENTS=' .. tostring(#clients)); vim.cmd('qa!') end, 10000)"
devenv shell -- python -m e2e.run --scenario startup
```
