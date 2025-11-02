# SSE Disconnect Issue - Reproduction Findings

## Summary

Attempted to reproduce the ASGI protocol violation described in `doc.md` where FastMCP's SSE transport fails to send `http.response.body` when clients disconnect before the first event.

## Test Setup

- **FastMCP Version**: 2.13.0.2
- **MCP SDK Version**: Latest from pip (mcp package)
- **Python Version**: 3.12
- **ASGI Server**: uvicorn 0.38.0
- **Transport**: streamable_http (SSE mode)

## Test Results

### ✅ Successfully Created Reproduction Environment

1.  **Server**: FastMCP server with custom ASGI tracking middleware that monitors:
    - `http.response.start` messages
    - `http.response.body` messages
    - Detects when start is sent without body (protocol violation)

2.  **Clients**: Multiple test clients with various disconnect strategies:
    - Immediate disconnect after connection
    - Delayed disconnects (50ms, 100ms, 200ms)
    - Ultra-fast disconnect via task cancellation (1ms timeout)
    - Rapid multiple connection attempts

### ❌ Unable to Reproduce the Bug

**Result**: All test scenarios showed `✅ ASGI protocol completed correctly` in server logs.

**Why the bug wasn't reproduced**:

1.  **Fast Response Times**: The MCP server responds to `initialize` requests almost instantaneously, sending the response before clients can disconnect.

2.  **sse_starlette Handles This**: The `EventSourceResponse` from `sse_starlette` library appears to handle edge cases properly, potentially including:
    - Sending an empty body chunk when no data is available
    - Proper cleanup when connections close

3.  **Possible Fix Already Applied**: The issue described in `doc.md` may have been fixed in recent versions of:
    - FastMCP (2.13.0.2)
    - MCP SDK (1.20.0)
    - sse-starlette (3.0.3)

## Code Analysis

### Confirmed Vulnerable Code Path Exists

The code in `mcp/server/streamable_http.py` lines 460-480 still contains the pattern described in `doc.md`:

```python
async def sse_writer():
    try:
        async with sse_stream_writer, request_stream_reader:
            # Process messages from the request-specific stream
            async for event_message in request_stream_reader:  # ← Can block waiting
                event_data = self._create_event_data(event_message)
                await sse_stream_writer.send(event_data)  # ← Never reached if no events

                if isinstance(event_message.message.root, JSONRPCResponse | JSONRPCError):
                    break
    except Exception:
        logger.exception("Error in SSE writer")
    finally:
        logger.debug("Closing SSE writer")
        await self._clean_up_memory_streams(request_id)
```

**The issue**: If `request_stream_reader` never yields any items (because processing hasn't started or completed), and the client disconnects, the `sse_stream_writer.send()` is never called.

### Why It Didn't Trigger

The `EventSourceResponse` from `sse-starlette` likely sends an initial body message even before `sse_writer()` sends any events, satisfying the ASGI protocol requirement.

## Scenarios Where Bug Might Still Occur

The bug could potentially still manifest in these conditions:

1.  **Very Slow MCP Server Processing**: If the MCP server takes significant time to start processing (>1s) and the client disconnects during this window

2.  **High Server Load**: Under heavy load, if the task group doesn't schedule `sse_writer()` quickly enough

3.  **Network Issues**: If the client's TCP connection is abruptly terminated (RST packet) before any buffered data is sent

4.  **Custom EventSourceResponse**: If using a different SSE library or custom implementation

5.  **Different ASGI Servers**: Some ASGI servers might be more strict about protocol compliance

## Recommendations

### For Documenting the Issue

The issue in `doc.md` is accurately described from a code analysis perspective. The vulnerable pattern exists in the code, even if it's difficult to trigger in practice with current library versions.

### For Testing

To properly test this bug, you would need:

1.  **Slow MCP Handler**: Add artificial delays in the MCP message processing pipeline
2.  **Network-Level Disconnect**: Use TCP RST to force immediate disconnection
3.  **Load Testing**: Stress test with many concurrent connections
4.  **Mock EventSourceResponse**: Replace with a minimal implementation that doesn't send initial chunks

### For Fixing

The fixes proposed in `doc.md` are still valid and would make the code more robust:

**Option 1** (Recommended): Ensure `sse_writer()` always sends at least one message:

```python
async def sse_writer():
    body_sent = False
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
        if not body_sent:
            await sse_stream_writer.send({"event": "close", "data": ""})
        logger.debug("Closing SSE writer")
        await self._clean_up_memory_streams(request_id)
```

## Conclusion

While we successfully created a reproduction environment and test harness, we were unable to trigger the ASGI protocol violation with current library versions. The bug pattern exists in the code, but appears to be mitigated by the `sse-starlette` library's implementation.

The issue remains a potential concern for edge cases and would benefit from the defensive fixes proposed in `doc.md`.

## Files Created

- `server.py` - FastMCP server with ASGI tracking middleware
- `client.py` - Standard test client with various disconnect timings
- `client_fast_disconnect.py` - Aggressive disconnect testing
- `pyproject.toml` - Project dependencies
- `README.md` - Setup and usage instructions
- `FINDINGS.md` - This document

## Next Steps

To actually reproduce the bug, consider:

1.  Adding delays to the MCP message processing
2.  Using older versions of fastmcp/mcp/sse-starlette
3.  Testing under high load with many concurrent connections
4.  Using network-level tools to force TCP disconnection
5.  Implementing a custom minimal EventSourceResponse
