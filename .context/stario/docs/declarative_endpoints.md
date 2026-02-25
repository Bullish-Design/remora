
stario.dev
Declarative Endpoints
2–3 minutes
Explicit Input, Explicit Output ¶

Stario handlers prioritize visibility and predictability. Every handler receives exactly two parameters:

async def handler(c: Context, w: Writer) -> None:
    pass

    Context (c): Everything the handler needs (Input).
    Writer (w): Everything the handler does (Output).

The Closure Pattern ¶

Instead of complex dependency injection frameworks or hidden globals, Stario uses standard Python closures.

def make_handlers(db: Database, mailer: Mailer):

    async def create_user(c: Context, w: Writer):
        data = await c.req.json()
        user = await db.save(data)
        await mailer.send_welcome(user)
        w.json(user, status=201)

    return create_user

Why Closures? ¶

    Dependencies are Visible: Looking at the make_handlers signature tells you exactly what the handlers require to function.
    Testing is Trivial: Pass mock objects directly into the factory function. No DI container setup required.
    No Magic: There are no decorators injecting hidden state or performing behind-the-scenes resolution.
    Natural Scopes: Application-level services are closed over; request-level state stays inside the handler.

Explicit vs Implicit ¶
Feature 	Traditional Frameworks (Implicit) 	Stario (Explicit)
Request Data 	Ambient request object 	Passed as Context
Response 	return a dict or string 	Call Writer methods
Dependencies 	@inject or global imports 	Closed over via factory
Side Effects 	Hidden in middleware 	Visible in handler flow
Summary ¶

By making inputs and outputs explicit, Stario handlers are easier to read, easier to test, and significantly more predictable. You never have to wonder where a piece of data came from or how it gets to the client.

Changing the world, one byte at a time
