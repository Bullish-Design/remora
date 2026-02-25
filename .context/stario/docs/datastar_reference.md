
stario.dev
Datastar
2–3 minutes
Datastar Reference ¶

Stario integrates with Datastar via data.* (attributes) and at.* (actions).
Reading Signals ¶

Signals are reactive state sent from the client.

# Raw dict
signals = await c.signals()
count = signals.get("count", 0)

# Typed with Dataclass
@dataclass
class Search:
    query: str

data = await c.signals(Search)
print(data.query)

Attributes (data.*) ¶

Helpers for data- attributes.
Helper 	Resulting Attribute 	Purpose
data.signals(dict) 	data-signals 	Initialize state
data.bind(key) 	data-bind-* 	Two-way binding
data.text(expr) 	data-text 	Reactive text
data.on(evt, act) 	data-on:* 	Event handler
data.show(expr) 	data-show 	Conditional visibility
data.init(act) 	data-init 	Run on mount
data.indicator(sig) 	data-indicator 	Loading indicator
data.effect(expr) 	data-effect 	Side effect
data.computed(dict) 	data-computed 	Derived state
Event Handlers ¶

# Simple expression
Button(data.on("click", "$count++"), "+1")

# Server action
Button(data.on("click", at.post("/inc")), "Add")

# Modifiers
Input(data.on("input", at.get("/search"), debounce=0.3))

Actions (at.*) ¶

Helpers for triggering server requests from events.

at.get("/path")
at.post("/path", include=["user"], selector="#output")
at.put("/path")
at.patch("/path")
at.delete("/path")

SSE Patterns ¶
Server Method 	Result
w.patch(Div({"id": "res"}, "OK")) 	Merges element into #res
w.sync({"count": 10}) 	Updates $count signal
w.navigate("/next") 	Soft-redirects browser
w.remove("#item-1") 	Removes element from DOM
Example: Inline Search ¶

async def search(c: Context, w: Writer):
    # 1. Read signals
    signals = await c.signals()
    query = signals.get("query", "")

    # 2. Patch DOM
    results = await db.find(query)
    w.patch(Div({"id": "results"}, 
        *[P(r.title) for r in results]
    ))

Changing the world, one byte at a time
