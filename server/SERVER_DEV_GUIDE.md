# Server Development Guide (vLLM Refactor)

This guide breaks the server-side work into small, verifiable steps. Each step
includes a quick test or verification so you can confirm progress before moving
on. Use this when implementing the new `server/` directory and the server-side
opportunities in the refactor plan.

## Scope

You will build the `server/` directory contents plus two future-facing features:

- **Subagent definition serving** (section 7.1 in `VLLM_REFACTOR.md`)
- **Adapter hot-loading** (section 7.4 in `VLLM_REFACTOR.md`)

The goal is a self-contained server setup that can be deployed over Tailscale
and extended later with these two server-side enhancements.

## Step 1 — Scaffold the `server/` directory

**What to implement**

Create the core files listed in the refactor plan:

- `server/Dockerfile`
- `server/Dockerfile.tailscale`
- `server/docker-compose.yml`
- `server/entrypoint.sh`
- `server/update.sh`
- `server/test_connection.py`
- `server/README.md`

**Verification**

- Confirm the files exist in `server/` and match the plan structure in
  `VLLM_REFACTOR.md`.
- Run `docker compose config` in `server/` to confirm the YAML is valid.

## Step 2 — Implement the vLLM container image

**What to implement**

In `server/Dockerfile`, base the image on `vllm/vllm-openai:latest`, copy in
`entrypoint.sh`, and set it as the entrypoint.

**Verification**

- From `server/`, run `docker build -t vllm-gemma -f Dockerfile .`.
- Confirm the image builds without errors and has the entrypoint set.

## Step 3 — Implement the Tailscale sidecar image

**What to implement**

In `server/Dockerfile.tailscale`, base on `tailscale/tailscale:latest`, install
`git`, `docker-cli`, and `docker-cli-compose`, and set `/app` as the workdir.

**Verification**

- From `server/`, run `docker build -t tailscale-vllm -f Dockerfile.tailscale .`.
- Start a shell in the image and check `git --version` and `docker --version`.

## Step 4 — Implement `docker-compose.yml`

**What to implement**

Create the two-service stack:

- `tailscale` service with hostname `function-gemma-server`
- `vllm-server` that shares the Tailscale network namespace

Use the volume mounts and environment variables described in the refactor plan.

**Verification**

- Run `docker compose up -d --build` in `server/`.
- Confirm `docker ps` shows both containers running.
- Confirm `docker logs -f vllm-gemma` shows the base model loading.

## Step 5 — Add the vLLM entrypoint

**What to implement**

Create `server/entrypoint.sh` with:

- Base model: `google/functiongemma-270m-it`
- `--enable-prefix-caching`
- Commented Multi-LoRA block for future adapters

**Verification**

- Restart the stack (`docker compose up -d --build`).
- Confirm logs show the server listening on port 8000 and the model loaded.

## Step 6 — Add the connection test script

**What to implement**

Create `server/test_connection.py` as a PEP 723 script using `openai.AsyncOpenAI`
that hits `http://function-gemma-server:8000/v1`.

**Verification**

- From any Tailscale-connected machine, run:
  `uv run server/test_connection.py`
- Expect the script to print `SUCCESS:` and the model reply.

## Step 7 — Add the update script

**What to implement**

Create `server/update.sh` to pull from `main`, rebuild `vllm-server`, and tail
logs. This is meant to be run after SSH-ing into the Tailscale container.

**Verification**

- `ssh root@function-gemma-server` (from a Tailscale-connected machine)
- Run `./update.sh` and confirm:
  - `git pull` succeeds
  - `docker compose up -d --build vllm-server` succeeds
  - Logs stream without errors

## Step 8 — Implement subagent definition serving (7.1)

**What to implement**

Add a small HTTP server that serves the `agents/` directory to clients.
Recommended approach:

- Create `server/agents_server.py` using FastAPI or Flask.
- Serve `/agents/<path>` from a mounted `agents/` directory.
- Add a `docker-compose.yml` service (or include in `vllm-server`) to run this.

**Verification**

- Start the service and request a known YAML file:
  `curl http://function-gemma-server:8000/agents/lint/lint_subagent.yaml`
- Confirm the response matches the source YAML file.
- Add a local cache test (client side) that pulls the YAML once and reuses it.

## Step 9 — Implement adapter hot-loading (7.4)

**What to implement**

Add a management script to load LoRA adapters at runtime using vLLM’s API.

- Create `server/server.py` (or `server/adapter_manager.py`).
- Add a command that calls `POST /v1/load_lora_adapter` with:
  - `lora_name` (adapter name)
  - `lora_path` (path on the server)

**Verification**

- Place a test adapter directory on the server (or a stub adapter if available).
- Run the management command to load it.
- Call `server/test_connection.py` with `model=<adapter name>` and ensure it
  succeeds.

## Step 10 — Final integration checks

**What to implement**

Confirm the server can be started, updated, and used by a client.

**Verification**

- `docker compose up -d --build` works from `server/`.
- `uv run server/test_connection.py` succeeds from a client machine.
- `ssh root@function-gemma-server ./update.sh` completes without errors.
- Verify a new adapter can be hot-loaded without restarting the stack.
