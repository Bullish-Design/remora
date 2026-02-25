
stario.dev
Database Dependency
~2 minutes
Database Access ¶

Stario uses standard Python closures for dependency injection. This makes database access explicit and easy to test.
1. The Closure Pattern ¶

Create a factory function that takes your database client and returns handlers.

def user_handlers(db: Database):

    async def get_user(c: Context, w: Writer):
        user_id = c.req.tail
        user = await db.find(user_id)
        w.json(user)

    return get_user

# Usage in main.py
db = Database("postgresql://...")
app.get("/users/*", user_handlers(db))

2. Router Factories ¶

For larger apps, create entire routers with their own dependencies.

def api_router(pool: Pool) -> Router:
    r = Router()

    async def list_items(c: Context, w: Writer):
        async with pool.acquire() as conn:
            items = await conn.fetch("SELECT * FROM items")
            w.json(items)

    r.get("/items", list_items)
    return r

# Mounting
app.mount("/api", api_router(my_pool))

3. Connection Pooling (Production) ¶

Initialize your pool in async main() and pass it down.

async def main():
    pool = await asyncpg.create_pool("...")

    app = Stario()
    app.mount("/api", api_router(pool))

    await app.serve()

Why this wins? ¶

    No Globals: You don't need a global db object.
    Unit Testing: You can pass a MockDatabase() into your factory during tests.
    Explicit: Every handler shows exactly where its dependencies come from.

Changing the world, one byte at a time
