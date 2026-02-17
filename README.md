# Remora

Local code analysis and enhancement using FunctionGemma subagents.

## vLLM setup

Remora uses a vLLM server on your Tailscale network. Follow the server bring-up guide, then point `remora.yaml` at the server.

```bash
uv run server/test_connection.py
```

Once the server is reachable, set `server.base_url` in your config and run `remora analyze <path>`.
