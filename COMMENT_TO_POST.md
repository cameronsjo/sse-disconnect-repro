## Reproduction Attempt & Code Analysis

I've created a minimal reproduction environment for this issue. While I wasn't able to trigger the bug with current library versions, I can confirm the vulnerable code pattern exists.

### 📦 Reproduction Repository

**Repository:** https://github.com/cameronsjo/sse-disconnect-repro

Complete setup with:
- FastMCP SSE server with ASGI protocol tracking middleware
- Multiple test clients with various disconnect strategies
- Full documentation and analysis

```bash
git clone https://github.com/cameronsjo/sse-disconnect-repro
cd sse-disconnect-repro
uv sync
uv run python server.py  # Terminal 1
uv run python client.py  # Terminal 2
```

### 🔍 Confirming the Vulnerable Code Pattern

The issue exists in `mcp/server/streamable_http.py` lines 460-480:

```python
async def sse_writer():
    try:
        async with sse_stream_writer, request_stream_reader:
            async for event_message in request_stream_reader:  # ← Blocks here
                event_data = self._create_event_data(event_message)
                await sse_stream_writer.send(event_data)  # ← Never reached if disconnect early
                # ...
```

**The Flow:**
1. Line 497: `EventSourceResponse` sends `http.response.start` immediately
2. Line 465: `sse_writer()` blocks waiting for events from the MCP server
3. Client disconnects before any events generated
4. `sse_stream_writer.send()` never called → No `http.response.body` → ASGI violation

### 🧪 Test Results

**Tested with:**
- FastMCP: 2.13.0.2
- MCP SDK: 1.20.0
- sse-starlette: 3.0.3

**Result:** Unable to reproduce - all requests completed correctly.

**Why:** MCP server responds in <10ms, and `sse-starlette` appears to send initial chunks that satisfy ASGI requirements.

### 🔧 Proposed Fix

Even though hard to reproduce, the defensive fix ensures robustness:

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

### 💡 When This Could Trigger

- Slow MCP processing (>100ms delays)
- High server load causing task scheduling delays
- TCP RST packets before buffered data sent
- Stricter ASGI server implementations

### 🎯 Recommendation

Apply the defensive fix because:
- Vulnerable pattern exists in the code
- Edge cases under load could trigger it
- Simple fix adds robustness
- Ensures ASGI spec compliance

Happy to submit a PR with the fix if helpful!
