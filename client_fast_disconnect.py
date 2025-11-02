"""Client that disconnects immediately to trigger ASGI violation.

This client uses asyncio.wait_for with a very short timeout to force
disconnection before the server sends any events.
"""

import asyncio
import logging

import httpx

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def ultra_fast_disconnect() -> None:
    """Connect and force disconnect by cancelling the request task."""
    logger.info("=" * 60)
    logger.info("TEST: Ultra-fast disconnect via task cancellation")
    logger.info("=" * 60)

    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",  # Simple list request
        "params": {},
    }

    async def make_request() -> None:
        async with httpx.AsyncClient() as client:
            logger.info("Starting SSE streaming request...")
            async with client.stream(
                "POST",
                "http://localhost:8000/mcp",
                json=request_payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            ) as response:
                logger.info(f"Got response: {response.status_code}")
                logger.info("About to be cancelled...")
                # This will be cancelled before we read anything
                async for _ in response.aiter_bytes():
                    pass

    task = asyncio.create_task(make_request())

    try:
        # Wait just long enough for the connection to be established
        # but not long enough for any data to be received
        await asyncio.wait_for(task, timeout=0.001)  # 1ms
    except asyncio.TimeoutError:
        logger.info("Timeout reached, cancelling request task...")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("Task cancelled successfully")

    logger.info("Connection forcibly closed")
    logger.info("")


async def rapid_disconnect_during_handshake() -> None:
    """Send request but disconnect during TCP/TLS handshake."""
    logger.info("=" * 60)
    logger.info("TEST: Disconnect during connection handshake")
    logger.info("=" * 60)

    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "slow_operation",  # This takes 2 seconds
            "arguments": {},
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            # Use context manager but cancel immediately
            logger.info("Opening streaming connection...")
            request = client.build_request(
                "POST",
                "http://localhost:8000/mcp",
                json=request_payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )

            # Send the request
            response = await client.send(request, stream=True)
            logger.info(f"Response started: {response.status_code}")

            # Close immediately without reading
            await response.aclose()
            logger.info("Closed response immediately")

        except Exception as e:
            logger.error(f"Error: {type(e).__name__}: {e}")

    logger.info("")


async def main() -> None:
    """Run aggressive disconnect tests."""
    logger.info("FastMCP SSE Ultra-Fast Disconnect Client")
    logger.info("Attempting to trigger ASGI protocol violation")
    logger.info("")

    # Test 1: Ultra-fast disconnect via cancellation
    await ultra_fast_disconnect()
    await asyncio.sleep(1)

    # Test 2: Rapid disconnect during handshake
    await rapid_disconnect_during_handshake()
    await asyncio.sleep(1)

    # Test 3: Multiple rapid attempts
    logger.info("=" * 60)
    logger.info("TEST: 10 rapid connection attempts")
    logger.info("=" * 60)

    tasks = []
    for i in range(10):
        tasks.append(ultra_fast_disconnect())

    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("=" * 60)
    logger.info("All tests completed - check server logs for violations")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
