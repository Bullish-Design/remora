# vLLM Server Setup

This guide walks through bringing up the vLLM FunctionGemma server that Remora
connects to over Tailscale.

## Prerequisites

- NVIDIA GPU with recent drivers on the host
- Docker Desktop (WSL2 backend) on Windows or Docker Engine on Linux
- Tailscale installed on both the server machine and the dev machine
- Tailscale auth key (reusable) from the Admin Console
- Hugging Face token if the model is gated

## Storage Layout

The compose file expects three persistent directories:

- Base model weights: `/mnt/d/AI_Models/base`
- LoRA adapters: `/mnt/e/AI_Models/adapters`
- Hugging Face cache: `/mnt/d/AI_Models/cache`

Adjust these to match your SSD layout. Under WSL2, Windows drives are mounted as
`/mnt/<letter>/` (for example, `D:` → `/mnt/d/`). For best performance, move
Docker Desktop’s `ext4.vhdx` disk image to a fast SSD via **Settings → Resources
→ Advanced → Disk image location**.

## Configuration

Edit `server/docker-compose.yml` before first boot:

1. Set `TS_AUTHKEY` to your Tailscale auth key.
2. Set `HUGGING_FACE_HUB_TOKEN` to your Hugging Face token (or remove the line
   if the model is public).
3. Update the volume mount paths to match the storage layout above.

## First Boot

```bash
cd server
docker compose up -d --build
```

Watch for the model to download and load:

```bash
docker logs -f vllm-gemma
```

The server is ready when you see:

```
INFO:     Application startup complete.
```

## Verification

From any Tailscale-connected machine:

```bash
uv run server/test_connection.py
```

Expected output:

```
Connecting to vLLM at http://function-gemma-server:8000/v1...
SUCCESS: Connection successful.
```

## Subsequent Deploys

Use the Tailscale sidecar to pull and redeploy:

```bash
ssh root@function-gemma-server
./update.sh
```

## Enabling LoRA Adapters

1. Copy adapter directories into the adapters path (e.g. `lint/`, `test/`).
2. Uncomment the Multi-LoRA block in `server/entrypoint.sh`.
3. Redeploy with `./update.sh`.
4. Reference adapters in `remora.yaml` via `operations.<name>.model_id`.

## Troubleshooting

- `FAILED: Connection refused`: wait for model load to finish, retry the test.
- `FAILED: Name or service not known`: Tailscale not connected; check
  `tailscale status`.
- `CUDA out of memory`: reduce `--max-num-seqs` in `server/entrypoint.sh`.
- Model re-downloads every boot: volume paths incorrect; verify
  `docker-compose.yml` mounts.
- C: drive filling up on Windows: move Docker Desktop disk image to another
  drive as noted above.
