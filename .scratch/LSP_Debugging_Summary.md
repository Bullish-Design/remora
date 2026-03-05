● Summary of Remora LSP Debugging Work

  Previous Work (from initial summary)

  Fixes Applied Before This Session

  1. LSP Client Retry/Polling (init.lua)
    - Added get_client_with_retry() function that polls for the LSP client with exponential backoff (100ms → 500ms, up to 20 attempts / ~5 seconds)
    - Updated exec_command() and apply_code_action() to use retry when client not immediately available
  2. User Feedback (init.lua)
    - Shows [Remora] Connecting to LSP... notification while waiting
    - Shows [Remora] LSP connected! when successful
    - Shows [Remora] LSP not available after timeout
  3. Panel Retry on Open (panel.lua)
    - Added get_client_with_retry callback to panel configuration
    - Initial fetch_agent_data(true) now uses retry when panel first opens
    - Background autocmd refreshes use fetch_agent_data_no_retry() to avoid spamming
  4. SQLite Database Locking Fixes (event_store.py)
    - Reduced timeout from 15s to 2s
    - Increased retry attempts from 3 to 5 with exponential backoff
  5. Background Scan Optimization (main.py)
    - Changed from individual append() calls to batch_append() per file

  Original Root Cause Identified

  - Race condition: LSP takes 18-20 seconds to spawn after vim.lsp.enable()
  - Client lookup failed when user tried commands before LSP was ready
  - SQLite 15-second timeout caused long waits during concurrent access

  ---
  This Session's Work

  Problem Statement

  Despite the previous fixes, the cursor was still not triggering the agent panel to change, and nothing was getting through to the vLLM server.

  Root Cause Analysis

  Issue 1: asyncio.Lock Contention
  - The append() and batch_append() methods held self._lock for the entire retry loop, including during asyncio.sleep() delays
  - User queries (get_node_at_position) and event emissions (emit_event) needed the same lock
  - Background scan running continuously meant the lock was rarely available

  Issue 2: SQLite Database-Level Locking
  - Even after fixing the asyncio.Lock issue, SQLite only allows ONE writer at a time (even in WAL mode)
  - Background scan doing continuous batch_append calls blocked emit_event from writing HumanChatEvent
  - Chat messages could never reach the agent runner because they couldn't be written to the database

  Issue 3: Slow Retry Logic
  - 2-second SQLite timeout + exponential backoff (0.5s, 1s, 2s, 4s) = up to 17.5 seconds worst case
  - Operations would eventually succeed but far too slowly for interactive use

  Fixes Applied

  Fix 1: Release asyncio.Lock Before Sleeping (event_store.py)

  # Before (bad - holds lock during sleep):
  async with self._lock:
      for attempt in range(max_attempts):
          try: ... except: await asyncio.sleep(delay)

  # After (good - releases lock before sleep):
  for attempt in range(max_attempts):
      try:
          async with self._lock:
              result = await asyncio.to_thread(_do_operation)
          break
      except: await asyncio.sleep(delay)

  Fix 2: Separate Read Connection (event_store.py)

  - Added _read_conn for read-only queries that doesn't need the lock
  - With WAL mode, readers don't block writers and vice versa
  - Updated methods to use _read_conn:
    - get_node_at_position()
    - get_node()
    - list_nodes()
    - get_recent_events()
    - get_events_for_correlation()

  Fix 3: Background Scan Throttling (main.py)

  - Added 0.5s initial delay before scan starts (lets user operations proceed first)
  - Added 50ms delay between file processing (yields write lock regularly)

  Fix 4: Faster SQLite Retry Logic (event_store.py)

  - Reduced SQLite connection timeout: 2s → 100ms (fail fast)
  - Reduced retry backoff base: 500ms → 50ms
  - Increased retry attempts: 5 → 10
  - Worst case now ~2.5s instead of ~17.5s

  Files Modified

  1. src/remora/core/event_store.py
    - Added _read_conn for read-only operations
    - Restructured retry loops to release lock before sleeping
    - Reduced timeouts and backoff delays
    - Updated read methods to use dedicated read connection
  2. src/remora/lsp/main.py
    - Added initial delay before background scan
    - Added delay between file processing in scan loop

  Verification

  - All 28 unit tests pass
  - Panel now updates correctly (confirmed in logs: "agent changed to rm_n3gi29dn")
  - Read operations no longer blocked by write contention