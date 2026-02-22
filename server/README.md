# Remora Inference Server (Quick Reference)

This directory hosts the vLLM server stack used by Remora. It exposes an OpenAI-compatible API on your Tailscale network and optionally serves the `agents/` directory for bundle distribution.

## Prerequisites

- NVIDIA GPU with current drivers installed on the host
- Docker Desktop (WSL2 backend) on Windows or Docker Engine on Linux
- Tailscale installed on the server machine and dev machine
- Tailscale auth key + Hugging Face token (if model is gated)

## Bring-Up Commands

```bash
cd server
docker compose up -d --build
docker logs -f vllm-gemma
```

## Verify

```bash
uv run server/test_connection.py
```

Expected output:

```
Connecting to vLLM at http://remora-server:8000/v1...
SUCCESS: Connection successful.
```

## Agents Server (Optional)

The optional `agents-server` container serves the `agents/` directory for remote clients.

```bash
curl http://remora-server:8001/agents/lint/bundle.yaml
```

## Hot-load Adapters

```bash
python server/adapter_manager.py --name lint --path /models/adapters/lint
```

## Redeploy

```bash
ssh root@remora-server
./update.sh
```
