# Server Development Guide (vLLM Refactor)

This guide breaks the server-side work into small, verifiable steps. Each step
includes a quick test or verification so you can confirm progress before moving
on. It also clarifies **which machine** runs each command and provides **Windows
(command prompt/PowerShell) equivalents** where needed.

## Machines and terminology

- **Windows Host (Docker Desktop)**: The Windows machine that actually runs the
  containers. Run Docker commands here.
- **Linux Dev Machine**: The developer’s Linux box. Run `uv` and client tests
  here.

When a step says **Windows Host**, run the command in PowerShell or Windows
Terminal from the repo root (or from the `server/` directory as noted). When a
step says **Linux Dev Machine**, run the command in a Linux shell.

> **Tip for juniors:** If you aren’t sure where you are, run `pwd` (Linux) or
> `Get-Location` (PowerShell). The command should show the repo and `server/`.

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

- **Linux Dev Machine:** `ls server/`
- **Windows Host (PowerShell):** `Get-ChildItem .\server\`

Also validate the compose file:

- **Windows Host:** `cd server` then `docker compose config`

> **Tip for juniors:** You only need Docker Desktop for the `docker compose`
> validation. File creation can happen on either machine, but it’s easiest to
> edit on Linux and push/pull to Windows via Git.

## Step 2 — Implement the vLLM container image

**What to implement**

In `server/Dockerfile`, base the image on `vllm/vllm-openai:latest`, copy in
`entrypoint.sh`, and set it as the entrypoint.

**Verification**

- **Windows Host:**
  - `cd server`
  - `docker build -t vllm-gemma -f Dockerfile .`

> **Tip for juniors:** The Windows host is where Docker builds actually happen.
> Even if you edit files on Linux, run the build on Windows so Docker Desktop
> picks up the changes.

## Step 3 — Implement the Tailscale sidecar image

**What to implement**

In `server/Dockerfile.tailscale`, base on `tailscale/tailscale:latest`, install
`git`, `docker-cli`, and `docker-cli-compose`, and set `/app` as the workdir.

**Verification**

- **Windows Host:**
  - `cd server`
  - `docker build -t tailscale-vllm -f Dockerfile.tailscale .`
  - `docker run --rm -it tailscale-vllm sh -c "git --version && docker --version"`

> **Tip for juniors:** This image is a helper container that can run Docker
> commands inside the Tailscale network namespace.

## Step 4 — Implement `docker-compose.yml`

**What to implement**

Create the two-service stack:

- `tailscale` service with hostname `remora-server`
- `vllm-server` that shares the Tailscale network namespace

Use the volume mounts and environment variables described in the refactor plan.

**Verification**

- **Windows Host:**
  - `cd server`
  - `docker compose up -d --build`
  - `docker ps`
  - `docker logs -f vllm-gemma`

> **Tip for juniors:** `docker compose up -d --build` both builds images and
> starts containers. `docker logs -f` streams logs; press `Ctrl+C` to exit.

## Step 5 — Add the vLLM entrypoint

**What to implement**

Create `server/entrypoint.sh` with:

- Base model: `google/functiongemma-270m-it`
- `--enable-prefix-caching`
- Commented Multi-LoRA block for future adapters

**Verification**

- **Windows Host:**
  - `cd server`
  - `docker compose up -d --build`
  - `docker logs -f vllm-gemma`

> **Tip for juniors:** If you update `entrypoint.sh`, rebuild with `--build` so
> the container gets the new script.

## Step 6 — Add the connection test script

**What to implement**

Create `server/test_connection.py` as a PEP 723 script using `openai.AsyncOpenAI`
that hits `http://remora-server:8000/v1`.

**Verification**

- **Linux Dev Machine:**
  - `uv run server/test_connection.py`

> **Tip for juniors:** This test runs from Linux. It assumes your Linux machine
> is connected to the same Tailscale network and can resolve
> `remora-server`.

## Step 7 — Add the update script

**What to implement**

Create `server/update.sh` to pull from `main`, rebuild `vllm-server`, and tail
logs. This is meant to be run after SSH-ing into the Tailscale container.

**Verification**

- **Linux Dev Machine (recommended):**
  - `ssh root@remora-server`
  - `./update.sh`

- **Windows Host (PowerShell):**
  - `ssh root@remora-server`
  - `./update.sh`

Confirm:

- `git pull` succeeds
- `docker compose up -d --build vllm-server` succeeds
- Logs stream without errors

> **Tip for juniors:** You’re SSH’ing into the Tailscale container itself. The
> script runs inside that container, not on your local machine.

## Step 8 — Implement subagent definition serving (7.1)

**What to implement**

Add a small HTTP server that serves the `agents/` directory to clients.
Recommended approach:

- Create `server/agents_server.py` using FastAPI.
- Add `server/Dockerfile.agents` to run `uvicorn` on port `8001`.
- Serve `/agents/<path>` from a mounted `agents/` directory.
- Add a `docker-compose.yml` service (`agents-server`) sharing the Tailscale network.

**Verification**

- **Linux Dev Machine (client test):**
  - `curl http://remora-server:8001/agents/lint/lint_subagent.yaml`

- **Windows Host (PowerShell):**
  - `Invoke-WebRequest http://remora-server:8001/agents/lint/lint_subagent.yaml`

Confirm the response matches the source YAML file.

> **Tip for juniors:** `curl` is common on Linux. On Windows, PowerShell’s
> `Invoke-WebRequest` is the closest equivalent.

## Step 9 — Implement adapter hot-loading (7.4)

**What to implement**

Add a management script to load LoRA adapters at runtime using vLLM’s API.

- Create `server/adapter_manager.py`.
- Add a command that calls `POST /v1/load_lora_adapter` with:
  - `lora_name` (adapter name)
  - `lora_path` (path on the server)

**Verification**

- **Windows Host:**
  - Place a test adapter directory on the server (or a stub adapter).

- **Linux Dev Machine:**
  - Run the management command to load it:
    - `python server/adapter_manager.py --name <adapter name> --path /models/adapters/<adapter name>`
  - `uv run server/test_connection.py --model <adapter name>`

> **Tip for juniors:** The adapter files must exist on the Windows host’s
> filesystem (or a mounted volume) because that’s where vLLM runs.

## Step 10 — Final integration checks

**What to implement**

Confirm the server can be started, updated, and used by a client.

**Verification**

- **Windows Host:**
  - `cd server`
  - `docker compose up -d --build`

- **Linux Dev Machine:**
  - `uv run server/test_connection.py`

- **Linux Dev Machine (or Windows Host if preferred):**
  - `ssh root@remora-server ./update.sh`

- **Linux Dev Machine:**
  - Verify a new adapter can be hot-loaded without restarting the stack.

> **Tip for juniors:** If a test fails, check container logs first:
> `docker logs -f vllm-gemma` on the Windows host.
