
stario.dev
Structuring Apps
17–21 minutes
Structuring Larger Applications ¶

A single main.py works fine for small apps. But when your project grows - more routes, a database, multiple features - you need structure. This tutorial shows how to organize a Stario application using routers, modules, and closure-based dependency injection.

We'll build a simplified version of the Chat example that demonstrates all these patterns. You can install the full example with uvx stario@latest init and pick chat.
The Problem with a Single File ¶

In a small app, everything lives in main.py:

# This works for 100 lines. At 500 lines, it's painful.
board = {}
users = set()
relay = Relay()

async def home(c, w): ...
async def subscribe(c, w): ...
async def click(c, w): ...

async def main():
    app = Stario(tracer)
    app.get("/", home)
    app.get("/subscribe", subscribe)
    app.post("/click", click)
    await app.serve()

The problems: handlers reach for module-level globals, dependencies are implicit, and you can't test handlers without running the whole app.
Project Structure ¶

Here's how a real Stario app should look:

my-chat/
├── main.py              # Entry point - wires everything together
└── app/
    ├── __init__.py
    ├── state.py          # Data models (dataclasses)
    ├── db.py             # Database layer
    ├── views.py          # HTML view functions
    ├── handlers.py       # Request handlers
    └── static/
        ├── css/style.css
        └── js/datastar.js

Each file has a single responsibility. Let's build it piece by piece.
Step 1: Data Models - app/state.py ¶

Start with your data shapes. These are plain dataclasses - no ORM, no magic:

# app/state.py
from dataclasses import dataclass

@dataclass
class Message:
    id: str
    user_id: str
    username: str
    text: str
    timestamp: float

@dataclass
class User:
    id: str
    username: str
    color: str
    typing: bool = False

Keep this file pure - no imports from stario, no side effects. Just data definitions and small helpers.
Step 2: Database Layer - app/db.py ¶

The database module wraps your persistence. Here's a simple SQLite wrapper:

# app/db.py
import sqlite3
import threading
from dataclasses import dataclass, field
from contextlib import contextmanager
from .state import Message, User

@dataclass
class Database:
    db_path: str
    _local: threading.local = field(default_factory=threading.local)

    def __post_init__(self):
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _init_tables(self):
        with self._cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    color TEXT NOT NULL,
                    typing INTEGER NOT NULL DEFAULT 0
                )
            """)

    def add_message(self, msg: Message) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO messages (id, user_id, username, text, timestamp) VALUES (?, ?, ?, ?, ?)",
                (msg.id, msg.user_id, msg.username, msg.text, msg.timestamp),
            )

    def get_messages(self, limit: int = 50) -> list[Message]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM messages ORDER BY timestamp ASC LIMIT ?", (limit,))
            return [Message(**dict(row)) for row in cur.fetchall()]

    def add_user(self, user: User) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO users (id, username, color, typing) VALUES (?, ?, ?, ?)",
                (user.id, user.username, user.color, int(user.typing)),
            )

    def remove_user(self, user_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def get_users(self) -> dict[str, User]:
        with self._cursor() as cur:
            cur.execute("SELECT id, username, color, typing FROM users")
            return {
                row["id"]: User(id=row["id"], username=row["username"], color=row["color"], typing=bool(row["typing"]))
                for row in cur.fetchall()
            }

    def user_exists(self, user_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = ?", (user_id,))
            return cur.fetchone() is not None

def create_database(is_dev: bool = True) -> Database:
    return Database(db_path=":memory:" if is_dev else "chat.db")

Key points:

    Thread-local connections - SQLite isn't thread-safe, so each worker thread gets its own connection.
    create_database() factory - returns the right configuration for dev vs production.
    No stario imports - this module knows nothing about HTTP. You can test it independently.

Step 3: Views - app/views.py ¶

Views are pure functions: data in, HTML out. No request handling, no side effects.

# app/views.py
from stario import asset, at, data
from stario.html import (
    Body, Button, Div, Form, Head, Html,
    Input, Link, Meta, Script, Span, Title,
)
from .state import Message, User

def page(*children):
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Title("Chat - Stario"),
            Link({"rel": "stylesheet", "href": "/static/" + asset("css/style.css")}),
            Script({"type": "module", "src": "/static/" + asset("js/datastar.js")}),
        ),
        Body(*children),
    )

def message_view(msg: Message, current_user_id: str):
    is_own = msg.user_id == current_user_id
    return Div(
        {"class": "message own" if is_own else "message"},
        Span({"class": "username"}, msg.username),
        Div({"class": "message-text"}, msg.text),
    )

def messages_view(current_user_id: str, messages: list[Message]):
    if not messages:
        return Div({"id": "messages", "class": "messages empty"}, "No messages yet.")
    return Div(
        {"id": "messages", "class": "messages"},
        *[message_view(msg, current_user_id) for msg in messages],
    )

def chat_view(user_id: str, username: str, *, messages: list[Message], users: dict[str, User]):
    return page(
        Div(
            {"class": "chat-container"},
            data.signals({"user_id": user_id, "username": username, "message": ""}, ifmissing=True),
            data.init(at.get("/subscribe")),
            Div({"class": "chat-header"}, Span(f"{len(users)} online")),
            messages_view(user_id, messages),
            Form(
                {"id": "input-form"},
                data.on("submit", "evt.preventDefault()"),
                Input(
                    {"type": "text", "placeholder": "Type a message..."},
                    data.bind("message"),
                    data.on("keydown", """
                        if (evt.key === 'Enter' && $message.trim()) {
                            evt.preventDefault();
                            @post('/send');
                            $message = '';
                        }
                    """),
                ),
            ),
        ),
    )

Views receive all data as parameters. They don't access globals, databases, or request objects. This means:

    You can call them from tests with fake data.
    They're deterministic - same input, same output.
    You can build a component library without touching your HTTP layer.

Step 4: Handlers - app/handlers.py ¶

Here's the core pattern: handlers that need dependencies are returned by factory functions.

# app/handlers.py
import time
import uuid
from dataclasses import dataclass

from stario import Context, Relay, Writer
from .db import Database
from .state import Message, User
from .views import chat_view

@dataclass
class ChatSignals:
    user_id: str = ""
    username: str = ""
    message: str = ""

# Simple handler - no dependencies needed
async def home(c: Context, w: Writer) -> None:
    user_id = str(uuid.uuid4())[:8]
    username = f"User{user_id[:4]}"
    w.html(chat_view(user_id, username, messages=[], users={}))

# Factory function - returns a handler with db and relay captured
def subscribe(db: Database, relay: Relay[str]):
    async def handler(c: Context, w: Writer) -> None:
        signals = await c.signals(ChatSignals)
        if not signals.user_id:
            w.redirect("/")
            return

        user = User(id=signals.user_id, username=signals.username, color="#3498db")
        db.add_user(user)
        c("User connected", {"user_id": signals.user_id})
        relay.publish("update", "join")

        # Send initial state
        w.patch(chat_view(
            signals.user_id, signals.username,
            messages=db.get_messages(), users=db.get_users(),
        ))

        # Stream updates until disconnect
        async for _, event_type in w.alive(relay.subscribe("update")):
            c("event", {"type": event_type})
            w.patch(chat_view(
                signals.user_id, signals.username,
                messages=db.get_messages(), users=db.get_users(),
            ))

        # Cleanup
        db.remove_user(signals.user_id)
        relay.publish("update", "leave")
        c("User disconnected", {"user_id": signals.user_id})

    return handler

def send_message(db: Database, relay: Relay[str]):
    async def handler(c: Context, w: Writer) -> None:
        signals = await c.signals(ChatSignals)
        if not signals.user_id or not db.user_exists(signals.user_id):
            w.redirect("/")
            return

        text = signals.message.strip()
        if not text:
            w.empty(204)
            return

        msg = Message(
            id=str(uuid.uuid4())[:8],
            user_id=signals.user_id,
            username=signals.username,
            text=text,
            timestamp=time.time(),
        )
        db.add_message(msg)
        c("Message sent", {"user_id": signals.user_id, "text": text[:50]})

        # Respond, then broadcast
        w.empty(204)
        relay.publish("update", "message")

    return handler

Why Factory Functions? ¶

This is Go-style dependency injection. Instead of a DI framework or @inject decorators, you use plain closures:

# The factory captures dependencies in a closure
def subscribe(db: Database, relay: Relay[str]):
    async def handler(c: Context, w: Writer) -> None:
        # db and relay are available here - captured from outer scope
        users = db.get_users()
        relay.publish("update", "join")
    return handler

Benefits over other approaches:
Approach 	Stario (closures) 	FastAPI (Depends) 	Flask (globals)
Explicit deps 	Yes - visible in factory signature 	Partly - hidden in type annotations 	No - import globals
Easy to test 	Yes - pass mocks to factory 	Possible but verbose - override dependencies 	Hard - need app context
IDE support 	Full - just functions 	Partial - magic parameter injection 	Full but brittle
Learning curve 	None - it's just Python 	Medium - learn Depends() system 	Low but hidden coupling

For handlers that don't need external dependencies (like home), keep them as regular functions. Only use factories when you need to inject something.
Step 5: Wire It Together - main.py ¶

The entry point creates all dependencies and passes them to handler factories:

# main.py
import asyncio
import sys
from pathlib import Path

from app.db import create_database
from app.handlers import home, send_message, subscribe
from stario import JsonTracer, Relay, RichTracer, Stario

async def main():
    is_dev = "--local" in sys.argv or sys.stdout.isatty()

    if is_dev:
        tracer = RichTracer()
        host, port, workers = "127.0.0.1", 8000, 1
    else:
        tracer = JsonTracer()
        host, port, workers = "0.0.0.0", 8000, 4

    # Create dependencies
    db = create_database(is_dev=is_dev)
    relay: Relay[str] = Relay()

    with tracer:
        app = Stario(tracer)
        app.assets("/static", Path(__file__).parent / "app" / "static")

        # Register routes - factories are called here with dependencies
        app.get("/", home)
        app.get("/subscribe", subscribe(db, relay))
        app.post("/send", send_message(db, relay))

        await app.serve(host=host, port=port, workers=workers)

if __name__ == "__main__":
    asyncio.run(main())

Notice how main.py is the composition root - it's the only place that knows about all the pieces. Handlers don't import the database directly; they receive it. Views don't know about the Relay; they just render data.
Using Sub-Routers ¶

As your app grows further, you'll want to group related routes. Stario's Router class lets you create modular route groups:

from stario import Router

def chat_router(db: Database, relay: Relay[str]) -> Router:
    """Creates the chat route group with dependencies injected."""
    r = Router()

    r.get("/", home)
    r.get("/subscribe", subscribe(db, relay))
    r.post("/send", send_message(db, relay))

    return r

def admin_router(db: Database) -> Router:
    """Creates admin routes - could be a separate module entirely."""
    r = Router()

    async def stats(c: Context, w: Writer) -> None:
        users = db.get_users()
        messages = db.get_messages()
        w.json({"users": len(users), "messages": len(messages)})

    r.get("/stats", stats)
    return r

Then mount them in main.py:

app = Stario(tracer)
app.mount("/chat", chat_router(db, relay))
app.mount("/admin", admin_router(db))

Routes become /chat/subscribe, /admin/stats, etc. Each router is self-contained - you can develop and test them independently.
Router Factories as Modules ¶

For even larger apps, each router factory lives in its own file:

app/
├── chat/
│   ├── __init__.py      # Exports chat_router()
│   ├── handlers.py
│   └── views.py
├── admin/
│   ├── __init__.py      # Exports admin_router()
│   └── handlers.py
└── shared/
    ├── db.py
    └── state.py

Each __init__.py exports a router factory:

# app/chat/__init__.py
from stario import Router, Relay
from ..shared.db import Database
from .handlers import home, subscribe, send_message

def chat_router(db: Database, relay: Relay[str]) -> Router:
    r = Router()
    r.get("/", home)
    r.get("/subscribe", subscribe(db, relay))
    r.post("/send", send_message(db, relay))
    return r

And main.py just composes the top-level app:

from app.chat import chat_router
from app.admin import admin_router

app = Stario(tracer)
app.mount("/", chat_router(db, relay))
app.mount("/admin", admin_router(db))

Middleware ¶

Routers support middleware - functions that wrap handlers:

async def auth_middleware(c: Context, w: Writer, next) -> None:
    token = c.req.cookies.get("session")
    if not token:
        w.redirect("/login")
        return
    c.state["user"] = await validate_token(token)
    await next(c, w)

# Apply to all routes in a router
admin = Router()
admin.use(auth_middleware)
admin.get("/stats", stats_handler)

# Or apply to specific routes
app.get("/admin/danger", danger_handler, auth_middleware)

Middleware has the same signature as a handler, plus a next parameter. Call next(c, w) to continue to the handler (or next middleware). Skip calling next to short-circuit - useful for auth, rate limiting, etc.
Testing ¶

The closure pattern makes testing straightforward:

# test_handlers.py
from app.handlers import subscribe, send_message
from app.db import Database
from stario import Relay

def test_subscribe():
    # Create test dependencies
    db = Database(db_path=":memory:")
    relay = Relay()

    # Get the handler
    handler = subscribe(db, relay)

    # handler is a regular async function - test it however you want
    # (mock Context and Writer, or use Stario's test client)

No app context needed, no global state to reset, no monkey-patching. You pass in mocks and call the function.
Summary: Rules of Thumb ¶

    One file until it hurts - don't split prematurely. Start in main.py, extract when a file hits ~200 lines.
    Views are pure - data in, HTML out. No database calls, no request access.
    Handlers get dependencies via closures - if it needs a database, make a factory function.
    main.py is the composition root - it creates everything and wires it together.
    Routers for grouping - use mount() to organize routes by feature.
    No globals - if you're reaching for a module-level db = ..., use a factory instead.

What You've Learned ¶

    How to structure a multi-file Stario application
    The closure/factory pattern for dependency injection
    Creating and mounting sub-routers
    Applying middleware to routers and individual routes
    How to keep views pure and handlers testable

Next Steps ¶

    Tiles Walkthrough - One handler, three usage patterns, plus telemetry.
    Hello World from Scratch - Build the simplest possible app step by step.
    How-to: Containerization - Deploy your structured app with Docker.
    Reference: Routing - Complete routing API including host-based routing and catch-all paths.

Changing the world, one byte at a time
