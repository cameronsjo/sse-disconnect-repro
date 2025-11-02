"""Client that reproduces the SSE disconnect issue.

This client connects to the FastMCP SSE server and immediately disconnects
to trigger the ASGI protocol violation.
"""

import asyncio
import logging
from typing import Any

import httpx

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def quick_disconnect_test() -> None:
    """Connect and immediately disconnect before any events are sent."""
    logger.info("=" * 60)
    logger.info("TEST: Quick disconnect before first event")
    logger.info("=" * 60)

    # Create a valid MCP initialize request
    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0",
            },
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            # Send POST request to establish SSE connection
            # The Accept header must include BOTH application/json AND text/event-stream
            # for streamable_http to use SSE mode
            logger.info("Sending POST request with SSE Accept header...")

            async with client.stream(
                "POST",
                "http://localhost:8000/mcp",
                json=request_payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                timeout=1.0,  # Short timeout to force quick disconnect
            ) as response:
                logger.info(f"Response status: {response.status_code}")
                logger.info(f"Response headers: {dict(response.headers)}")

                # Immediately close without reading any events
                logger.info("Closing connection immediately without reading events...")
                # Just exit the context manager to disconnect

        except httpx.ReadTimeout:
            logger.info("Timeout occurred (expected)")
        except Exception as e:
            logger.error(f"Error: {type(e).__name__}: {e}")

    logger.info("Connection closed")
    logger.info("")


async def delayed_disconnect_test(delay_ms: int = 100) -> None:
    """Connect, wait briefly, then disconnect before events."""
    logger.info("=" * 60)
    logger.info(f"TEST: Delayed disconnect ({delay_ms}ms) before first event")
    logger.info("=" * 60)

    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0",
            },
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            logger.info("Sending POST request with SSE Accept header...")

            async with client.stream(
                "POST",
                "http://localhost:8000/mcp",
                json=request_payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                timeout=5.0,
            ) as response:
                logger.info(f"Response status: {response.status_code}")

                # Wait a bit before disconnecting
                await asyncio.sleep(delay_ms / 1000.0)
                logger.info(f"Waited {delay_ms}ms, now closing without reading...")

        except httpx.ReadTimeout:
            logger.info("Timeout occurred")
        except Exception as e:
            logger.error(f"Error: {type(e).__name__}: {e}")

    logger.info("Connection closed")
    logger.info("")


async def main() -> None:
    """Run multiple test scenarios."""
    logger.info("FastMCP SSE Disconnect Reproduction Client")
    logger.info("Make sure server.py is running on http://localhost:8000")
    logger.info("")

    # Wait for user to confirm server is ready
    await asyncio.sleep(1)

    # Test 1: Immediate disconnect
    await quick_disconnect_test()
    await asyncio.sleep(1)

    # Test 2: Very quick disconnect (50ms)
    await delayed_disconnect_test(50)
    await asyncio.sleep(1)

    # Test 3: Quick disconnect (100ms)
    await delayed_disconnect_test(100)
    await asyncio.sleep(1)

    # Test 4: Slightly longer (200ms) - might still trigger the issue
    await delayed_disconnect_test(200)

    logger.info("=" * 60)
    logger.info("All tests completed")
    logger.info("Check server logs for ASGI protocol violations")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
