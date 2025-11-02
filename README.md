# FastMCP SSE Disconnect Reproduction

Minimal reproduction case for the ASGI protocol violation in FastMCP's SSE transport when clients disconnect before the first event is sent.

## Issue Summary

FastMCP's SSE transport (`streamable_http.py`) violates the ASGI protocol by sending `http.response.start` without always sending at least one `http.response.body` message, causing "ASGI callable returned without completing response" errors.

**ASGI Requirement:**
Per the [ASGI HTTP specification](https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope), after sending `http.response.start`, you **must** send at least one `http.response.body` message.

## Setup

Install dependencies using uv:

```bash
uv sync
```

## Reproduction Steps

1.  **Start the server** (in one terminal):
    ```bash
    uv run python server.py
    ```

2.  **Run the client** (in another terminal):
    ```bash
    uv run python client.py
    ```

## Expected Behavior

The server logs should show:

- `✅ ASGI protocol completed correctly` - when protocol is followed
- `❌ ASGI PROTOCOL VIOLATION` - when the bug occurs

You should see the protocol violation when the client disconnects before the MCP server sends any response events.

## What Happens

1.  Server sends `http.response.start` (HTTP 200 + SSE headers)
2.  Client disconnects before any SSE events are generated
3.  Server never sends `http.response.body` message
4.  **ASGI protocol violation**: Every response must have at least one body message

## Server Logs Example

When the bug occurs, you'll see:

```
DEBUG    ASGITrackingMiddleware: [/mcp] ASGI: http.response.start
INFO     uvicorn.access: ::1:50000 - "POST /mcp HTTP/1.1" 200 OK
ERROR    ASGITrackingMiddleware: [/mcp] ❌ ASGI PROTOCOL VIOLATION: http.response.start sent but no http.response.body message!
```

## Root Cause

In `mcp/server/streamable_http.py` lines 440-495:

1.  `EventSourceResponse` immediately sends `http.response.start`
2.  `sse_writer()` blocks waiting for events from the MCP server
3.  If client disconnects before any events are ready:
    - The `async for` loop never iterates
    - No SSE data is sent
    - No `http.response.body` message is ever sent
    - ASGI protocol violated

## Project Structure

```
.
├── README.md           # This file
├── pyproject.toml      # Dependencies
├── server.py          # FastMCP SSE server with ASGI tracking
├── client.py          # Client that triggers the issue
└── doc.md             # Detailed technical analysis
```

## Files

- **server.py**: FastMCP server with middleware that tracks ASGI messages and detects violations
- **client.py**: Test client that connects and disconnects at various intervals
- **doc.md**: Comprehensive analysis of the issue with proposed fixes

## Proposed Fixes

See `doc.md` for detailed fix proposals, including:

1.  Ensure body message in `sse_writer()` (recommended)
2.  Send initial keepalive event
3.  Wrap `EventSourceResponse` with completion guarantee

## References

- [ASGI HTTP Spec](https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope)
- [FastMCP Repository](https://github.com/jlowin/fastmcp)
- [SSE Specification](https://html.spec.whatwg.org/multipage/server-sent-events.html)
