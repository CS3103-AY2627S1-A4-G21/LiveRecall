#!/usr/bin/env python3
"""Unit tests for client_sender flow control: at most FLOW_WINDOW unconfirmed messages per client."""

import asyncio
import unittest

from solution_server import FLOW_WINDOW, ClientConnection, client_sender


class FakeWebSocket:
    """Records sent messages; each ping returns a future that resolves when the test sends the pong."""

    def __init__(self, auto_pong: bool = False) -> None:
        self.auto_pong = auto_pong
        self.sent: list[str] = []
        self.pings: list[asyncio.Future] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def ping(self) -> asyncio.Future:
        pong_received = asyncio.get_running_loop().create_future()
        if self.auto_pong:
            pong_received.set_result(0.001)
        self.pings.append(pong_received)
        return pong_received

    async def close(self, code: int = 1000, reason: str = "") -> None:
        pass


class TestFlowControl(unittest.IsolatedAsyncioTestCase):
    async def start(self, auto_pong: bool = False) -> None:
        self.ws = FakeWebSocket(auto_pong)
        self.client = ClientConnection(ws=self.ws, session="L1")
        self.sender = asyncio.create_task(client_sender(self.client))

    async def asyncTearDown(self) -> None:
        self.sender.cancel()
        await asyncio.gather(self.sender, return_exceptions=True)

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    async def pong_until_drained(self) -> None:
        for _ in range(50):
            for pong_received in self.ws.pings:
                if not pong_received.done():
                    pong_received.set_result(0.001)
            await self.settle()

    async def test_stops_at_window_until_pong(self):
        """Without pongs, only FLOW_WINDOW messages are sent; pongs release the rest."""
        await self.start()
        total = FLOW_WINDOW + 3
        for seg in range(1, total + 1):
            self.client.queue.enqueue_caption(seg, 1, True, f"seg{seg}_final")
        await self.settle()

        self.assertEqual(len(self.ws.sent), FLOW_WINDOW)
        self.assertTrue(self.client.queue.flow_blocked)

        await self.pong_until_drained()
        self.assertEqual(self.ws.sent, [f"seg{seg}_final" for seg in range(1, total + 1)])

    async def test_coalesces_while_blocked(self):
        """Revisions arriving while the window is full stay queued, so obsolete ones are merged away."""
        await self.start()
        for seg in range(1, FLOW_WINDOW + 1):
            self.client.queue.enqueue_caption(seg, 1, True, f"seg{seg}_final")
        await self.settle()
        self.assertTrue(self.client.queue.flow_blocked)

        seg = FLOW_WINDOW + 1
        self.client.queue.enqueue_caption(seg, 1, False, "rev1")
        self.client.queue.enqueue_caption(seg, 2, False, "rev2")
        self.client.queue.enqueue_caption(seg, 3, True, "rev3_final")
        self.assertEqual(self.client.queue.qsize(), 1)

        await self.pong_until_drained()
        self.assertEqual(self.ws.sent[-1], "rev3_final")
        self.assertNotIn("rev1", self.ws.sent)
        self.assertNotIn("rev2", self.ws.sent)

    async def test_healthy_client_receives_every_revision(self):
        """A client whose pongs return promptly is never blocked and gets every revision."""
        await self.start(auto_pong=True)
        expected = []
        for seg in range(1, 4):
            for rev in range(1, 4):
                payload = f"seg{seg}_rev{rev}"
                self.client.queue.enqueue_caption(seg, rev, rev == 3, payload)
                expected.append(payload)
            await self.settle()

        self.assertEqual(self.ws.sent, expected)
        self.assertFalse(self.client.queue.flow_blocked)


if __name__ == "__main__":
    unittest.main()
