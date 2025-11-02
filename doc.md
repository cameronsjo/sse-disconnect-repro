Secure Note
FastMCP SSE Transport ASGI Protocol Violation
Summary
FastMCP's SSE transport (streamable_http.py) violates the ASGI protocol by sending http.response.start without always sending at least one http.response.body message, causing "ASGI callable returned without completing response" errors.

Environment
FastMCP Version: (check with pip show fastmcp)
MCP SDK Version: mcp package from site-packages/mcp/server/streamable_http.py
Python Version: 3.13
ASGI Server: uvicorn
Transport: SSE (Server-Sent Events) / streamable-http
Problem Description
What Happens
When a client connects to an MCP server using SSE transport and disconnects before the server sends any events, the server violates the ASGI protocol:

✅ Server sends http.response.start (HTTP 200 + headers)
❌ Client disconnects before any SSE events are generated
❌ Server never sends http.response.body message
❌ ASGI protocol violation: Every response MUST have at least one body message
ASGI Specification Requirement
Per the ASGI HTTP specification (https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope):

After sending http.response.start, you must send at least one http.response.body message containing the response body. You can send as many as you like, but you must send at least one.

Symptoms
Server-Side Logs
INFO:     ::1:50000 - "POST /mcp HTTP/1.1" 200 OK
ASGI callable returned without completing response.
Or with more detailed logging:

DEBUG    Creating new transport
INFO     Created new transport with session ID: a02d5b457b4b44f3a7e10723670a2020
DEBUG    JSONRPCBatchRejectionMiddleware send: message type=http.response.start
DEBUG    ProtocolVersionMiddleware send: message type=http.response.start
INFO:    ::1:55074 - "POST /mcp HTTP/1.1" 200 OK
DEBUG    Got event: http.disconnect. Stop streaming.
DEBUG    Closing SSE writer
DEBUG    Request stream 0 not found for message. Still processing message as the client might reconnect and replay.
ASGI callable returned without completing response.
Client-Side Symptoms
Connection hangs or times out
"Connection closed unexpectedly" errors
Empty response body despite receiving HTTP 200 OK
SSE connection fails to establish
Client needs frequent reconnect/retry logic
Root Cause Analysis
Code Location
File: mcp/server/streamable_http.py
Lines: 440-495 (SSE response path in _handle_post_request)

The Problematic Code Flow
async def _handle_post_request(self, scope: Scope, request: Request, receive: Receive, send: Send) -> None:
    # ... validation code ...

    else:  # Line 440: SSE response path
        # Create SSE stream
        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, str]](0)

        async def sse_writer():
            try:
                async with sse_stream_writer, request_stream_reader:
                    # Process messages from the request-specific stream
                    async for event_message in request_stream_reader:  # ← BLOCKS HERE WAITING FOR EVENTS
                        # Build the event data
                        event_data = self._create_event_data(event_message)
                        await sse_stream_writer.send(event_data)  # ← NEVER REACHED IF CLIENT DISCONNECTS

                        # If response, close
                        if isinstance(event_message.message.root, JSONRPCResponse | JSONRPCError):
                            break
            except Exception:
                logger.exception("Error in SSE writer")
            finally:
                logger.debug("Closing SSE writer")
                await self._clean_up_memory_streams(request_id)

        # Create EventSourceResponse
        response = EventSourceResponse(
            content=sse_stream_reader,
            data_sender_callable=sse_writer,  # ← Calls sse_writer() above
            headers=headers,
        )

        # Start the SSE response (this will send headers immediately)
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(response, scope, receive, send)  # ← Sends http.response.start
                # Send message to MCP server for processing
                metadata = ServerMessageMetadata(request_context=request)
                session_message = SessionMessage(message, metadata=metadata)
                await writer.send(session_message)  # ← Sends to MCP server
        except Exception:
            logger.exception("SSE response error")
            # Cleanup...
Why It Fails
Line 475-479: EventSourceResponse starts and immediately sends http.response.start (HTTP 200 + SSE headers)
Line 449: sse_writer() blocks waiting for events from request_stream_reader (the MCP server's response)
If client disconnects early:
The async for loop at line 449 never iterates (no events to send)
Line 452 (sse_stream_writer.send()) is never reached
EventSourceResponse never sends any SSE data
No http.response.body message is ever sent
ASGI protocol violated
When It Occurs
Client connects and immediately disconnects (network issues, timeouts, retry logic)
Quick request/response cycles during connection initialization
SSE handshake phase before first event
Client-side connection pooling or load balancing
Any scenario where the MCP server doesn't generate a response event before the client disconnects
Impact
On Server
ASGI compliance warnings/errors in logs
Potential issues with:
Load balancers expecting proper HTTP responses
Monitoring tools detecting incomplete responses
ASGI server connection pool management
Middleware that expects complete ASGI protocol
On Client
Unreliable SSE connections requiring excessive retry logic
Difficulty distinguishing between server errors and incomplete responses
Potential connection leaks or hung connections
Increased latency from connection retries
Proposed Fix
Option 1: Ensure Body Message in sse_writer() (Recommended)
Modify the sse_writer() function to always send at least one body message:

async def sse_writer():
    body_sent = False  # Track if any body sent
    try:
        async with sse_stream_writer, request_stream_reader:
            async for event_message in request_stream_reader:
                event_data = self._create_event_data(event_message)
                await sse_stream_writer.send(event_data)
                body_sent = True

                if isinstance(event_message.message.root, JSONRPCResponse | JSONRPCError):
                    break
    except Exception:
        logger.exception("Error in SSE writer")
    finally:
        # Ensure ASGI protocol completion
        if not body_sent:
            # Send keepalive comment or close event to complete protocol
            await sse_stream_writer.send({
                "event": "close",
                "data": ""
            })
        logger.debug("Closing SSE writer")
        await self._clean_up_memory_streams(request_id)
Option 2: Send Initial Keepalive Event
Send an immediate keepalive/connection-established event before waiting for MCP responses:

async def sse_writer():
    try:
        async with sse_stream_writer, request_stream_reader:
            # Send initial keepalive to ensure at least one body message
            await sse_stream_writer.send({
                "event": "connected",
                "data": json.dumps({"status": "connected"})
            })

            # Now wait for actual events
            async for event_message in request_stream_reader:
                event_data = self._create_event_data(event_message)
                await sse_stream_writer.send(event_data)

                if isinstance(event_message.message.root, JSONRPCResponse | JSONRPCError):
                    break
    except Exception:
        logger.exception("Error in SSE writer")
    finally:
        logger.debug("Closing SSE writer")
        await self._clean_up_memory_streams(request_id)
Option 3: Wrap EventSourceResponse with Completion Guarantee
Create a wrapper that ensures protocol completion:

class ASGICompliantEventSourceResponse(EventSourceResponse):
    """EventSourceResponse that guarantees ASGI protocol completion."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        response_started = False
        body_sent = False

        async def tracking_send(message):
            nonlocal response_started, body_sent
            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.body":
                body_sent = True
            await send(message)

        try:
            await super().__call__(scope, receive, tracking_send)
        finally:
            # Ensure completion
            if response_started and not body_sent:
                await send({
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False
                })
Workarounds
Server-Side: Middleware Completion Guard
Until FastMCP is fixed, add middleware to ensure ASGI completion:

class ASGICompletionMiddleware:
    """Ensures ASGI protocol completion for incomplete responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False
        body_sent = False

        async def tracking_send(message):
            nonlocal response_started, body_sent
            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.body":
                body_sent = True
            await send(message)

        await self.app(scope, receive, tracking_send)

        # Complete protocol if app didn't
        if response_started and not body_sent:
            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False
            })
Client-Side: Use HTTP Transport Instead
If SSE streaming isn't required, use regular HTTP transport:

from mcp import ClientSession

session = ClientSession(
    server_url="http://localhost:3000/mcp",
    transport="http"  # Not SSE
)
References
ASGI HTTP Spec: https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope
FastMCP Repository: https://github.com/jlowin/fastmcp
Related Issues: (none found yet)
SSE Specification: https://html.spec.whatwg.org/multipage/server-sent-events.html
Reproduction Steps
Create MCP server with SSE transport using FastMCP
Add middleware or logging to track ASGI messages
Connect client and immediately disconnect before server sends events
Observe "ASGI callable returned without completing response" error
Additional Context
This issue also affects the GET request SSE handler (lines 508-598) for standalone SSE streams, though it's less common since GET handlers typically establish long-lived connections.

The same pattern exists in _handle_get_request() starting at line 560 with the standalone_sse_writer() function.

Testing Recommendations
Once fixed, add tests for:

Client disconnect before first event
Client disconnect during event streaming
Network timeout scenarios
Rapid connect/disconnect cycles
Zero-event responses (server sends no data)
Environment Detection
This issue is particularly problematic when:

Running behind load balancers that enforce HTTP compliance
Using ASGI servers with strict protocol validation
Deploying with monitoring tools that check response completeness
Working with clients that have aggressive timeout/retry logic
