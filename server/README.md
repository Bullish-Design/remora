# Remora Inference Server

vLLM running `google/function-gemma-3-270m` in Docker, exposed to your
Tailscale network via a sidecar container.

## Prerequisites

- NVIDIA GPU with current drivers installed on the host
- [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
  with the **WSL2 backend** enabled, **or** Docker Engine on a Linux host
- [Tailscale](https://tailscale.com/download) installed on the server machine
  and on your development machine
- A Tailscale **Auth Key** (reusable):
  [Tailscale Admin Console → Settings → Keys](https://login.tailscale.com/admin/settings/keys)
- A Hugging Face token if the model is gated: <https://huggingface.co/settings/tokens>

## Configuration

Before first boot, edit `docker-compose.yml`:

1. Replace `tskey-auth-YOUR_KEY_HERE` with your Tailscale auth key
2. Replace `hf_YOUR_TOKEN_HERE` with your Hugging Face token (or remove the
   line if the model is public)
3. Adjust the volume mount paths to match your SSD layout:
   - `/mnt/d/AI_Models/base` → directory for the base model weights
   - `/mnt/e/AI_Models/adapters` → directory for fine-tuned LoRA adapters
   - `/mnt/d/AI_Models/cache` → Hugging Face download cache

   WSL2 maps Windows drives as `/mnt/<letter>/` (`D:` → `/mnt/d/`).

## First Boot

```bash
cd server/
docker compose up -d --build
```

Watch the model download and load:

```bash
docker logs -f vllm-gemma
```

The server is ready when you see a line like:

```
INFO:     Application startup complete.
```

## Verify

From any machine on your Tailscale network:

```bash
uv run server/test_connection.py
```

Expected output:

```
Connecting to vLLM at http://function-gemma-server:8000/v1...
SUCCESS: Connection successful.
```

## Redeploy After Changes

```bash
# SSH into the Tailscale sidecar (no password — Tailscale handles auth)
ssh root@function-gemma-server

# Pull and restart (runs in the container, so it affects the host Docker daemon)
./update.sh
```

## Enabling LoRA Adapters

Once you have trained LoRA adapters:

1. Copy adapter directories into `/mnt/e/AI_Models/adapters/` (e.g., `lint/`, `test/`)
2. Uncomment the `--enable-lora` block in `entrypoint.sh`
3. Run `./update.sh` via SSH to redeploy

In `remora.yaml`, set the adapter name under the operation's `model_id`:

```yaml
operations:
  lint:
    model_id: "lint"   # matches the name in entrypoint.sh --lora-modules
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `FAILED: Connection refused` | Container still starting | Wait 60s, re-run test |
| `FAILED: Name or service not known` | Tailscale not connected | Check `tailscale status` |
| `CUDA out of memory` | `--max-num-seqs` too high | Lower it in `entrypoint.sh` |
| Model re-downloads every boot | Cache volume not mapped | Check volume paths in `docker-compose.yml` |
| C: drive filling up | Docker ext4.vhdx on wrong drive | Move via Docker Desktop → Resources → Disk image location |
