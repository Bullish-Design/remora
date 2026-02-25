
stario.dev
Exceptions
~2 minutes

Stario uses exceptions to handle HTTP errors and domain-specific failures.
HttpException ¶

Raise HttpException to stop execution and return an HTTP error.

from stario import HttpException

async def get_user(c: Context, w: Writer):
    user = await db.find(c.req.tail)
    if not user:
        raise HttpException(404, "User not found")
    w.json(user)

Argument 	Default 	Description
status 	500 	HTTP status code
detail 	"" 	Error message for the client
headers 	None 	Optional dict of extra headers
Global Error Handlers ¶

Register custom handlers to catch exceptions and return beautiful error pages or JSON.

def handle_404(c: Context, w: Writer, exc: HttpException):
    w.html(Div(H1("Oops!"), P(exc.detail)), status=404)

def handle_generic(c: Context, w: Writer, exc: Exception):
    # Log the real error to your tracer
    c["error"] = str(exc)
    w.json({"error": "Internal Server Error"}, status=500)

app.on_error(HttpException, handle_404)
app.on_error(Exception, handle_generic)

ClientDisconnected ¶

Raised automatically when a client closes the connection during an SSE stream. If you use w.alive(), this is handled for you and the loop simply exits.

async def stream(c: Context, w: Writer):
    async for msg in w.alive(relay.subscribe("chat")):
        w.patch(Div(msg))
    # Disconnect happens -> loop ends -> cleanup runs here

StarioError ¶

Internal framework errors (e.g., misconfiguration). These usually include help_text to guide you toward a fix.

Changing the world, one byte at a time
