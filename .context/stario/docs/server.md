
stario.dev
Server
6–8 minutes
Server Reference ¶

The Server runs your Stario application, handling networking, worker threads, and graceful shutdown.
Starting the Server ¶

The simplest way to run your app is app.serve():

import asyncio
from stario import Stario, RichTracer

async def main():
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", home)
        await app.serve()

if __name__ == "__main__":
    asyncio.run(main())

For more control, instantiate Server directly:

from stario.http.app import Server

server = Server(app, host="0.0.0.0", port=8000, workers=4)
await server.run()

Configuration ¶
Parameter 	Default 	Description
host 	"127.0.0.1" 	TCP bind address. Use "0.0.0.0" for all interfaces.
port 	8000 	TCP port number.
unix_socket 	None 	Path to a Unix domain socket. Mutually exclusive with host/port.
workers 	1 	Number of worker threads.
graceful_timeout 	5.0 	Seconds to wait for tasks to finish during shutdown.
backlog 	2048 	Connection backlog size.
Binding: TCP vs Unix Socket ¶
TCP (default) ¶

Listens on a host and port. Good for development and simple deployments.

await app.serve(host="127.0.0.1", port=8000)

Unix Domain Socket ¶

Listens on a file socket instead of a TCP port. Preferred when running behind a reverse proxy on the same machine - avoids TCP overhead and port management.

await app.serve(unix_socket="/run/myapp/server.sock")

When using a Unix socket:

    The socket file is created automatically with 0o666 permissions.
    If a stale socket file exists at the path, it is removed before binding.
    The socket file is cleaned up on shutdown.

    Tip: For reverse proxy setups with Caddy or Nginx, Unix sockets are the recommended approach. See the Reverse Proxy (Caddy) how-to.

Workers ¶

Stario uses threads for multi-worker concurrency - each worker runs its own asyncio event loop in a dedicated thread.

await app.serve(host="0.0.0.0", port=8000, workers=4)

TCP workers ¶

Multiple TCP workers bind to the same port using SO_REUSEPORT (available on Linux and macOS). The OS distributes incoming connections across workers. SO_REUSEPORT is not available on Windows - use workers=1 there.
Unix socket workers ¶

All workers share a single pre-created socket, so SO_REUSEPORT is not required. This works on all platforms.
Worker synchronization ¶

Workers synchronize during startup via a threading.Barrier. All workers must successfully bind before any start accepting connections. If one worker fails (e.g., port in use), all workers abort.

Worker 0 runs a background task that updates the shared HTTP Date header every second. This avoids expensive per-request timestamp formatting across all workers.
Performance: uvloop ¶

For production, use uvloop for a faster event loop:

import uvloop
uvloop.run(app.serve(host="0.0.0.0", port=8000, workers=4))

Lifecycle ¶

Stario uses thread-based workers - each worker runs its own asyncio event loop in a dedicated thread. This is designed for Python 3.14's free-threaded mode.

Both startup and shutdown are instrumented with telemetry spans.
Startup ¶

A server.startup span is created with the following attributes:
Attribute 	Description
server.host 	Bind address (TCP mode)
server.port 	Port number (TCP mode)
server.unix_socket 	Socket path (Unix mode)
server.workers 	Number of workers

The startup sequence:

    Register SIGINT and SIGTERM signal handlers.
    Spawn worker threads - each binds to the socket or port.
    All workers synchronize via a barrier - serving only begins once every worker is ready.

If any worker fails to bind (e.g., port in use, permission denied), the barrier breaks and all workers abort.
Shutdown ¶

A server.shutdown span is created when a signal is received, with these attributes:
Attribute 	Description
server.graceful_timeout 	Configured timeout
server.workers 	Number of workers
server.worker.{id}.connections_at_shutdown 	Open connections when shutdown started
server.worker.{id}.connections_force_closed 	Connections that had to be force-closed
server.worker.{id}.handler_tasks_cancelled 	Handler tasks that were cancelled

The shutdown sequence per worker:

    Stop accepting — close the server socket so no new connections arrive.
    Wait for connections to drain — poll every 0.1 s up to graceful_timeout for open connections to close on their own. Handlers using w.alive() exit their loop automatically once the shutdown future resolves, so well-behaved handlers finish naturally during this window.
    Force-close connections — any connections still open after the timeout have their transports closed.
    Cancel handler tasks — only stario-managed handler tasks are cancelled. External tasks on the same event loop (periodic flushes, metrics collectors, etc.) are never touched.
    Await cancelled tasks — cancelled tasks are gathered so their cleanup code can run.
    Wait for server close — server.wait_closed() ensures the socket is fully released.
    Cleanup — remove the Unix socket file and cancel the shared date-header ticker.

Graceful Shutdown ¶

Stario handles SIGINT (Ctrl+C) and SIGTERM to shut down cleanly. Signal handlers are registered on the running event loop using signal.signal() with loop.call_soon_threadsafe(), making them compatible with both Unix and Windows.

When shutdown is triggered, w.alive() loops exit automatically — code after the block runs, which is the natural place for cleanup:

async def subscribe(c: Context, w: Writer) -> None:
    async for msg in w.alive(relay.subscribe("updates")):
        w.patch(render(msg))
    # This runs on disconnect OR shutdown - cleanup here
    users.discard(c["user_id"])

You can also check w.shutting_down to detect shutdown outside of an alive() loop:

if w.shutting_down:
    # Server is shutting down, wrap up
    ...

Adjusting the timeout ¶

The graceful_timeout controls how long the server waits for open connections to close before force-closing them. Increase it for apps with long-lived connections like SSE streams:

await app.serve(graceful_timeout=30.0)

Hot Reload (Development) ¶

Stario doesn't include a built-in dev server. Use watchfiles for automatic restarts during development:

uv run watchfiles "python main.py" .

    Caution: The command string must be "python main.py" - don't wrap it with uv run inside watchfiles, as that swallows the SIGINT signal needed for reload. See the Hot Reload how-to for details.

Changing the world, one byte at a time
