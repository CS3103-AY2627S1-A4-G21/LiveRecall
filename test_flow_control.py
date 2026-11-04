#!/usr/bin/env python3
"""Unit tests for client_sender flow control and slow-reader detection."""

import asyncio
import unittest

from solution_server import (
    CLIENTS,
    FLOW_WINDOW,
    MIN_RTT_SAMPLES,
    SLOW_EXIT_MESSAGES,
    STALE_PONG_STREAK,
    ClientConnection,
    client_sender,
    enqueue_live_update,
)


class FakeWebSocket:
    """Records sent messages; each ping returns a future that resolves when the test sends the pong."""

    def __init__(self, auto_pong: bool = False) -> None:
        self.auto_pong = auto_pong
        self.sent: list[str] = []
        self.pings: list[asyncio.Future] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)
        # Yield like real socket I/O, so pongs can arrive between sends
        await asyncio.sleep(0)

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
        CLIENTS.discard(self.client)
        self.sender.cancel()
        await asyncio.gather(self.sender, return_exceptions=True)

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    def pong(self, latency: float) -> None:
        """Answer every outstanding ping with the given round-trip latency."""
        for pong_received in self.ws.pings:
            if not pong_received.done():
                pong_received.set_result(latency)

    async def pong_until_drained(self, latency: float = 0.001) -> None:
        for _ in range(50):
            self.pong(latency)
            await self.settle()

    async def send_one(self, seg: int, latency: float) -> None:
        """Send one final caption and answer its ping with the given latency."""
        self.client.queue.enqueue_caption(seg, 1, True, f"seg{seg}_final")
        await self.settle()
        self.pong(latency)
        await self.settle()

    async def learn_rtt(self, latency: float) -> None:
        """Give the client MIN_RTT_SAMPLES ordinary round trips."""
        for seg in range(1, MIN_RTT_SAMPLES + 1):
            await self.send_one(seg, latency)

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
        self.assertFalse(self.client.slow_mode)

    async def test_every_sent_message_is_confirmed(self):
        """Messages sent while an earlier ping is in flight are covered by their own pings."""
        await self.start()
        for seg in range(1, 4):
            self.client.queue.enqueue_caption(seg, 1, True, f"seg{seg}_final")
        await self.settle()
        self.assertEqual(len(self.ws.sent), 3)

        self.pong(0.001)
        await self.settle()
        self.assertEqual(self.client.acked, self.client.sent)

    async def test_slow_pong_enters_slow_mode_and_sends_finals_only(self):
        """A pong far slower than the client's own round trip means a backlog: finals only."""
        await self.start()
        CLIENTS.add(self.client)
        await self.learn_rtt(0.010)
        self.assertFalse(self.client.slow_mode)

        await self.send_one(MIN_RTT_SAMPLES + 1, 2.0)
        self.assertTrue(self.client.slow_mode)

        seg = MIN_RTT_SAMPLES + 2
        enqueue_live_update("L1", seg, 1, False, "provisional")
        enqueue_live_update("L1", seg, 2, True, "final")
        await self.pong_until_drained(0.010)
        self.assertNotIn("provisional", self.ws.sent)
        self.assertEqual(self.ws.sent[-1], "final")

    async def test_slow_mode_preserves_latest_active_provisional(self):
        """Under slow mode, latest active provisional is preserved and delivered before finalization."""
        await self.start()
        CLIENTS.add(self.client)
        await self.learn_rtt(0.010)

        # Trigger slow mode
        await self.send_one(MIN_RTT_SAMPLES + 1, 2.0)
        self.assertTrue(self.client.slow_mode)

        seg = MIN_RTT_SAMPLES + 2
        # Send provisional rev 1 then rev 2 for active segment
        enqueue_live_update("L1", seg, 1, False, "seg_active_rev1")
        enqueue_live_update("L1", seg, 2, False, "seg_active_rev2")

        # Drain: rev 2 (latest available revision) must be delivered, rev 1 suppressed
        await self.pong_until_drained(0.010)
        self.assertNotIn("seg_active_rev1", self.ws.sent)
        self.assertIn("seg_active_rev2", self.ws.sent)

        # Later, segment finalizes
        enqueue_live_update("L1", seg, 3, True, "seg_active_final")
        await self.pong_until_drained(0.010)
        self.assertEqual(self.ws.sent[-1], "seg_active_final")

    async def test_slow_mode_active_provisional_cleared_by_final_when_flow_blocked(self):
        """When flow-blocked in slow mode, finalization clears obsolete provisional so it is never sent."""
        await self.start()
        CLIENTS.add(self.client)
        await self.learn_rtt(0.010)

        # Trigger slow mode
        await self.send_one(MIN_RTT_SAMPLES + 1, 2.0)
        self.assertTrue(self.client.slow_mode)

        # Exhaust flow window with finals
        for i in range(FLOW_WINDOW):
            self.client.queue.enqueue_caption(100 + i, 1, True, f"blocked_final_{i}")
        await self.settle()
        self.assertTrue(self.client.sent - self.client.acked >= FLOW_WINDOW)

        # Active provisional arrives while window is full
        seg = MIN_RTT_SAMPLES + 2
        enqueue_live_update("L1", seg, 1, False, "unseen_provisional")

        # Segment finalizes before any pong arrives
        enqueue_live_update("L1", seg, 2, True, "seen_final")

        # Now drain
        await self.pong_until_drained(0.010)
        self.assertNotIn("unseen_provisional", self.ws.sent)
        self.assertIn("seen_final", self.ws.sent)

    async def test_lost_packet_delay_is_not_slow(self):
        """A few round trips of extra delay (a retransmitted packet) does not enter slow mode."""
        await self.start()
        await self.learn_rtt(0.200)
        await self.send_one(MIN_RTT_SAMPLES + 1, 0.800)
        self.assertFalse(self.client.slow_mode)

    async def test_fresh_delay_on_fast_network_is_not_slow(self):
        """On a ~1 ms network, a 50 ms hiccup is 50x the minimum but captions stay fresh."""
        await self.start()
        await self.learn_rtt(0.001)
        await self.send_one(MIN_RTT_SAMPLES + 1, 0.050)
        self.assertFalse(self.client.slow_mode)

    async def test_no_classification_before_min_rtt_samples(self):
        """Without enough round-trip samples there is no baseline, so a slow pong is ignored."""
        await self.start()
        await self.send_one(1, 2.0)
        self.assertFalse(self.client.slow_mode)

    async def test_stale_round_trips_enter_slow_mode_without_baseline(self):
        """On a link congested from the start, every pong is slow, so the ratio never fires;
        STALE_PONG_STREAK successive stale round trips enter slow mode instead."""
        await self.start()
        for seg in range(1, STALE_PONG_STREAK):
            await self.send_one(seg, 1.2)
            self.assertFalse(self.client.slow_mode)

        await self.send_one(STALE_PONG_STREAK, 1.2)
        self.assertTrue(self.client.slow_mode)

    async def test_stale_pongs_from_one_stall_count_once(self):
        """Pings delayed by the same stall (e.g. one retransmitted packet) are one observation."""
        await self.start()
        for seg in range(1, STALE_PONG_STREAK + 1):
            self.client.queue.enqueue_caption(seg, 1, True, f"seg{seg}_final")
        await self.settle()
        self.assertEqual(len(self.ws.pings), STALE_PONG_STREAK)

        self.pong(0.7)
        await self.settle()
        self.assertEqual(self.client.stale_pongs, 1)
        self.assertFalse(self.client.slow_mode)

    async def test_fresh_pong_resets_stale_streak(self):
        """Stale pongs must be consecutive: a fresh one in between means the jam was occasional.
        The fresh round trip is 200 ms, so 0.7 s is only 3.5x the minimum and the ratio stays quiet."""
        await self.start()
        seg = 1
        for latency in [0.7] * (STALE_PONG_STREAK - 1) + [0.200] + [0.7] * (STALE_PONG_STREAK - 1):
            await self.send_one(seg, latency)
            seg += 1
        self.assertFalse(self.client.slow_mode)

    async def test_slow_mode_exits_after_confirmed_messages(self):
        """SLOW_EXIT_MESSAGES confirmed messages without another slow pong leave slow mode."""
        await self.start()
        await self.learn_rtt(0.010)
        await self.send_one(MIN_RTT_SAMPLES + 1, 2.0)
        self.assertTrue(self.client.slow_mode)

        first_seg = MIN_RTT_SAMPLES + 2
        for seg in range(first_seg, first_seg + SLOW_EXIT_MESSAGES):
            await self.send_one(seg, 0.010)
        self.assertFalse(self.client.slow_mode)


if __name__ == "__main__":
    unittest.main()
