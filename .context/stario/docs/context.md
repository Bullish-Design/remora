
stario.dev
Context
4–5 minutes
Context Reference ¶

The Context (c) provides a unified interface for request data, Datastar signals, and telemetry.
Request Data (c.req) ¶
Property 	Type 	Description 	Example
.method 	str 	HTTP method 	"GET", "POST"
.path 	str 	Request path 	"/api/v1/users"
.query 	QueryParams 	Parsed query string 	c.req.query.get("q")
.tail 	str 	Path tail for /* 	c.req.tail
.headers 	Headers 	HTTP headers 	c.req.headers.get("X-ID")
.cookies 	dict[str, str] 	Cookies 	c.req.cookies.get("sid")
Query Parameters ¶

c.req.query returns a QueryParams object with consistent access:

c.req.query.get("page")           # First value → str | None
c.req.query.get("page", "1")      # With default → str
c.req.query.getlist("tags")        # All values → list[str]
"page" in c.req.query              # Membership check → bool
len(c.req.query)                   # Number of unique keys

Why get() and getlist()? Query strings can have repeated keys — ?tags=a&tags=b is valid HTTP. Internally, all values are stored as lists keyed by parameter name. .get() returns the first value for convenience (the common case for single-valued params like page or id). .getlist() returns all values for that key, which is what you want for multi-valued params like checkboxes or tag filters.

# /search?tags=python&tags=async&page=2
c.req.query.get("tags")          # "python"  (first value)
c.req.query.getlist("tags")      # ["python", "async"]  (all values)
c.req.query.get("page")          # "2"
c.req.query.getlist("page")      # ["2"]  (always a list)
c.req.query.get("missing")       # None
c.req.query.getlist("missing")   # []

c.req.headers returns a Headers object. .get() and .getlist() return decoded strings:

c.req.headers.get("Authorization")      # First value → str | None
c.req.headers.get("Accept", "text/html") # With default → str
c.req.headers.getlist("Set-Cookie")      # All values → list[str]
"Content-Type" in c.req.headers          # Membership check → bool

Headers follow the same pattern as query parameters — HTTP allows multiple values for the same header name. When a header appears once, it's stored as a single bytes value internally. When a second value is added (via .add()), the storage promotes to a list[bytes]. .get() returns the first value (decoded as a string), while .getlist() returns all of them. Header names are case-insensitive — they're normalized to lowercase bytes internally.

# Request with: Accept-Language: en, Accept-Language: fr
c.req.headers.get("Accept-Language")      # "en"  (first value)
c.req.headers.getlist("Accept-Language")   # ["en", "fr"]

Body Access ¶

    await c.req.json(): Parses body as JSON.
    await c.req.form(): Parses multipart or url-encoded forms.
    await c.req.body(): Returns raw bytes.

Datastar Signals ¶

Signals are synced reactive state from the client.

# 1. As a dictionary
signals = await c.signals()

# 2. As a typed Dataclass
@dataclass
class Filters:
    query: str
    page: int = 1

data = await c.signals(Filters)

Tracing & Telemetry ¶

Stario uses trace-based logging. Use c.span and c.step to observe performance.
Spans & Steps ¶

# Set attributes on the request span
c["user_id"] = 42

# Create a child span for an operation
with c.step("db.query", {"table": "users"}) as s:
    res = await db.fetch()
    s["count"] = len(res)

Events ¶

Record specific moments in time:

c("user.logged_in")
c("cache.miss", {"key": "..."})

Custom State ¶

Store handler-specific data in c.state (common in middleware):

def auth_middleware(next):
    async def h(c, w):
        c.state["user"] = await get_user(c)
        await next(c, w)
    return h

Changing the world, one byte at a time
