
stario.dev
Tiles Walkthrough
12–15 minutes
Walkthrough: The Tiles App ¶

The best way to learn Stario is to explore a working app. In this tutorial we'll set up the Tiles template - a collaborative painting board - and walk through every part of it: the handler signature, common usage patterns, real-time streaming, telemetry, and request access.

By the end, you'll understand the patterns that make up every Stario application.
Set Up the Project ¶

uvx stario@latest init

    Note: Stario v2 requires Python 3.14+. Running uvx stario@latest init ensures you get the latest version - uvx stario init without @latest may install a cached older version.

Pick tiles when prompted. This creates a project with uv, installs Stario, and copies the template. Start it:

cd tiles
uv run main.py

Open http://127.0.0.1:8000 - you should see a 5x5 grid you can paint. Open a second browser tab and watch cells update in real time.

Now let's understand how it works.
The Handler Signature ¶

Every handler in Stario has the exact same signature:

async def handler(c: Context, w: Writer) -> None:
    pass

Two arguments, always:

    Context (c) - everything about the incoming request: headers, query params, body, signals, and tracing.
    Writer (w) - how you send the response: HTML, SSE patches, redirects, status codes.

That's it. No return values, no decorators, no magic injection. If you've used FastAPI, you know the pain of Depends(), Request, Response, type-annotated parameters, and middleware that silently changes behavior. In Stario, every handler looks the same and works the same way.
One Handler, Three Patterns ¶

There's only one kind of handler in Stario. The signature is always the same - async def handler(c: Context, w: Writer) -> None. What changes is how you use c and w inside it. The Tiles app demonstrates the three most common patterns.

In frameworks like Starlette or FastAPI, each of these patterns requires a fundamentally different approach: different return types, different response classes, different decorators, different machinery. In Stario, it's just the same handler doing different things.
Serving a Page ¶

The simplest pattern. Read the request, send a response, done.

async def home(c: Context, w: Writer) -> None:
    user_id = str(uuid.uuid4())[:8]
    c["user_id"] = user_id
    w.html(home_view(user_id))

w.html() sends a full HTML page and closes the connection. You also have w.json(), w.text(), w.redirect(), w.empty() - all just methods on the same Writer.

In FastAPI, you'd need a response_class=HTMLResponse decorator, a return HTMLResponse(content=...), and a completely different function shape than a JSON endpoint. Here, the handler looks the same regardless of what kind of response you're sending.
Keeping a Connection Alive - Real-Time Streaming ¶

This is the heart of real-time. The client opens a connection, and the server keeps it alive, pushing updates as Server-Sent Events. Datastar receives these events and patches the DOM. It's the same handler - just a different way of using it.

async def subscribe(c: Context, w: Writer) -> None:
    signals = await c.signals(HomeSignals)
    if not signals.user_id:
        c("No user id", {"hint": "user had to change something manually"})
        w.redirect("/")
        return

    # Register user and notify everyone
    users.add(signals.user_id)
    relay.publish("join", signals.user_id)
    c("on_join", {"user_id": signals.user_id})
    c["user_id"] = signals.user_id

    # Send initial state
    w.patch(home_view(signals.user_id))
    c("onload patch")

    # Loop until client disconnects
    async for event, user_id in w.alive(relay.subscribe("*")):
        c("on_event", {"event": event, "user_id": user_id})
        w.patch(home_view(signals.user_id))

    # Cleanup - runs after disconnect
    users.discard(signals.user_id)
    relay.publish("leave", signals.user_id)
    c("on_leave", {"user_id": signals.user_id})

Same signature, same c and w. The difference is that instead of calling w.html() once and exiting, you call w.alive() to keep the connection open. It wraps an async iterator (like relay.subscribe()) and yields values until the client disconnects. When the client closes their browser tab, the loop exits cleanly - no exception, no special handling. Code after the loop is your cleanup hook.

w.patch() sends HTML fragments as SSE events. Datastar matches elements by id and merges them into the DOM. You re-render the whole view, but only changed parts update on screen.

Relay is an in-process pub/sub. relay.publish("click", user_id) pushes to all relay.subscribe("*") iterators. Each connected client's SSE loop receives the event and re-renders.

Compare what the same thing looks like in Starlette - you leave the handler world entirely and enter a different abstraction:

# Starlette - completely different pattern: generator function, different response class,
# manual disconnect polling, no cleanup hook
async def subscribe(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break  # Manual polling for disconnect
            data = await get_update()
            yield {"data": json.dumps(data)}
    return EventSourceResponse(event_generator())
# Where does cleanup go? You'd need a try/finally inside the generator,
# and hope the framework actually calls your cleanup code on disconnect.

In Stario, this is just a handler that calls w.alive(). Same signature, same c, same w. Nothing new to learn.
Responding Early, Working After - Actions ¶

The third common pattern handles button clicks, form submissions, and any request where you want to acknowledge receipt fast and do work after. Again - same handler.

async def click(c: Context, w: Writer) -> None:
    # Validate input
    signals = await c.signals(HomeSignals)
    if not signals.user_id or signals.user_id not in users:
        c("No user id or user not connected", {"user_id": signals.user_id})
        w.redirect("/")
        return

    cell_id_param = c.req.query.get("cellId")
    if cell_id_param is None:
        c("No cell id", {"hint": "pass cellId as query parameter"})
        w.redirect("/")
        return

    cell_id = int(cell_id_param)
    c["user_id"] = signals.user_id
    c["cell_id"] = cell_id

    # Respond immediately - client gets 204 No Content right now
    w.empty(204)

    # Everything below still runs after the response is sent
    user_color = color_for_user(signals.user_id)
    if board.get(cell_id) == user_color:
        board.pop(cell_id, None)
    else:
        board[cell_id] = user_color

    relay.publish("click", signals.user_id)

The critical insight: code after w.empty(204) still runs. The HTTP response is already sent, but the handler continues. The user gets an instant response, and the server does the work in the background - updating state, broadcasting to other clients via the Relay.

In FastAPI, this requires dedicated machinery - a BackgroundTasks parameter and a separate function:

# FastAPI - need BackgroundTasks, extra parameter, separate function
@app.post("/click")
async def click(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    background_tasks.add_task(process_click, data)
    return Response(status_code=204)

In Stario, you just keep writing code. The handler is the background task.
Why This Matters ¶

All three patterns - serving a page, streaming real-time updates, and fire-and-forget actions - use the same function signature. You don't need to learn different abstractions, import different response classes, or restructure your code when requirements change. A handler that starts as a simple page render can evolve into a streaming endpoint by adding a w.alive() loop. An action that used to return immediately can start doing background work by moving code below w.empty(). The handler just grows - it never has to become something else.
Signals - Client-Server State ¶

Datastar manages reactive state via signals. Signals are set on the client and automatically sent with every @get / @post request.

In the Tiles template, the home page initializes signals:

data.signals({"user_id": user_id}, ifmissing=True)

ifmissing=True means "set only if not already present" - this preserves state across SSE re-renders.

On the server, you parse signals with a dataclass schema:

@dataclass
class HomeSignals:
    user_id: str

async def subscribe(c: Context, w: Writer) -> None:
    signals = await c.signals(HomeSignals)
    # signals.user_id is typed, parsed, and validated

c.signals() extracts signals from the request (Datastar sends them automatically) and validates them against your dataclass. Bad data? You get clear errors, not silent failures.
Telemetry - Tracing Your Handlers ¶

Stario has built-in tracing that works through the Context object. Every request automatically gets a span, and you can add events, attributes, and child spans.
Recording Events - c() ¶

Call the context like a function to record an event:

c("on_join", {"user_id": signals.user_id})
c("cache.hit", {"key": "users:123"})
c(ValueError("invalid input"))  # Record exception (doesn't set error status)

Events are attached to the current span and show up in your tracer output.
Setting Attributes - c[] ¶

Use bracket syntax to set attributes on the current span:

c["user_id"] = signals.user_id
c["cell_id"] = cell_id
c["db.query"] = "SELECT * FROM users"

Attributes are key-value metadata that help you debug and monitor.
Child Spans - c.step() ¶

For operations you want to trace separately (like database queries), create a child span:

with c.step("db.query", {"sql": "SELECT ..."}) as s:
    c("cache.miss")        # Event on child span
    c["rows"] = 10         # Attribute on child span
    result = await db.execute(sql)
# Back to request span after the block

Inside a c.step() block, c() and c[] operate on the child span. Outside, they operate on the request span.
Choosing a Tracer ¶

# Pretty console output for development
tracer = RichTracer()

# Structured JSON logs for production
tracer = JsonTracer()

The Tiles template auto-selects based on environment:

if "--local" in sys.argv or sys.stdout.isatty():
    tracer = RichTracer()
else:
    tracer = JsonTracer()

Accessing the Request - c.req ¶

The request object is available at c.req and provides everything you need:

c.req.method          # "GET", "POST", etc.
c.req.path            # "/click"
c.req.query           # QueryParams object
c.req.headers         # Headers object
c.req.cookies         # {"session": "abc123"}
c.req.host            # "localhost"
await c.req.body()    # Read full body
await c.req.json()    # Parse body as JSON

Query params are accessed through the QueryParams object - .get() for the first value, .getlist() for all values of a key:

c.req.query.get("cellId")          # str | None
c.req.query.get("page", "1")       # str (with default)
c.req.query.getlist("tags")         # list[str]
"cellId" in c.req.query             # bool

Headers work the same way - .get() and .getlist() return decoded strings:

c.req.headers.get("Authorization")  # str | None
c.req.headers.getlist("Set-Cookie") # list[str]

The Full Picture - App Setup ¶

Looking at the bottom of main.py, the app is wired together explicitly:

async def main():
    if "--local" in sys.argv or sys.stdout.isatty():
        tracer = RichTracer()
        host, port, workers = "127.0.0.1", 8000, 1
    else:
        tracer = JsonTracer()
        host, port, workers = "0.0.0.0", 8000, 4

    with tracer:
        app = Stario(tracer)
        app.assets("/static", Path(__file__).parent / "static")
        app.get("/", home)
        app.get("/subscribe", subscribe)
        app.post("/click", click)
        await app.serve(host=host, port=port, workers=workers)

No hidden configuration files, no auto-discovery, no class-based views. Routes are registered explicitly, the server starts, and you can read the entire flow top to bottom.
What You've Learned ¶

    One handler signature: always async def handler(c: Context, w: Writer) -> None - the same for every use case
    Serving pages: w.html() sends a response and closes
    Real-time streaming: w.alive() keeps a connection open with automatic disconnect detection and cleanup
    Actions with background work: w.empty() responds immediately, code after it keeps running
    One handler grows - it never needs to become a different kind of thing when requirements change
    Signals: data.signals() on client, c.signals(Schema) on server
    Telemetry: c() for events, c[] for attributes, c.step() for child spans
    Request access: everything lives on c.req - QueryParams for query strings, Headers for headers (both return decoded strings)

Next Steps ¶

    Hello World from Scratch - Build a minimal app from an empty file, no template needed.
    Structuring Larger Apps - Routers, modules, and dependency injection for real projects.
    Reference: Writer - All response methods in detail.

Changing the world, one byte at a time
