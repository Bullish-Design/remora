# vLLM Server Setup

This guide walks through bringing up the vLLM FunctionGemma server that Remora
connects to over Tailscale.

## Prerequisites

- NVIDIA GPU with recent drivers on the host
- Docker Desktop (WSL2 backend) on Windows or Docker Engine on Linux
- Tailscale installed on both the server machine and the dev machine
- Tailscale auth key (reusable) from the Admin Console
- Hugging Face token if the model is gated
- Git installed (to clone the server repo)

## Grab the Server Directory

Clone the Remora repo and enter the `server/` directory:

```bash
git clone https://github.com/Bullish-Design/remora.git
cd remora/server
```

## Storage Layout

The compose file expects three persistent directories:

- Base model weights: `/mnt/d/AI_Models/base`
- LoRA adapters: `/mnt/e/AI_Models/adapters`
- Hugging Face cache: `/mnt/d/AI_Models/cache`

Adjust these to match your SSD layout. Under WSL2, Windows drives are mounted as
`/mnt/<letter>/` (for example, `D:` -> `/mnt/d/`). For best performance, move
Docker Desktop’s `ext4.vhdx` disk image to a fast SSD via **Settings → Resources
→ Advanced → Disk image location**.

## Configuration

Create a local `.env` file in `remora/server` and keep it off Git:

```bash
cp .env.example .env
```

Then edit `.env` and set:

1. `TS_AUTHKEY` to your Tailscale auth key.
2. `HUGGING_FACE_HUB_TOKEN` to your Hugging Face token (or leave blank if the model is public).
3. `VLLM_BASE_MODEL_PATH`, `VLLM_ADAPTERS_PATH`, `VLLM_CACHE_PATH` to match the storage layout above.
4. Optional overrides like `TS_HOSTNAME` or `AGENTS_DIR` if needed.

## FunctionGemma Tool Calling

The `entrypoint.sh` script starts vLLM with FunctionGemma tool calling enabled:

- `--enable-auto-tool-choice`
- `--tool-call-parser functiongemma`
- `--chat-template /app/tool_chat_template_functiongemma.jinja`

The chat template file is bundled into the container at `/app/tool_chat_template_functiongemma.jinja`.

## First Boot

```bash
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
uv run test_connection.py
```

Expected output:

```
Connecting to vLLM at http://remora-server:8000/v1...
SUCCESS: Connection successful.
```

## Agents Definitions (Optional)

Serve the shared agent YAML files from the server:

```bash
curl http://remora-server:8001/agents/lint/lint_subagent.yaml
```

## Adapter Hot-Loading (Optional)

Load a LoRA adapter without restarting the container:

```bash
python adapter_manager.py --name lint --path /models/adapters/lint
```

## Subsequent Deploys

Use the Tailscale sidecar to pull and redeploy:

```bash
ssh root@remora-server
./update.sh
```

## Updating After GitHub Changes

If the `server/` files are updated and pushed to GitHub, pull the latest code
and rebuild the containers (your `.env` stays local):

```bash
cd remora/server
git pull origin main
docker compose up -d --build
```

Then confirm the vLLM server is healthy:

```bash
docker logs -f vllm-gemma
```

## Enabling LoRA Adapters on Boot

1. Copy adapter directories into the adapters path (e.g. `lint/`, `test/`).
2. Uncomment the Multi-LoRA block in `entrypoint.sh`.
3. Redeploy with `./update.sh`.
4. Reference adapters in `remora.yaml` via `operations.<name>.model_id`.

## Troubleshooting

- `FAILED: Connection refused`: wait for model load to finish, retry the test.
- `FAILED: Name or service not known`: Tailscale not connected; check
  `tailscale status`.
- `CUDA out of memory`: reduce `--max-num-seqs` in `entrypoint.sh`.
- Model re-downloads every boot: volume paths incorrect; verify
  `docker-compose.yml` mounts.
- C: drive filling up on Windows: move Docker Desktop disk image to another
  drive as noted above.

