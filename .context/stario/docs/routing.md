
stario.dev
Routing
3–4 minutes
Routing Reference ¶

Routing maps HTTP methods and paths to handlers. Stario uses a predictable, order-based router.
Basic Usage ¶

app = Stario(tracer)

app.get("/", home)
app.post("/users", create_user)
app.get("/users/*", get_user)  # Catch-all

Route Types ¶
Type 	Pattern 	Match Example 	c.req.tail
Exact 	/users 	/users 	""
Catch-all 	/users/* 	/users/123/edit 	"123/edit"
Sub-Routers & Mounting ¶

Group related routes with Router and mount them at a prefix.

api = Router()
api.get("/users", list_users)
api.get("/users/*", get_user)

app.mount("/api/v1", api)
# Results in: /api/v1/users and /api/v1/users/*

Middleware ¶

Middleware wraps handlers and can be applied at the app, router, or route level.

# App-level (all routes)
app.use(logging_middleware)

# Router-level (all routes in this router)
api = Router()
api.use(auth_middleware)

# Per-route (right-to-left execution)
app.get("/admin", admin_page, auth_middleware, rate_limit)

Error Handlers ¶

Handle exceptions globally or by type.

def handle_404(c: Context, w: Writer, exc: HttpException):
    w.html(Div("Not Found"), status=404)

app.on_error(HttpException, handle_404)

Static Assets ¶

Serve fingerprinted assets with one line:

app.assets("/static", Path(__file__).parent / "static")

# Use in code
href = f"/static/{asset('css/style.css')}"

Host-Based Routing ¶

Route requests to different routers based on the Host header. This is useful for multi-tenant apps, API subdomains, or any setup where different hosts serve different content.

# Exact host match
api = Router()
api.get("/users", list_users)
api.post("/users", create_user)
app.host("api.example.com", api)

# Wildcard subdomain match
tenant = Router()
tenant.get("/dashboard", dashboard)
app.host("*.example.com", tenant)

How it works ¶
Pattern 	Match 	c.req.subhost
"api.example.com" 	Exact match only 	-
"*.example.com" 	Any subdomain 	Matched portion (e.g. "acme" for acme.example.com)

Precedence order:

    Exact hosts - O(1) lookup, checked first.
    Wildcard hosts - checked longest-suffix-first for most specific match.
    Fallback - routes registered directly on app handle unmatched hosts.

Multi-tenant example ¶

tenant = Router()

async def dashboard(c: Context, w: Writer) -> None:
    org = c.req.subhost  # "acme" for acme.myapp.com
    host = c.req.host    # "acme.myapp.com" (from the Host header)
    w.html(Div(f"Dashboard for {org}"))

tenant.get("/dashboard", dashboard)
app.host("*.myapp.com", tenant)

    Note: A bare "*" pattern is not allowed - use routes on the app directly as the fallback for unmatched hosts.

Matching Rules ¶

    Registration Order: Routes are matched in the order they were registered.
    Exact vs Catch-all: Exact paths are checked first.
    Longest Prefix: For nested routers, the longest matching prefix wins.

Changing the world, one byte at a time
