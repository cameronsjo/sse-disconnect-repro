"""FastMCP SSE Server for reproducing ASGI protocol violation.

This server demonstrates the issue where disconnecting before the first
SSE event causes an ASGI protocol violation.
"""

import logging
from typing import Any

from fastmcp import FastMCP

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


class ASGITrackingMiddleware:
    """Middleware to track ASGI messages and detect protocol violations."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: Any, send: Any
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False
        body_sent = False
        path = scope.get("path", "")

        async def tracking_send(message: dict) -> None:
            nonlocal response_started, body_sent
            msg_type = message["type"]

            if msg_type == "http.response.start":
                response_started = True
                logger.debug(f"[{path}] ASGI: http.response.start")
            elif msg_type == "http.response.body":
                body_sent = True
                more_body = message.get("more_body", False)
                body_len = len(message.get("body", b""))
                logger.debug(
                    f"[{path}] ASGI: http.response.body "
                    f"(bytes={body_len}, more_body={more_body})"
                )
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        finally:
            # Check for protocol violation
            if response_started and not body_sent:
                logger.error(
                    f"[{path}] ❌ ASGI PROTOCOL VIOLATION: "
                    f"http.response.start sent but no http.response.body message!"
                )
            elif response_started and body_sent:
                logger.debug(f"[{path}] ✅ ASGI protocol completed correctly")


# Create FastMCP instance
mcp = FastMCP("Test Server")


@mcp.tool()
def get_greeting(name: str) -> str:
    """Get a greeting for the given name."""
    return f"Hello, {name}!"


@mcp.tool()
async def slow_operation() -> str:
    """A slow operation that takes time to respond."""
    import asyncio

    await asyncio.sleep(2)
    return "Operation completed"


# Get the streamable_http app from FastMCP (call the method to get the actual app)
# This uses mcp.server.streamable_http under the hood (the buggy code)
http_app = mcp.streamable_http_app()

# Wrap with tracking middleware
app = ASGITrackingMiddleware(http_app)

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting FastMCP SSE server on http://localhost:8000")
    logger.info("MCP endpoint: http://localhost:8000/mcp")
    logger.info("Connect and disconnect quickly to reproduce the issue")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        log_level="debug",
    )
