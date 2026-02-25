
stario.dev
Hello World from Scratch ¶
12–15 minutes

This tutorial builds a minimal Stario app from an empty file. No templates, no scaffolding - just you and a blank main.py. By the end, you'll have a reactive counter with server interaction, and you'll understand every line.

    Quick start: If you just want the finished code, run uvx stario@latest init and pick hello-world. This tutorial builds the same app step by step.

Prerequisites ¶

    Python 3.14+ (Stario v2 requirement)
    uv package manager - install from docs.astral.sh/uv

Step 1: Create the Project ¶

uv init --app hello-world
cd hello-world
uv add stario

This creates a bare Python project with a main.py file. Let's replace its contents.
Step 2: The Minimal App ¶

Open main.py and replace it with the absolute minimum:

import asyncio
from stario import Context, Writer, Stario, RichTracer

async def home(c: Context, w: Writer) -> None:
    w.text("Hello, world!")

async def main():
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", home)
        await app.serve()

if __name__ == "__main__":
    asyncio.run(main())

Run it:

uv run main.py

Open http://127.0.0.1:8000 - you should see "Hello, world!" in plain text.

Let's break down what's here:

    RichTracer - pretty console output. Every request shows up in your terminal with timing, status, and any events you log.
    Stario(tracer) - creates the app. The tracer is the only required argument.
    app.get("/", home) - registers a GET route. No decorators.
    app.serve() - starts the HTTP server on 127.0.0.1:8000.

Step 3: Serve HTML ¶

Plain text isn't very useful. Let's return HTML using Stario's element helpers:

import asyncio
from stario import Context, Writer, Stario, RichTracer
from stario.html import H1, Body, Div, Head, Html, Meta, Title

async def home(c: Context, w: Writer) -> None:
    w.html(
        Html(
            {"lang": "en"},
            Head(
                Meta({"charset": "UTF-8"}),
                Title("Hello World"),
            ),
            Body(
                {"style": {
                    "font-family": "system-ui",
                    "padding": "2rem",
                    "max-width": "600px",
                    "margin": "0 auto",
                }},
                H1("Hello, Stario!"),
                Div("This is server-rendered HTML."),
            ),
        )
    )

async def main():
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", home)
        await app.serve()

if __name__ == "__main__":
    asyncio.run(main())

HTML elements are function calls. Dicts become attributes, everything else becomes children in order. style accepts a dict - stario.html converts it automatically:

Div({"class": "box", "style": {"color": "red"}}, "hello ", Span("world"))

<div class="box" style="color: red">hello <span>world</span></div>

w.html() sends a full page response and closes the connection.
Step 4: Add Datastar for Reactivity ¶

Now let's make it interactive. Datastar is a tiny client-side library that gives you reactive signals and server communication - no React, no build step.

First, we need the Datastar script. For this tutorial, we'll load it from a CDN:

import asyncio
from stario import Context, Writer, Stario, RichTracer, data
from stario.html import H1, Body, Button, Div, Head, Html, Meta, Script, Title

def page(*children):
    """Base page with Datastar loaded."""
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Title("Hello World"),
            Script({
                "type": "module",
                "src": "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
            }),
        ),
        Body(
            {"style": {
                "font-family": "system-ui",
                "padding": "2rem",
                "max-width": "600px",
                "margin": "0 auto",
            }},
            *children,
        ),
    )

async def home(c: Context, w: Writer) -> None:
    w.html(
        page(
            Div(
                data.signals({"count": 0}),
                H1("Counter"),
                Div(
                    {"style": {"display": "flex", "align-items": "center", "gap": "1rem"}},
                    Button(
                        {"style": {"padding": "0.5rem 1rem", "font-size": "1.25rem", "cursor": "pointer"}},
                        data.on("click", "$count--"),
                        "-",
                    ),
                    Div(
                        {"style": {"font-size": "2rem", "font-weight": "bold", "min-width": "3rem", "text-align": "center"}},
                        data.text("$count"),
                    ),
                    Button(
                        {"style": {"padding": "0.5rem 1rem", "font-size": "1.25rem", "cursor": "pointer"}},
                        data.on("click", "$count++"),
                        "+",
                    ),
                ),
            ),
        )
    )

async def main():
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", home)
        await app.serve()

if __name__ == "__main__":
    asyncio.run(main())

Refresh the page. You now have a working counter - click + and - to change the value. All client-side, no server round-trip.

Here's what the Datastar helpers do:

    data.signals({"count": 0}) - initializes a reactive signal called count with value 0. This becomes data-signals-count="0" in the HTML.
    data.text("$count") - binds the element's text content to the $count signal. Updates automatically when the signal changes.
    data.on("click", "$count++") - runs JavaScript when clicked. $count is a reactive reference to the signal.

Step 5: Add Server Interaction ¶

Client-side reactivity is nice, but the real power is server communication. Let's add a "Server +1" button that sends the current count to the server and gets back an incremented value.

import asyncio
from dataclasses import dataclass
from stario import Context, Writer, Stario, RichTracer, at, data
from stario.html import H1, Body, Button, Div, Head, Html, Meta, P, Script, Title

def page(*children):
    """Base page with Datastar loaded."""
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Title("Hello World"),
            Script({
                "type": "module",
                "src": "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
            }),
        ),
        Body(
            {"style": {
                "font-family": "system-ui",
                "padding": "2rem",
                "max-width": "600px",
                "margin": "0 auto",
            }},
            *children,
        ),
    )

@dataclass
class HomeSignals:
    count: int = 0

async def home(c: Context, w: Writer) -> None:
    w.html(
        page(
            Div(
                data.signals({"count": 0}),
                H1("Hello, Stario!"),
                P({"style": "color: #666"}, "A minimal counter with server interaction."),
                Div(
                    {"style": {"display": "flex", "align-items": "center", "gap": "1rem"}},
                    Button(
                        {"style": {"padding": "0.5rem 1rem", "font-size": "1.25rem", "cursor": "pointer"}},
                        data.on("click", "$count--"),
                        "-",
                    ),
                    Div(
                        {"id": "count", "style": {"font-size": "2rem", "font-weight": "bold", "min-width": "3rem", "text-align": "center"}},
                        data.text("$count"),
                    ),
                    Button(
                        {"style": {"padding": "0.5rem 1rem", "font-size": "1.25rem", "cursor": "pointer"}},
                        data.on("click", "$count++"),
                        "+",
                    ),
                ),
                P(
                    {"style": {"margin-top": "2rem", "color": "#666"}},
                    "Or fetch from server: ",
                    Button(
                        {"style": {"padding": "0.25rem 0.75rem", "cursor": "pointer"}},
                        data.on("click", at.get("/increment")),
                        "Server +1",
                    ),
                ),
            ),
        )
    )

async def increment(c: Context, w: Writer) -> None:
    signals = await c.signals(HomeSignals)
    c("increment", {"from": signals.count})
    signals.count += 1
    w.sync(signals)

async def main():
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", home)
        app.get("/increment", increment)
        await app.serve()

if __name__ == "__main__":
    asyncio.run(main())

Click "Server +1" and watch your terminal - the RichTracer shows the request, the "increment" event you logged, and the response.

Here's the new pieces:
The at Helper ¶

data.on("click", at.get("/increment"))

at.get("/increment") generates Datastar's @get('/increment') syntax. When clicked, Datastar sends a GET request to /increment, automatically including all current signals in the request. The server gets the current count without you manually serializing anything.
Parsing Signals on the Server ¶

@dataclass
class HomeSignals:
    count: int = 0

async def increment(c: Context, w: Writer) -> None:
    signals = await c.signals(HomeSignals)

c.signals(HomeSignals) parses the incoming signals into a typed dataclass. You get validation for free - if the client sends a string where you expect an int, you'll know.
Syncing State Back ¶

signals.count += 1
w.sync(signals)

w.sync() sends an SSE event that updates the client's signals. Datastar receives it and updates any bound elements (like the data.text("$count") display). The round-trip: client sends signals, server modifies them, server sends them back, client updates.
The Complete App ¶

Here's the final main.py - 50 lines for a reactive app with server interaction:

import asyncio
from dataclasses import dataclass
from stario import Context, Writer, Stario, RichTracer, at, data
from stario.html import H1, Body, Button, Div, Head, Html, Meta, P, Script, Title

def page(*children):
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Title("Hello World"),
            Script({
                "type": "module",
                "src": "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
            }),
        ),
        Body(
            {"style": {"font-family": "system-ui", "padding": "2rem", "max-width": "600px", "margin": "0 auto"}},
            *children,
        ),
    )

@dataclass
class HomeSignals:
    count: int = 0

async def home(c: Context, w: Writer) -> None:
    w.html(
        page(
            Div(
                data.signals({"count": 0}),
                H1("Hello, Stario!"),
                Div(
                    {"style": {"display": "flex", "align-items": "center", "gap": "1rem"}},
                    Button({"style": {"padding": "0.5rem 1rem", "font-size": "1.25rem", "cursor": "pointer"}}, data.on("click", "$count--"), "-"),
                    Div({"style": {"font-size": "2rem", "font-weight": "bold", "min-width": "3rem", "text-align": "center"}}, data.text("$count")),
                    Button({"style": {"padding": "0.5rem 1rem", "font-size": "1.25rem", "cursor": "pointer"}}, data.on("click", "$count++"), "+"),
                ),
                P(
                    {"style": {"margin-top": "2rem", "color": "#666"}},
                    "Or fetch from server: ",
                    Button({"style": {"padding": "0.25rem 0.75rem", "cursor": "pointer"}}, data.on("click", at.get("/increment")), "Server +1"),
                ),
            ),
        )
    )

async def increment(c: Context, w: Writer) -> None:
    signals = await c.signals(HomeSignals)
    c("increment", {"from": signals.count})
    signals.count += 1
    w.sync(signals)

async def main():
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", home)
        app.get("/increment", increment)
        await app.serve()

if __name__ == "__main__":
    asyncio.run(main())

What You've Learned ¶

    How to create a Stario project from scratch with uv
    The w.text() / w.html() response methods
    Stario's HTML element helpers (Div, H1, Button, etc.)
    Datastar signals for client-side reactivity (data.signals, data.text, data.on)
    Server communication with at.get() and c.signals()
    Syncing state back to the client with w.sync()

Next Steps ¶

    Tiles Walkthrough - Explore SSE streaming, w.alive(), and real-time multi-user patterns.
    Structuring Larger Apps - Routers, modules, and dependency injection for real projects.
    Reference: Server - Server configuration, workers, and graceful shutdown.

Changing the world, one byte at a time
