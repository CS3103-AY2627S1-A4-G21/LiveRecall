#!/usr/bin/env python3
"""Unit tests for CoalescingQueue: Bounded per-client delivery & semantic coalescing."""

import asyncio
import time
import unittest

from solution_server import (
    CoalescingQueue,
    PendingItem,
    DEFAULT_QUEUE_CAPACITY,
    OVERLOAD_WATERMARK,
)


class TestCoalescingQueue(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_under_normal_load(self):
        """Under normal conditions (< watermark), queue preserves strict FIFO ordering."""
        q = CoalescingQueue(maxsize=10, overload_watermark=5)
        self.assertFalse(q.is_strained())

        # Enqueue 3 provisional updates
        q.enqueue_caption(1, 1, False, "seg1_rev1")
        q.enqueue_caption(2, 1, False, "seg2_rev1")
        q.enqueue_caption(3, 1, False, "seg3_rev1")

        self.assertEqual(q.qsize(), 3)
        self.assertEqual(await q.get(), "seg1_rev1")
        q.task_done()
        self.assertEqual(await q.get(), "seg2_rev1")
        q.task_done()
        self.assertEqual(await q.get(), "seg3_rev1")
        q.task_done()
        self.assertEqual(q.qsize(), 0)

    async def test_in_place_coalescing(self):
        """Under strain, newer revisions replace an unsent provisional revision in-place."""
        q = CoalescingQueue(maxsize=10, overload_watermark=5)
        # Simulate slow transport sends so the queue is strained
        q.update_send_metric(1.0)

        # Enqueue seg 1 rev 1, then seg 2 rev 1
        q.enqueue_caption(1, 1, False, "seg1_rev1")
        q.enqueue_caption(2, 1, False, "seg2_rev1")
        self.assertEqual(q.qsize(), 2)

        # Seg 1 rev 2 arrives before seg 1 rev 1 is dequeued
        q.enqueue_caption(1, 2, False, "seg1_rev2")
        # Size must remain 2 (in-place replacement)
        self.assertEqual(q.qsize(), 2)

        # Seg 1 rev 3 (final) arrives
        q.enqueue_caption(1, 3, True, "seg1_rev3_final")
        self.assertEqual(q.qsize(), 2)

        # Dequeue must yield seg 1 rev 3 (final) first, preserving queue position relative to seg 2!
        msg1 = await q.get()
        q.task_done()
        self.assertEqual(msg1, "seg1_rev3_final")

        msg2 = await q.get()
        q.task_done()
        self.assertEqual(msg2, "seg2_rev1")

    async def test_burst_without_strain_keeps_every_revision(self):
        """A healthy client receives every revision, even when a burst queues them before the sender runs."""
        q = CoalescingQueue(maxsize=10, overload_watermark=5)

        q.enqueue_caption(1, 1, False, "seg1_rev1")
        q.enqueue_caption(1, 2, False, "seg1_rev2")
        q.enqueue_caption(1, 3, True, "seg1_rev3_final")
        self.assertEqual(q.qsize(), 3)

        items = [await q.get(), await q.get(), await q.get()]
        self.assertEqual(items, ["seg1_rev1", "seg1_rev2", "seg1_rev3_final"])

    async def test_coalescing_after_sending_older_revision(self):
        """Sending an older revision must not stop a newer queued revision of the same segment from coalescing."""
        q = CoalescingQueue(maxsize=10, overload_watermark=5)

        # Burst while healthy: both revisions are queued
        q.enqueue_caption(1, 1, False, "seg1_rev1")
        q.enqueue_caption(1, 2, False, "seg1_rev2")
        self.assertEqual(await q.get(), "seg1_rev1")
        q.task_done()

        # Strain begins; the final replaces the still-unsent rev 2
        q.update_send_metric(1.0)
        q.enqueue_caption(1, 3, True, "seg1_rev3_final")
        self.assertEqual(q.qsize(), 1)
        self.assertEqual(await q.get(), "seg1_rev3_final")

    async def test_newer_revision_never_overtakes_queued_final(self):
        """Once a final is queued, later updates of that segment must not coalesce into an earlier slot."""
        q = CoalescingQueue(maxsize=10, overload_watermark=5)
        q.enqueue_caption(1, 1, False, "seg1_rev1")
        q.enqueue_caption(1, 2, True, "seg1_rev2_final")

        q.update_send_metric(1.0)
        q.enqueue_caption(1, 3, True, "seg1_rev3_final")

        items = [await q.get(), await q.get(), await q.get()]
        self.assertEqual(items, ["seg1_rev1", "seg1_rev2_final", "seg1_rev3_final"])

    async def test_final_captions_never_dropped(self):
        """Final captions are durable state and must never be evicted, even at capacity."""
        # Create a tiny queue of size 3
        q = CoalescingQueue(maxsize=3, overload_watermark=2)

        # Enqueue 2 finals and 1 provisional
        q.enqueue_caption(1, 3, True, "final_1")
        q.enqueue_caption(2, 1, False, "prov_2")
        q.enqueue_caption(3, 3, True, "final_3")
        self.assertEqual(q.qsize(), 3)

        # Now queue is full (size 3). Enqueue another final caption.
        # It must evict prov_2, preserving final_1 and final_3!
        q.enqueue_caption(4, 3, True, "final_4")
        self.assertEqual(q.qsize(), 3)

        # All 3 items in queue must be finals (final_1, final_3, final_4)
        items = [await q.get(), await q.get(), await q.get()]
        self.assertEqual(items, ["final_1", "final_3", "final_4"])

    async def test_provisional_dropped_when_all_finals(self):
        """When queue is full of finals, new provisional updates are discarded rather than evicting finals."""
        q = CoalescingQueue(maxsize=2, overload_watermark=1)
        q.enqueue_caption(1, 3, True, "final_1")
        q.enqueue_caption(2, 3, True, "final_2")
        self.assertEqual(q.qsize(), 2)

        # Enqueue provisional update when full of finals
        q.enqueue_caption(3, 1, False, "prov_3")
        self.assertEqual(q.qsize(), 2)

        # Dequeue must still yield only final_1 and final_2
        self.assertEqual(await q.get(), "final_1")
        self.assertEqual(await q.get(), "final_2")

    async def test_generic_put_nowait_for_history(self):
        """put_nowait correctly enqueues HISTORY or control messages."""
        q = CoalescingQueue(maxsize=10, overload_watermark=5)
        q.put_nowait('{"type": "HISTORY", "items": []}')
        self.assertEqual(q.qsize(), 1)
        self.assertEqual(await q.get(), '{"type": "HISTORY", "items": []}')
        q.task_done()

    async def test_strain_detection_and_hysteresis(self):
        """Test strain detection based on watermark, head lag, and send duration."""
        q = CoalescingQueue(maxsize=20, overload_watermark=5)
        self.assertFalse(q.is_strained())

        # Test depth trigger
        for i in range(1, 6):
            q.enqueue_caption(i, 1, False, f"seg_{i}")
        self.assertTrue(q.is_strained())

        # Drain to test hysteresis recovery: must drain to <= 5 to recover
        while q.qsize() > 5:
            await q.get()
            q.task_done()
        # At depth 5, if items are fresh, it should de-escalate
        self.assertFalse(q.is_strained())

        # Test send duration EMA trigger
        q.update_send_metric(0.080)  # 80ms send time
        q.update_send_metric(0.080)
        self.assertTrue(q.is_strained())


if __name__ == "__main__":
    unittest.main()

