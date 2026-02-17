# Remora Inference Server (Quick Reference)

vLLM running `google/functiongemma-270m-it`, exposed to your Tailscale network.
For the full setup guide, see `docs/SERVER_SETUP.md`.

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
Connecting to vLLM at http://function-gemma-server:8000/v1...
SUCCESS: Connection successful.
```

## Redeploy

```bash
ssh root@function-gemma-server
./update.sh
```
