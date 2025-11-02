# GitHub Issue Comment

## Reproduction Attempt & Code Analysis

I've created a minimal reproduction environment for this issue. While I wasn't able to trigger the bug with current library versions, I can confirm the vulnerable code pattern exists and provide the reproduction tooling for further testing.

### 📦 Reproduction Repository

I've created a complete reproduction setup with:
- FastMCP SSE server with ASGI protocol tracking middleware
- Multiple test clients with various disconnect strategies
- Full documentation and analysis

**Repository structure:**
```
sse-disconnect-repro/
├── server.py                    # FastMCP server with ASGI tracking
├── client.py                    # Standard test client
├── client_fast_disconnect.py    # Aggressive disconnect testing
├── pyproject.toml               # Dependencies (fastmcp, uvicorn, httpx)
├── README.md                    # Setup & usage instructions
└── FINDINGS.md                  # Detailed test results & analysis
```

### 🔍 Code Analysis - Confirming the Bug Pattern

The vulnerable code still exists in `mcp/server/streamable_http.py` lines 460-480:

```python
async def sse_writer():
    try:
        async with sse_stream_writer, request_stream_reader:
            # Process messages from the request-specific stream
            async for event_message in request_stream_reader:  # ← Blocks waiting for events
                event_data = self._create_event_data(event_message)
                await sse_stream_writer.send(event_data)  # ← Never reached if client disconnects early

                if isinstance(event_message.message.root, JSONRPCResponse | JSONRPCError):
                    break
    except Exception:
        logger.exception("Error in SSE writer")
    finally:
        logger.debug("Closing SSE writer")
        await self._clean_up_memory_streams(request_id)
```

**The Problem:**
1. Line 497: `EventSourceResponse` sends `http.response.start` immediately
2. Line 465: `sse_writer()` blocks waiting for events from `request_stream_reader`
3. If client disconnects before any events: The async for never iterates, `sse_stream_writer.send()` is never called
4. Result: No `http.response.body` message → ASGI protocol violation

### 🧪 Test Results

**Environment Tested:**
- FastMCP: 2.13.0.2
- MCP SDK: 1.20.0
- sse-starlette: 3.0.3
- Python: 3.12
- ASGI Server: uvicorn 0.38.0

**Result:** ❌ Unable to reproduce with current versions

**Why it didn't trigger:**
1. MCP server responds very quickly (initialize requests complete in <10ms)
2. `sse-starlette`'s `EventSourceResponse` appears to send initial chunks, mitigating the issue
3. Bug may have been fixed in recent library versions

### 💡 When This Bug Could Still Occur

1. **Slow MCP Processing**: If the server takes >100ms to process requests
2. **High Server Load**: Task scheduling delays under heavy load
3. **Network Aborts**: TCP RST packets before any buffered data sent
4. **Different SSE Libraries**: Custom implementations without proper safeguards
5. **Stricter ASGI Servers**: Some servers have stricter protocol validation

### 🔧 Proposed Fix

Add defensive code to ensure at least one body message is sent:

```python
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
```

### 📋 Next Steps for Reproduction

To trigger this bug reliably, consider:

1. **Add Processing Delays**: Insert artificial delays in MCP message handling
2. **Test Older Versions**: Try fastmcp < 2.0 or mcp < 1.0
3. **Load Testing**: Many concurrent connections with rapid disconnects
4. **Network-Level Tools**: Use tools like `tcpkill` to force abrupt disconnection
5. **Mock EventSourceResponse**: Replace with minimal implementation

### 🎯 Recommendation

Even though this is hard to reproduce in practice with current versions, the defensive fix should be applied because:
- The vulnerable code pattern exists
- Edge cases under load could still trigger it
- The fix is simple and adds robustness
- ASGI spec compliance is important for compatibility

Would you like me to share the full reproduction repository, or would a PR with the defensive fix be more helpful?

---

**Testing the reproduction:**
```bash
# Clone or create the files mentioned above
uv sync
uv run python server.py  # Terminal 1
uv run python client.py  # Terminal 2
```

The server logs will show whether ASGI protocol violations occur.
