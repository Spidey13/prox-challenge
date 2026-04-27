# ADR 003 — Server-Sent Events over WebSocket

**Status:** Accepted  
**Date:** 2025-04

---

## Context

Streaming agent responses to the browser requires a persistent server → client channel. Two main options:

| Option | Protocol | Bidirectional | Complexity | Cloud Run support |
|--------|----------|---------------|------------|-------------------|
| WebSocket | WS/WSS | Yes | Higher — connection lifecycle, reconnect logic | Requires HTTP/2 or explicit WS upgrade config |
| **SSE** | HTTP/1.1 | No (client → server is a separate POST) | Low — standard `EventSource` API | Works out of the box |

The agent is request-response: the user sends a message (POST), the server streams a response. There is no server-initiated push or client-to-server streaming mid-response. WebSocket's bidirectional channel is not needed.

---

## Decision

Use `EventSourceResponse` from `sse-starlette`. The `/ask` route is a `POST` that returns a streaming SSE response. The React client reads it with a manual `fetch` + `ReadableStream` loop (not `EventSource`, to allow POST and custom headers).

Event types emitted:

```
{"type": "token",          "content": "..."}       — text delta
{"type": "job_card_start", "metadata": {...}}       — fault diagnosis header
{"type": "job_card_step",  "step": {...}}            — one diagnostic step
{"type": "done",           "suggestions": [...],
                           "artifact": {...}|null,
                           "job_card": {...}|null,
                           "images": [...]}          — close the stream
```

---

## Consequences

- SSE works through Cloud Run's HTTP/1.1 proxy with no special configuration. `--timeout` on the `gcloud run deploy` command covers long requests.
- A thread-pool/queue bridge in `main.py` decouples the synchronous generator in `agent.py` from the async SSE generator: the tool loop runs in a thread, tokens are pushed to a `queue.Queue`, and the async generator polls the queue with `asyncio.sleep(0.01)` between items.
- Reconnect on network drop is not implemented (the job card state machine in `useJobCard.js` is in-memory). Acceptable for v1; a production version would persist state and replay from a resume token.
