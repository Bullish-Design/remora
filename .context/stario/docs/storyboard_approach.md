
stario.dev
The Storyboard Approach
2–3 minutes

Modern web development is often fragmented: the server has the data, the browser has the state, and the developer has to sync them. This leads to complexity, bugs, and stale UIs.

Stario eliminates the sync layer.
The Pattern: Snapshots, Not Increments ¶

Instead of sending JSON and letting the frontend decide what to change, Stario treates the backend as the Source of Truth.

    Backend renders the complete current state as HTML.
    SSE streams the snapshot to the client.
    Datastar morphs the DOM to match the snapshot.

Think of a storyboard: each frame is a complete scene. You don't describe the difference between frames; you just show the next frame.
Why it's Faster ¶

"Sending HTML every time is wasteful" is a myth.

    HTTP Persistent Connections: A single SSE stream avoids the overhead of repeated TCP/TLS handshakes.
    Compression Dictionary: Compression algorithms (zstd, brotli) learn from previous frames. If you send the same <ul> structure twice, the second one compresses to almost zero bytes.
    No JS Execution: The browser doesn't have to parse JSON, run frameworks, or diff virtual DOMs. It just morphs the real DOM.

Bandwidth Reality ¶
Scenario 	Traditional JSON + Framework 	Stario Snapshot + Compression
Initial Load 	200KB (JSON + JS Framework) 	15KB (HTML)
Interaction 	5KB (JSON) + Client Logic 	1KB (Compressed HTML)
User Feel 	Latency while JS runs 	Instant
One Connection. One Truth. ¶

By moving rendering back to the server, you gain:

    Zero Sync Bugs: Client and server never disagree because the client has no state of its own.
    Multiplayer for Free: Use Relay to push the same snapshot to all connected users.
    Reduced Complexity: No state managers (Redux, Vuex, etc.). Just Python functions returning HTML.

The schizophrenia ends. Stop thinking "what changed?" and start thinking "what does the screen look like now?"

Changing the world, one byte at a time
