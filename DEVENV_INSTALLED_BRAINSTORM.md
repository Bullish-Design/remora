# DEVENV_INSTALLED_BRAINSTORM.md

> Exploring how to package Remora + Neovim as a single `devenv.nix`-installable unit that auto-parses any workspace on shell entry.

---

## 1. The Vision

Today, Remora is a development-mode monorepo: the library, the LSP, the Neovim plugin, the demo project, the agent bundles, and the devenv.nix all live in one repo. To use Remora in a **different** project you'd have to clone remora, symlink things, and manually wire up the config.

The goal is: **any repo can add one import to its `devenv.nix` and get a fully working Remora environment** — Neovim with the plugin loaded, the LSP server running, tree-sitter discovery on startup, default agents active, and a `.remora/` directory convention for per-repo customization.

```nix
# consumer project's devenv.nix
{ pkgs, inputs, ... }: {
  imports = [ inputs.remora.devenvModules.default ];

  remora.enable = true;
  remora.discoveryPaths = [ "src/" "lib/" ];
  remora.languages = [ "python" "markdown" ];
}
```

That's it. `devenv shell` gives you `nv2` with Remora, `remora` CLI commands, and the workspace auto-indexed.

---

## 2. What "Installable" Means — The Packaging Problem

### 2.1 Current State

| Component | Location | How it runs |
|-----------|----------|-------------|
| Python library (`remora`) | `src/remora/` | `uv pip install -e .` in venv |
| CLI entrypoints | `pyproject.toml [project.scripts]` | `remora`, `remora-lsp`, `remora-index` |
| Neovim plugin (Lua) | `src/remora/lsp/nvim/` | Added to `rtp` via `nv2.extraRuntimePaths` |
| Agent bundles (YAML + .pym) | `agents/` | Referenced by `remora.yaml` `bundle_root` |
| Extension models (.py) | `.remora/models/` | Dynamically imported by `load_extensions()` |
| Tree-sitter queries (.scm) | `src/remora/queries/` | Loaded by `importlib.resources` inside the package |
| Config | `remora.yaml` at project root | Found by `_find_config_file()` walking up to `pyproject.toml` |
| Runtime state | `.remora/` (indexer.db, agents/, events/, hub.pid) | Created by LSP/CLI at runtime |

### 2.2 What Needs to Be Distributable

For a consumer project to use Remora without cloning the repo:

1. **Python package** — must be installable as a dependency (pip/uv), not just editable-mode.
2. **Neovim plugin** — must be loadable from the installed package or a Nix derivation (not a local path).
3. **Default agent bundles** — must ship with the package or be copied into the consumer's `.remora/`.
4. **Tree-sitter queries** — already handled via `importlib.resources` (good).
5. **Default extensions** — need a "standard library" of AgentExtension classes.
6. **nixvim integration** — the `nv2.extraRuntimePaths` and `nv2.extraInitLua` need to work from a Nix store path, not `$PWD`.

### 2.3 Packaging Strategy Options

**Option A: Nix flake with Python package + Neovim plugin overlay**

- Remora repo exposes a flake with:
  - A Python package derivation (built from pyproject.toml via `buildPythonPackage`)
  - A Vim plugin derivation (just the `src/remora/lsp/nvim/` tree)
  - A devenv module that wires both together
- Consumer adds `inputs.remora.url = "github:Bullish-Design/remora"` to their flake
- The devenv module handles: adding remora to Python deps, adding the nvim plugin, configuring LSP, running reconciliation on shell entry

**Option B: Pure Python package + runtime Nix wrapper**

- Publish `remora` to PyPI (or private index)
- Neovim plugin ships inside the Python package (`remora.lsp.nvim` is already a subpackage)
- Nix module locates the installed package and extracts the nvim plugin path
- Less Nix complexity, but the Neovim plugin path becomes `$(python -c "import remora; print(remora.__path__[0])")/lsp/nvim`

**Recommendation: Option A.** The nixvim integration is already deeply Nix-native. Fighting against that by trying to locate Python paths at runtime adds fragility. A flake-based approach keeps everything reproducible and declarative.

---

## 3. The devenv Module Design

### 3.1 Module Interface

```nix
# What the consumer sees
{
  options.remora = {
    enable = mkEnableOption "Remora reactive agent swarm";

    # Discovery
    discoveryPaths = mkOption {
      type = types.listOf types.str;
      default = [ "src/" ];
      description = "Paths to scan for code nodes";
    };
    languages = mkOption {
      type = types.nullOr (types.listOf types.str);
      default = null;  # null = all supported
      description = "Limit discovery to these languages";
    };

    # Model
    modelBaseUrl = mkOption {
      type = types.str;
      default = "http://localhost:8000/v1";
    };
    modelDefault = mkOption {
      type = types.str;
      default = "Qwen/Qwen3-4B";
    };

    # Agent bundles
    bundleRoot = mkOption {
      type = types.str;
      default = ".remora/bundles";
      description = "Where agent bundle YAMLs live (relative to project root)";
    };
    defaultBundles = mkOption {
      type = types.bool;
      default = true;
      description = "Copy standard agent bundles into .remora/bundles/ if not present";
    };

    # Extensions
    extensionsDir = mkOption {
      type = types.str;
      default = ".remora/models";
      description = "Directory for AgentExtension Python classes";
    };
    defaultExtensions = mkOption {
      type = types.bool;
      default = true;
      description = "Copy standard extensions into .remora/models/ if not present";
    };

    # Neovim
    filetypes = mkOption {
      type = types.listOf types.str;
      default = [ "python" "markdown" "toml" ];
    };
    keyPrefix = mkOption {
      type = types.str;
      default = "<leader>r";
    };

    # Auto-reconcile
    reconcileOnEntry = mkOption {
      type = types.bool;
      default = true;
      description = "Run 'remora swarm reconcile' on devenv shell entry";
    };
  };
}
```

### 3.2 Module Implementation Sketch

```nix
config = mkIf cfg.enable {
  # 1. Python environment gets remora as a dependency
  languages.python.enable = true;
  languages.python.venv.enable = true;
  # The remora package is added to the venv

  # 2. Neovim gets the plugin
  nv2.extraRuntimePaths = [ "${remoraPackage}/lib/python3.13/site-packages/remora/lsp/nvim" ];
  nv2.extraInitLua = ''
    local ok, remora = pcall(require, "remora")
    if ok then
      remora.setup({
        cmd = { "remora-lsp" },
        filetypes = ${luaList cfg.filetypes},
        root_markers = { ".remora", ".git", "pyproject.toml" },
        prefix = "${cfg.keyPrefix}",
      })
    end
  '';

  # 3. Shell entry: scaffold .remora/ and reconcile
  enterShell = ''
    # Ensure .remora directory exists
    mkdir -p .remora/models .remora/bundles .remora/events

    # Generate remora.yaml from Nix options if not present
    if [ ! -f remora.yaml ]; then
      remora-init --discovery-paths ${cfg.discoveryPaths} ...
    fi

    # Copy default bundles/extensions if opted in
    ${optionalString cfg.defaultBundles "remora-scaffold bundles"}
    ${optionalString cfg.defaultExtensions "remora-scaffold extensions"}

    # Auto-reconcile: discover nodes and populate event store
    ${optionalString cfg.reconcileOnEntry "remora swarm reconcile"}

    echo "Remora ready. Open nv2 to start."
  '';
};
```

---

## 4. The `.remora/` Directory Convention

### 4.1 Proposed Standard Layout

```
.remora/                          # Root (swarm_root in config)
├── remora.yaml                   # Optional override (or at project root)
├── models/                       # AgentExtension Python files
│   ├── 00_scaffold_initializer.py   # Numbered for priority (first match wins)
│   ├── 10_test_function.py
│   └── 50_generic_chat.py
├── bundles/                      # Agent bundle manifests (structured-agents format)
│   ├── docstring/
│   │   ├── bundle.yaml
│   │   └── tools/
│   │       ├── read_type_hints.pym
│   │       └── submit_result.pym
│   ├── lint/
│   │   └── bundle.yaml
│   └── chat/
│       └── bundle.yaml
├── queries/                      # Custom tree-sitter queries (override/extend defaults)
│   └── python/
│       └── remora_core/
│           └── custom_decorators.scm
├── events/                       # Runtime: event store SQLite
│   └── events.db
├── agents/                       # Runtime: per-agent state (auto-managed)
│   └── <hash>/
│       └── state.jsonl
├── subscriptions.db              # Runtime: subscription registry
├── indexer.db                    # Runtime: indexer state
└── hub.pid                       # Runtime: process lock
```

### 4.2 User-Facing vs. Runtime Directories

| Directory | User-editable? | Committed to git? | Purpose |
|-----------|---------------|-------------------|---------|
| `models/` | Yes | Yes | Custom agent extensions |
| `bundles/` | Yes | Yes | Agent bundle manifests + tools |
| `queries/` | Yes | Yes | Custom tree-sitter queries |
| `events/` | No | No (.gitignore) | Runtime event store |
| `agents/` | No | No (.gitignore) | Runtime agent state |
| `subscriptions.db` | No | No (.gitignore) | Runtime subscriptions |
| `indexer.db` | No | No (.gitignore) | Runtime indexer cache |
| `hub.pid` | No | No (.gitignore) | Runtime PID lock |

### 4.3 Recommended `.gitignore` Addition

```
# Remora runtime state (auto-generated, do not commit)
.remora/events/
.remora/agents/
.remora/subscriptions.db
.remora/indexer.db
.remora/hub.pid
```

### 4.4 Scaffolding Command

A new CLI command `remora init` (or `remora scaffold`) should:

1. Create `.remora/` directory structure
2. Copy default bundles from the installed package
3. Copy standard extension templates
4. Generate a starter `remora.yaml` with sensible defaults
5. Append `.gitignore` entries for runtime directories
6. Print a summary of what was created

```
$ remora init
Created .remora/models/        (3 standard extensions)
Created .remora/bundles/       (5 standard bundles: chat, docstring, lint, test, harness)
Created .remora/queries/       (empty, for custom queries)
Updated .gitignore             (added runtime exclusions)
Generated remora.yaml          (discovery_paths: ["src/"], model: Qwen/Qwen3-4B)

Run 'remora swarm reconcile' to index your codebase.
```

---

## 5. Auto-Parse on Environment Startup

### 5.1 The Startup Sequence

When a developer runs `devenv shell` (or `direnv` triggers it), the following should happen automatically:

```
1. Nix builds/activates the shell environment
   └── Python venv with remora installed
   └── nv2 with remora nvim plugin in rtp

2. enterShell runs:
   a. Check if .remora/ exists
      ├── No  → run `remora init` (scaffold)
      └── Yes → continue

   b. Run `remora swarm reconcile`
      ├── Discovery: tree-sitter parses all configured paths
      ├── Diff: compare discovered CSTNodes against existing event store
      ├── Emit: NodeDiscoveredEvent for new/changed nodes
      ├── Emit: NodeRemovedEvent for deleted nodes
      └── Print summary: "142 agents active, 3 new, 0 orphaned"

3. Developer opens nv2 (or it auto-opens)
   a. Neovim starts, loads remora plugin from rtp
   b. remora.setup() registers LSP config
   c. Opening a file triggers LSP client → spawns remora-lsp
   d. LSP server connects to existing .remora/events/events.db
   e. CodeLens, hover, code actions immediately available
```

### 5.2 Performance Concerns

The reconcile step on shell entry must be fast:

- **Cold start** (no existing event store): Full discovery + event emission. For a medium project (500 files, 3000 nodes), this takes ~2-5 seconds. Acceptable.
- **Warm start** (existing event store, few changes): Hash comparison is O(n) in nodes but very fast. Only changed files re-emit events. Sub-second for most cases.
- **Large monorepos**: May need a `reconcileOnEntry = false` option and manual reconcile. Or a `--quick` mode that only checks git-dirty files.

### 5.3 Lazy vs. Eager Initialization

Two strategies for when the LSP also starts:

**Eager (current):** LSP starts when first supported file opens. It creates EventStore/SubscriptionRegistry from scratch (reading from the SQLite DB that reconcile already populated). Fast because it just loads existing state.

**Lazy (alternative):** LSP server only starts on explicit user action (`:RemoraChat`, etc.). Reduces startup overhead but means CodeLens/hover aren't available until first interaction.

**Recommendation:** Keep eager. The reconcile-on-shell-entry ensures the DB is warm by the time the LSP starts. The cost of starting the LSP is negligible compared to the reconcile.

---

## 6. Standard Nodes and Extensions

### 6.1 What Ships by Default

The "standard library" of Remora should include:

**Extensions (`.remora/models/`):**

| File | Matches | Behavior |
|------|---------|----------|
| `00_todo_tracker.py` | `node_type == "todo"` | Subscribes to ContentChangedEvent; tracks completion state |
| `10_test_scaffold.py` | `node_type == "function" and not name.startswith("test_")` | Generates test stubs when function changes |
| `20_docstring_agent.py` | `node_type in ("function", "class")` | Generates/updates docstrings |
| `30_note_summarizer.py` | `node_type == "note"` | Summarizes markdown notes, tracks dependencies |
| `50_generic_chat.py` | Always True (catch-all) | Basic chat capability for any node |

**Bundles (`bundles/`):**

| Bundle | Purpose | Tools |
|--------|---------|-------|
| `chat/` | Interactive chat with any agent | rewrite_self, message_node, read_node |
| `docstring/` | Docstring generation | read_type_hints, read_current_docstring, write_docstring, submit_result |
| `lint/` | Linting integration | run_linter, read_file, apply_fix, submit_result |
| `test/` | Test generation | analyze_signature, read_existing_tests, write_test_file, run_tests, submit_result |
| `harness/` | Generic tool harness | simple_tool, submit_result |

### 6.2 Making It Easy to Customize

The key insight: **users should never need to touch the installed package.** All customization happens in `.remora/`:

1. **Override an extension**: Create a file with a lower number prefix (e.g., `05_my_special_function.py`). First match wins.
2. **Add a new bundle**: Create a directory in `.remora/bundles/my_agent/` with a `bundle.yaml`.
3. **Add a custom query**: Place a `.scm` file in `.remora/queries/<language>/remora_core/`.
4. **Change config**: Edit `remora.yaml` at project root.

### 6.3 Extension Discovery Resolution Order

When `load_extensions()` runs, it should check (in order):

1. **Project-local**: `.remora/models/*.py` (highest priority)
2. **Standard library**: Bundled extensions from the installed package (fallback)

This means a project can:
- Use only defaults (empty `models/` dir)
- Override specific extensions (add numbered files)
- Disable a default (add a file that `matches()` the same nodes but does nothing)

**Implementation change needed:** `load_extensions()` currently only looks at one directory. It needs to also load from a "standard" directory inside the remora package, with the project-local dir taking priority.

---

## 7. The Nix Flake Structure

### 7.1 What the Remora Flake Exposes

```nix
{
  outputs = { self, nixpkgs, ... }: {
    # For devenv import
    devenvModules.default = ./nix/devenv-module.nix;

    # For standalone use
    packages.x86_64-linux = {
      remora = <python package derivation>;
      remora-nvim = <vim plugin derivation>;
    };

    # For nixvim overlay consumers
    overlays.default = final: prev: {
      vimPlugins = prev.vimPlugins // {
        remora-nvim = self.packages.${prev.system}.remora-nvim;
      };
    };
  };
}
```

### 7.2 The Python Package Derivation

```nix
remora = python3Packages.buildPythonPackage {
  pname = "remora";
  version = "0.4.12";
  src = ./.;
  format = "pyproject";

  nativeBuildInputs = [ python3Packages.hatchling ];
  propagatedBuildInputs = with python3Packages; [
    click typer rich tqdm pyyaml watchfiles
    pydantic pydantic-settings
    tree-sitter tree-sitter-python tree-sitter-markdown
    pygls lsprotocol
    # ... etc
  ];

  # Include queries, bundles, and nvim plugin in the wheel
  postInstall = ''
    cp -r agents $out/lib/python*/site-packages/remora/standard_bundles
    cp -r src/remora/lsp/nvim $out/lib/python*/site-packages/remora/nvim_plugin
  '';
};
```

### 7.3 The Neovim Plugin Derivation

```nix
remora-nvim = pkgs.vimUtils.buildVimPlugin {
  pname = "remora-nvim";
  version = "0.4.12";
  src = ./src/remora/lsp/nvim;
};
```

### 7.4 Consumer Flake Example

```nix
# consumer's flake.nix
{
  inputs = {
    devenv.url = "github:cachix/devenv";
    remora.url = "github:Bullish-Design/remora";
  };

  outputs = { self, devenv, remora, nixpkgs, ... }: {
    # devenv picks up devenv.nix automatically
  };
}

# consumer's devenv.nix
{ pkgs, inputs, ... }: {
  imports = [ inputs.remora.devenvModules.default ];

  remora = {
    enable = true;
    discoveryPaths = [ "src/" "tests/" ];
    languages = [ "python" ];
    modelBaseUrl = "http://my-gpu-server:8000/v1";
    reconcileOnEntry = true;
  };
}
```

---

## 8. Configuration Layering

### 8.1 Priority Order (Lowest to Highest)

1. **Compiled defaults** — `Config()` Pydantic defaults in `config.py`
2. **Nix module options** — devenv.nix `remora.*` options generate a `remora.yaml`
3. **Project `remora.yaml`** — checked into git, shared by team
4. **Environment variables** — `REMORA_*` prefix (Pydantic BaseSettings)
5. **Local overrides** — `remora.local.yaml` (gitignored)

### 8.2 Nix-to-YAML Bridge

The devenv module generates a `remora.yaml` from Nix options **only if one doesn't already exist**. This prevents Nix from overwriting manual config. The generated file includes a header comment:

```yaml
# Auto-generated by Remora devenv module. Edit freely; this file won't
# be regenerated if it already exists. Delete to regenerate from Nix options.
discovery_paths: ["src/"]
model_base_url: "http://localhost:8000/v1"
model_default: "Qwen/Qwen3-4B"
# ...
```

### 8.3 Environment Variable Support (Already Exists)

The `Config` class already supports `REMORA_*` env vars via Pydantic BaseSettings. The `remora.yaml` also supports `${VAR:-default}` expansion. No changes needed here.

---

## 9. Challenges and Open Questions

### 9.1 Python Dependency Hell

Remora has heavy dependencies: `structured-agents`, `grail`, `cairn`, `fsdantic` — all from private GitHub repos. For Nix packaging:

- **Option 1:** Vendor them as flake inputs and build from source.
- **Option 2:** Use a Nix Python builder that supports `uv` lockfiles (`uv2nix`, `dream2nix`).
- **Option 3:** Ship a pre-built wheel in the Nix store (fast but less reproducible).
- **Open question:** How do we handle the `structured-agents[grammar,vllm]` extras which pull in large ML libraries?

**Recommendation:** Start with a hybrid: the devenv module sets up a Python venv with `uv`, and `uv pip install remora` handles the Python deps. The Nix side only packages the Neovim plugin and the shell integration. This avoids the Nix-Python packaging nightmare while keeping the editor integration clean.

### 9.2 Tree-sitter Grammar Availability

Tree-sitter grammars for the Neovim side come from nixvim's treesitter plugin. But the Python side uses `tree-sitter-python`, `tree-sitter-markdown`, etc. as pip packages. These are separate implementations. Need to verify they produce compatible parse trees (they do — same grammar repos, just different bindings).

### 9.3 nixvim Dependency

The current `devenv.nix` imports from a local nixvim checkout: `imports = [ /home/andrew/Documents/Projects/nixvim/devenv.nix ]`. For distribution, nixvim must be a proper flake input. The remora flake should declare nixvim as an input, and the devenv module should import it.

### 9.4 First-Run UX

When a developer first enters a project with Remora:
- `.remora/` doesn't exist → needs scaffolding
- No `remora.yaml` → needs generation
- No event store → needs initial reconcile
- This could take a few seconds on first entry

**Mitigation:** Show clear progress output during enterShell. Subsequent entries are fast (warm DB, no changes).

### 9.5 Model Server Dependency

Remora needs a model server (vLLM, Ollama, etc.) for agent execution. The devenv should:
- Not **require** a model server for basic functionality (discovery, indexing, CodeLens all work without one)
- Optionally spin up a local model server via `services` if configured
- Default to a reasonable `modelBaseUrl` (localhost:8000)

### 9.6 Multi-Language Query Customization

The `.remora/queries/` overlay needs design:
- Do custom queries **replace** or **extend** the built-in queries?
- If extend: how are they merged? (Concatenate .scm files? Separate query pack name?)
- If replace: how does the user know what they're replacing?

**Recommendation:** Extend by default. Custom `.scm` files in `.remora/queries/<lang>/remora_core/` are loaded alongside built-in ones. To replace, use a different query pack name and configure it in `remora.yaml`.

---

## 10. Implementation Phases

### Phase 1: Refactor for Distribution (No Nix Changes Yet)

1. **Standard extensions library**: Move demo extensions from `remora_demo/project/.remora/models/` into `src/remora/standard_extensions/`. Ship them in the wheel.
2. **Standard bundles**: Move `agents/` content into `src/remora/standard_bundles/`. Ship them in the wheel.
3. **`remora init` CLI command**: Scaffolds `.remora/` directory, copies standard extensions/bundles, generates `remora.yaml`, updates `.gitignore`.
4. **Extension layering**: Update `load_extensions()` to load from both project-local and package-bundled directories with proper priority.
5. **Query overlay support**: Update `_load_queries()` to check `.remora/queries/` before the package's built-in queries.

### Phase 2: Nix Flake + devenv Module

1. **Create flake.nix** in the remora repo exposing:
   - `devenvModules.default`
   - `packages.*.remora` (Python package, possibly via uv2nix or manual derivation)
   - `packages.*.remora-nvim` (Vim plugin derivation)
2. **devenv module** (`nix/devenv-module.nix`):
   - Options as described in Section 3.1
   - Adds remora to Python venv
   - Configures nv2 with the Neovim plugin
   - Runs `remora init` + `remora swarm reconcile` in enterShell
3. **Convert nixvim from local path to flake input**
4. **Test in a clean consumer project** (not the remora repo itself)

### Phase 3: Polish and Ergonomics

1. **`remora doctor`**: Diagnostic command that checks all dependencies, model server connectivity, DB health, etc.
2. **Watch mode integration**: Optional file watcher that re-reconciles on save (already exists via `watchfiles` dep, needs integration with enterShell or as a background service)
3. **devenv services**: Optional `services.remora-watcher` that runs a file watcher daemon
4. **Template project**: `remora init --template python-fastapi` that scaffolds a complete project structure with Remora pre-configured

---

## 11. The User Experience End-to-End

### First time setup (new project)

```bash
$ cd my-new-project
$ # Add remora input to flake.nix, import module in devenv.nix
$ devenv shell

Remora dev environment ready!
  Scaffolding .remora/ directory...
  Created .remora/models/        (5 standard extensions)
  Created .remora/bundles/       (5 standard bundles)
  Created .remora/queries/       (empty)
  Updated .gitignore
  Generated remora.yaml

  Reconciling workspace...
  Discovered 247 nodes across 42 files
  247 agents created, 0 orphaned

  Run 'nv2' to launch Neovim with Remora.

$ nv2 src/main.py
# Neovim opens with:
#   - CodeLens on every function/class showing agent status
#   - Hover shows agent ID, graph context, recent events
#   - <leader>ra toggles the agent panel
#   - <leader>rc opens chat with the agent under cursor
```

### Day 2+ (existing project)

```bash
$ devenv shell    # or direnv auto-loads

  Reconciling workspace...
  2 nodes updated, 1 new, 0 orphaned (248 total)

$ nv2
# Everything just works, picks up where you left off
```

### Adding a custom extension

```python
# .remora/models/05_api_route.py
from remora.extensions import AgentExtension

class APIRouteExtension(AgentExtension):
    @staticmethod
    def matches(node_type, name, *, file_path="", source_code=""):
        return node_type == "function" and "@app.route" in source_code

    @staticmethod
    def get_extension_data():
        return {
            "extension_name": "APIRoute",
            "custom_system_prompt": (
                "You are an API route handler agent. Monitor this endpoint "
                "for security issues, missing validation, and documentation."
            ),
            "extra_subscriptions": [
                {"event_types": ["ContentChangedEvent"]},
            ],
        }
```

No restart needed — `load_extensions()` uses mtime-based cache invalidation. The next reconcile or LSP restart picks it up.

---

## 12. Summary of Required Changes

| Area | Change | Effort |
|------|--------|--------|
| `src/remora/extensions.py` | Layer project-local over package-bundled extensions | Small |
| `src/remora/core/discovery.py` | Support `.remora/queries/` overlay | Small |
| `src/remora/cli/main.py` | Add `remora init` / `remora scaffold` command | Medium |
| `src/remora/standard_extensions/` | Move/create standard extension library | Medium |
| `src/remora/standard_bundles/` | Move `agents/` content into package | Medium |
| `pyproject.toml` | Include standard_bundles and standard_extensions in wheel | Small |
| `flake.nix` | New: expose devenv module, packages, overlays | Large |
| `nix/devenv-module.nix` | New: full devenv module with options | Large |
| `devenv.nix` (remora repo) | Refactor to use own module (dog-food) | Medium |
| nixvim integration | Convert from local path to flake input | Medium |
| Documentation | User guide for the devenv module | Medium |
