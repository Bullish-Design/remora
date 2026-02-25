
stario.dev
Datastar Signals And Patching
~2 minutes

In Stario + Datastar, you have two ways to update the UI from the server.
1. w.sync (Update State) ¶

Use w.sync when you want to update reactive data on the client. Datastar will automatically update any elements bound to those signals (via data.text, data.bind, etc.).

async def increment(c: Context, w: Writer):
    signals = await c.signals()
    w.sync({"count": signals["count"] + 1})

    Pros: Cleanest logic, minimal data transfer.
    Cons: Requires elements to be pre-bound to signals.

2. w.patch (Update UI) ¶

Use w.patch when you want to replace a specific HTML fragment. Datastar finds the element by its id and morphs/replaces it.

async def update_msg(c: Context, w: Writer):
    w.patch(Div({"id": "status"}, "Operation Complete!"))

    Pros: Can update any part of the page dynamically.
    Cons: Transfers more data (HTML instead of just values).

Which one to choose? ¶
Scenario 	Recommendation
Updating a counter or small value 	w.sync
Adding a new item to a list 	w.patch (with mode="append")
Replacing a complex component 	w.patch
Clearing a form after submission 	w.sync
Combining Both ¶

You can use both in a single handler. Stario batches them into a single SSE stream response.

async def add_todo(c: Context, w: Writer):
    signals = await c.signals()

    # 1. Patch the list with the new item
    w.patch(Li(signals["new_todo"]), selector="#list", mode="append")

    # 2. Sync the input signal back to empty
    w.sync({"new_todo": ""})

Changing the world, one byte at a time
