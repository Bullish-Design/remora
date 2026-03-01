# Neovim Demo Implementation - Code Review

This document contains a thorough code review of the Neovim demo implementation across three primary files: `src/remora/demo/nvim_server.py`, `src/remora/nvim/server.py`, and `lua/remora_nvim/init.lua`.

## 1. `src/remora/demo/nvim_server.py`

### 🐛 Bugs & Critical Issues
- **Unix Sockets on Windows:** The code defaults to `/run/user/1000/remora.sock` and maps a Unix socket via `asyncio.start_unix_server`. You are developing on Windows. While modern Windows 10/11 supports Unix sockets (`AF_UNIX`), it lacks the `/run/user/...` hierarchy and can be prone to permission/path issues. A local TCP port or a cross-platform temp file abstraction is highly recommended for the fallback.
- **Exponential Workspace Bug (Confirmed user issue):** In `rpc_buffer_opened`, `compute_agent_id` is derived from `node.start_line` and `node.name`. The moment a test file sits unedited and a user adds an empty line above a function, the `start_line` changes, the hash changes, and Remora considers it a completely new agent. This orphans the old workspace and creates a new one, causing massive state bloat.
- **Leftover Linux Paths:** The comments and startup hints (`# so /home/andrew/Documents/...`) are all hardcoded to an old Linux setup, confusing to new developers.

### 🏗️ Architecture & duplicated Logic
- **Fat Controller:** This script handles FastAPI, Jinja2 template rendering, Datastar SSE, SQLite initialization, AgentRunner orchestrating, AND raw JSON-RPC over sockets. It's doing too much.
- **Duplication of NvimServer:** The logic for `handle_nvim_client` and message routing (`agent.select`, `agent.subscribe`, `swarm.emit`) is almost exactly duplicated in `src/remora/nvim/server.py`. The demo should `import NvimServer` rather than redefining the wheel.

### 🧹 Code Quality
- Excellent use of `asynccontextmanager` for lifespan management.
- `stream_events(request: Request)` contains commented-out Datastar fragments (`merge_fragments`), which points to recent firefighting. Glad to see `patch_elements` being used.
- In `rpc_buffer_opened`, the server iteratively reads every node from Treesitter and issues multiple async writes to the database (in `swarm_state.upsert` and agent state writing files). For a 2000-line python file with 100 functions, this will hammer the disk and block the RPC response. This should be batched.

## 2. `src/remora/nvim/server.py`

### 🐛 Bugs & Critical Issues
- **Same Unix Socket Limitation:** Uses `asyncio.start_unix_server(path=str(self._socket_path))`. Needs to be validated for cross-platform usage. 

### 🏗️ Architecture
- Much cleaner abstraction than the demo file. The `NvimServer` class cleanly encapsulates client connections, active subscriptions, and message dispatching.
- The path normalization in `_handle_swarm_emit`: `to_project_relative(self._project_root, event_data["path"])` is excellent and exactly what's missing in some of the rougher demo code.

### 🧹 Code Quality
- Good separation of concerns using `self._handlers` dictionary map for routing RPC methods.
- Needs to be integrated into `nvim_server.py` to stop the duplicate code footprint.

## 3. `lua/remora_nvim/init.lua`

### 🐛 Bugs & Critical Issues
- Hardcoding the fallback socket to `/run/user/1000/remora.sock` ensures that if `config.socket` is missing on Windows, the plugin will fail to connect with an obscure error.

### 🏗️ Architecture
- The plugin delegates nicely to `sidepanel`, `bridge`, and `navigation`.
- The `bridge.lua` mechanism (assuming from your provided context mapping) keeps a stateful TCP/Unix socket connection open. If the Remora daemon reboots, the lua client currently might need a neovim restart to reconnect unless there is robust retry logic in `bridge.lua`.

---

## Conclusion & Refactoring Recommendations
1. **Consolidate:** Purge the custom RPC loop out of `demo/nvim_server.py` and strictly instantiate the `NvimServer` class from `src/remora/nvim/server.py`.
2. **Move away from Unix Sockets:** Default to a dynamic local TCP port (e.g., pulling from a `.remora_port` file in the project root) or use Python's `tempfile` mechanism to grab a valid Unix socket path on all OS's.
3. **Batch DB writes:** When parsing a file via AST, insert all nodes as a single transaction into `swarm_state` to keep Neovim snappy.
