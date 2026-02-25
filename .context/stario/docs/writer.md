
Writer Reference ¶

The Writer (w) is your interface for sending HTTP responses. It handles one-shot responses, SSE streaming, and connection lifecycle.
One-Shot Responses ¶

Methods that send a full response and complete the connection.
Method 	Description 	Example
w.html(el) 	Send HTML element or string 	w.html(Div("Hello"))
w.json(data) 	Send JSON response 	w.json({"ok": True})
w.text(text) 	Send plain text 	w.text("OK")
w.redirect(url) 	HTTP redirect (307 default) 	w.redirect("/login")
w.empty(status) 	Empty response (204 default) 	w.empty()
SSE & Datastar Streaming ¶

Methods for real-time DOM patches and signal syncing.
Method 	Description 	Example
w.patch(el) 	Update DOM element by ID 	w.patch(Div({"id": "x"}, "New"))
w.sync(data) 	Update client-side signals 	w.sync({"count": 5})
w.navigate(url) 	Client-side navigation 	w.navigate("/home")
w.execute(js) 	Execute JavaScript 	w.execute("alert('Hi')")
w.remove(sel) 	Remove element from DOM 	w.remove("#error")
Connection Lifecycle: w.alive() ¶

w.alive() is an async iterator and context manager that monitors the connection and exits cleanly when the client disconnects or the server shuts down (e.g. via SIGINT/SIGTERM). Under the hood, it watches two futures - w._disconnect and w._shutdown - and cancels the current task when either resolves. The CancelledError is swallowed automatically, so code after the w.alive() block always runs, making it the natural place for cleanup.
Three usage patterns ¶

# 1. Wrap an async subscription - iterates until disconnect/shutdown
async for msg in w.alive(relay.subscribe("updates")):
    w.patch(render(msg))
# cleanup runs here

# 2. Infinite loop - await inside the loop body
async for _ in w.alive():
    msg = await queue.get()
    w.patch(render(msg))
# cleanup runs here

# 3. Context manager - protect a one-shot async operation
async with w.alive():
    result = await slow_api_call()
    w.patch(Div("Done"))
# cleanup runs here

In all three patterns, the block exits immediately when the client disconnects or the server begins shutting down. Any code placed after the block is guaranteed to run, so you can use it for resource cleanup.
Raw Response Methods: The Core Primitives ¶

Every response method in the Writer - w.html(), w.json(), w.text(), w.patch(), w.empty(), and so on - is a convenience method built on top of three core primitives: w.write_headers(), w.write(), and w.end(). These three methods form the foundation of all HTTP responses in Stario. Understanding them gives you full control over the response lifecycle and lets you implement custom protocols, stream binary data, proxy responses, or anything else the convenience methods don't cover.
w.write_headers(status_code) ¶

Send the HTTP status line and headers immediately. Must be called before w.write() if you want to set a specific status code (otherwise w.write() auto-sends 200).

    If Content-Length is set in headers, the response uses fixed-length mode.
    Otherwise, chunked transfer encoding is used automatically.
    Raises RuntimeError if called twice.
    Returns self for chaining.

async def stream_file(c: Context, w: Writer) -> None:
    w.headers.set("Content-Type", "application/octet-stream")
    w.headers.set("Content-Length", "1024")
    w.write_headers(200)
    w.write(file_bytes)
    w.end()

w.write(data) ¶

Write raw bytes to the response body.

    If headers haven't been sent yet, auto-sends them with status 200.
    In chunked mode (no Content-Length), applies compression if configured.
    In fixed-length mode (with Content-Length), writes directly - you control compression.
    Raises RuntimeError if called after w.end() or a one-shot method.
    Returns self for chaining.

w.write(b"chunk one")
w.write(b"chunk two")
w.end()

w.end(data=None) ¶

Finalize the response. No more writes are allowed after this.

    If headers haven't been sent yet, sends a minimal response (204 if no data, 200 if data is provided).
    Optionally writes a final chunk of data before finalizing.
    Sends the chunked encoding terminator if in chunked mode.

# Minimal empty response
w.end()

# Or finalize with data
w.end(b"final bytes")

Cookies & Headers ¶

# Cookies
w.cookie("session", token, httponly=True, secure=True)
w.delete_cookie("session")

# Headers (set before calling a response method)
w.headers.set("X-Custom", "val")
w.headers.add("X-Multi", "one")
w.headers.add("X-Multi", "two")

# Status is passed to the response method
w.json(data, status=201)

Headers accept both str and bytes for names and values. Names are normalized to lowercase internally. Use .set() to replace and .add() to append multiple values for the same header.
Compression ¶

Stario automatically uses zstd, brotli, or gzip based on the client's Accept-Encoding. No configuration needed for standard use.

Changing the world, one byte at a time
