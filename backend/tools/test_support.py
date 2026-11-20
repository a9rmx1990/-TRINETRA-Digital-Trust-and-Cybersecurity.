"""In-process ASGI client for integration tests."""

import asyncio

from fastapi.testclient import TestClient


def test_client(app):
    def loop_factory():
        loop = asyncio.new_event_loop()

        def pulse():
            # Restricted runners can block the portal's cross-thread socket wakeups.
            loop.call_later(0.012, pulse)

        loop.call_soon(pulse)
        return loop

    return TestClient(app, backend_options={"loop_factory": loop_factory})


test_client.__test__ = False
