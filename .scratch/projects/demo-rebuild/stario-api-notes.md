# Stario API Notes — Demo Rebuild

Quick reference for the real Stario API (from .context/stario/).

## Imports
```python
from stario import Context, Writer, Stario, RichTracer, Relay, at, data
from stario.html import Div, H1, Body, Head, Html, Meta, Title, Script, Style, Button, Span, P, Pre, Code, Input, Form, Link, SafeString, render
from stario.relay import Relay
```

## HTML Elements
```python
# Dicts = attributes, everything else = children
Div({"class": "box", "id": "main"}, "Hello")
Div({"style": {"color": "red"}}, H1("Title"))
# Multiple attribute dicts merge
Div({"class": "a"}, {"id": "b"}, "Hi")
# None/False ignored
Div(H1("X"), None, P("Y"))
# Lists unpack
Ul(*[Li(u) for u in users])
```

## SafeString (for raw HTML/SVG)
```python
from stario.html import SafeString
Div(SafeString("<svg>...</svg>"))
```

## Writer Methods
```python
w.html(element)      # Full page response
w.json(data)         # JSON response
w.text(text)         # Plain text
w.patch(element)     # SSE DOM patch (element must have id)
w.sync(data)         # SSE signal update
w.empty(status=204)  # Empty response
w.redirect(url)      # Redirect
w.navigate(url)      # Client-side nav
w.remove(selector)   # Remove DOM element
w.execute(js)        # Execute JS
```

## SSE / Long-lived connections
```python
async for subject, data in w.alive(relay.subscribe("pattern.*")):
    w.patch(render_something())
# cleanup runs here after disconnect
```

## Relay
```python
relay = Relay()
relay.publish("subject.name", data)
# Subscribe yields (subject, data) tuples
async for subject, payload in relay.subscribe("graph.*"):
    ...
```

## Datastar Helpers
```python
data.signals({"key": "val"})          # data-signals
data.signals({...}, ifmissing=True)   # only set if not already set
data.bind("field")                    # data-bind
data.text("$count")                   # data-text
data.on("click", "$count++")          # data-on:click
data.on("click", at.get("/path"))     # data-on:click with server action
data.on("input", at.get("/s"), debounce=0.3)
data.show("$visible")                 # data-show
data.init(at.get("/subscribe"))       # data-init (run on mount)
data.indicator("sig")                 # loading indicator
data.attr({"disabled": "!$msg"})      # reactive attributes
at.get("/path")                       # server GET action
at.post("/path")                      # server POST action
```

## App Setup
```python
async def main():
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", handler)
        app.get("/subscribe", subscribe_handler)
        app.post("/send", send_handler)
        app.assets("/static", Path("static"))
        await app.serve(host="127.0.0.1", port=8000)
```

## Handler Patterns
```python
# Simple handler
async def home(c: Context, w: Writer) -> None:
    w.html(Div("Hello"))

# Closure-based DI (Go-style)
def make_handler(db, relay):
    async def handler(c: Context, w: Writer) -> None:
        ...
    return handler

# Signal parsing
@dataclass
class MySignals:
    field: str = ""

async def handler(c: Context, w: Writer) -> None:
    signals = await c.signals(MySignals)

# Tracing/logging
c("event_name", {"key": "val"})
```

## SVG in Stario
SVG elements are NOT built-in. Use SafeString for raw SVG, or build helpers.
The plan's approach of Tag("svg") etc won't work — need to build SVG as strings
and wrap in SafeString, or create custom element constructors.

## Key Differences from Plan
1. Plan used: `Tag("div")` → callable `Div(class_="x")("child")` 
   Real: `Div({"class": "x"}, "child")`
2. Plan assumed: `stario.html.core.Tag` for SVG
   Real: Build SVG strings + SafeString
3. Plan used: `app.on("startup")` for background tasks
   Real: Need to use asyncio.create_task before app.serve() or within a handler
4. Plan used: `app.serve()` (sync)
   Real: `await app.serve()` (async)
