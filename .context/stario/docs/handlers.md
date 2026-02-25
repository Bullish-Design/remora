
stario.dev
Handlers
2–3 minutes

Handlers are the building blocks of Stario. They are async functions with a fixed signature:

async def handler(c: Context, w: Writer) -> None:
    pass

    Context (c): Read request data (query, body, signals, tracing).
    Writer (w): Send response data (HTML, JSON, SSE patches).

Reading Request Data ¶

Access all request info via c.req.
Data Type 	Access Pattern 	Returns 	Example
Query 	c.req.query.get("key") 	str \| None 	?q=search
Query (all) 	c.req.query.getlist("key") 	list[str] 	?tag=a&tag=b
Path Tail 	c.req.tail 	str 	/* match
Headers 	c.req.headers.get("key") 	str \| None 	User-Agent
Cookies 	c.req.cookies.get("key") 	str \| None 	session
Body (JSON) 	await c.req.json() 	Any 	POST data
Signals 	await c.signals(Schema?) 	T \| dict 	Datastar state
Dependency Injection (Go-Style) ¶

Stario avoids "magic" injection. Use closures to pass dependencies like databases or services.

def make_user_handler(db: Database):
    async def get_user(c: Context, w: Writer):
        user = await db.find(c.req.tail)
        w.json(user)
    return get_user

# Usage
app.get("/users/*", make_user_handler(my_db))

Connection Lifecycle ¶

Use w.alive() to keep handlers running for long-lived SSE connections.

async def stream(c: Context, w: Writer):
    # Sends initial HTML
    w.html(Div("Connecting..."))

    # Loops until client disconnects
    async for msg in w.alive(relay.subscribe("chat")):
        w.patch(Div({"id": "msg"}, msg))

    # Cleanup runs automatically here
    logger.info("Client disconnected")

Error Handling ¶

Raise HttpException to trigger error handlers.

from stario import HttpException

async def handler(c: Context, w: Writer):
    if not authorized:
        raise HttpException(401, "Unauthorized")

Changing the world, one byte at a time
