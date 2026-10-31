#!/usr/bin/env python3
"""Comprehensive test suite for Issue #5: Source caption handling."""

import asyncio
import json
import time
import unittest
import websockets
from solution_server import STATE, ServerState, SessionState, accept_caption, prune_history


class TestCaptionHandling(unittest.TestCase):
    def setUp(self):
        STATE.reset()

    def test_basic_monotonic_revisions(self):
        """Test normal revision progression: rev 1 -> rev 2 -> rev 3 (final)."""
        now = 1000.0
        m1 = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 1,
            "revision": 1,
            "source_ts": now,
            "final": False,
            "text": "Hello",
        }
        m2 = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 1,
            "revision": 2,
            "source_ts": now + 0.2,
            "final": False,
            "text": "Hello world",
        }
        m3 = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 1,
            "revision": 3,
            "source_ts": now + 0.4,
            "final": True,
            "text": "Hello world!",
        }

        self.assertTrue(accept_caption(m1, now=now))
        session = STATE.get_session("L1")
        self.assertEqual(session.segments[1].revision, 1)
        self.assertFalse(session.segments[1].final)
        self.assertEqual(session.latest_active_segment, 1)

        self.assertTrue(accept_caption(m2, now=now + 0.2))
        self.assertEqual(session.segments[1].revision, 2)
        self.assertFalse(session.segments[1].final)
        self.assertEqual(session.latest_active_segment, 1)

        self.assertTrue(accept_caption(m3, now=now + 0.4))
        self.assertEqual(session.segments[1].revision, 3)
        self.assertTrue(session.segments[1].final)
        self.assertIsNone(session.latest_active_segment)
        self.assertEqual(len(session.finalized_history), 1)
        self.assertEqual(session.finalized_history[0].text, "Hello world!")

    def test_ignore_duplicate_and_older_revisions(self):
        """Older and duplicate revisions must be rejected (return False)."""
        now = 1000.0
        m1 = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 2, "source_ts": now, "final": False, "text": "Step 2"}
        self.assertTrue(accept_caption(m1, now=now))

        # Duplicate revision 2
        dup = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 2, "source_ts": now + 0.1, "final": False, "text": "Step 2 dup"}
        self.assertFalse(accept_caption(dup, now=now + 0.1))

        # Older revision 1
        older = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 1, "source_ts": now + 0.2, "final": False, "text": "Step 1"}
        self.assertFalse(accept_caption(older, now=now + 0.2))

        # Verify state was not modified
        session = STATE.get_session("L1")
        self.assertEqual(session.segments[1].revision, 2)
        self.assertEqual(session.segments[1].text, "Step 2")

    def test_prevent_provisional_overwriting_finalized(self):
        """Finalized segment state must never be overwritten by provisional state."""
        now = 1000.0
        final_msg = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 5,
            "revision": 3,
            "source_ts": now,
            "final": True,
            "text": "Completed sentence.",
        }
        self.assertTrue(accept_caption(final_msg, now=now))

        # Provisional update with lower revision
        p_low = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 5, "revision": 2, "source_ts": now + 0.1, "final": False, "text": "Older provisional"}
        self.assertFalse(accept_caption(p_low, now=now + 0.1))

        # Provisional update with same revision
        p_same = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 5, "revision": 3, "source_ts": now + 0.2, "final": False, "text": "Same revision provisional"}
        self.assertFalse(accept_caption(p_same, now=now + 0.2))

        # Provisional update with higher revision
        p_high = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 5, "revision": 4, "source_ts": now + 0.3, "final": False, "text": "Higher revision provisional"}
        self.assertFalse(accept_caption(p_high, now=now + 0.3))

        # Duplicate final update
        dup_final = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 5, "revision": 3, "source_ts": now + 0.4, "final": True, "text": "Completed sentence duplicate"}
        self.assertFalse(accept_caption(dup_final, now=now + 0.4))

        session = STATE.get_session("L1")
        self.assertEqual(session.segments[5].revision, 3)
        self.assertTrue(session.segments[5].final)
        self.assertEqual(session.segments[5].text, "Completed sentence.")

    def test_variable_revision_counts(self):
        """Test revision counts other than 3: e.g. single-revision and 5-revision segments."""
        now = 1000.0
        # Segment 1: single final revision
        s1 = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 1, "source_ts": now, "final": True, "text": "Instant sentence."}
        self.assertTrue(accept_caption(s1, now=now))

        # Segment 2: 5 revisions
        for rev in range(1, 6):
            is_final = (rev == 5)
            msg = {
                "type": "CAPTION_UPDATE",
                "session": "L1",
                "segment": 2,
                "revision": rev,
                "source_ts": now + rev,
                "final": is_final,
                "text": f"Word count {rev}",
            }
            self.assertTrue(accept_caption(msg, now=now + rev))

        session = STATE.get_session("L1")
        self.assertEqual(len(session.finalized_history), 2)
        self.assertEqual(session.segments[1].revision, 1)
        self.assertEqual(session.segments[2].revision, 5)

    def test_extra_fields_preserved(self):
        """Extra JSON fields must be accepted and preserved without crashing."""
        now = 1000.0
        msg = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 1,
            "revision": 1,
            "source_ts": now,
            "final": True,
            "text": "Hello world",
            "test_phase": "warmup",
            "speaker_id": "prof_x",
            "extra_score": 0.99,
        }
        self.assertTrue(accept_caption(msg, now=now))
        session = STATE.get_session("L1")
        stored = session.segments[1].raw_msg
        self.assertEqual(stored.get("test_phase"), "warmup")
        self.assertEqual(stored.get("speaker_id"), "prof_x")
        self.assertEqual(stored.get("extra_score"), 0.99)

    def test_history_window_and_pruning(self):
        """Bounded history: entries older than retention window (75s) are pruned."""
        session = SessionState("L1", max_history_seconds=75.0)

        # Emit 100 segments, 1 segment per second: t=1000 to t=1099
        start_t = 1000.0
        for i in range(1, 101):
            ts = start_t + i
            msg = {
                "type": "CAPTION_UPDATE",
                "session": "L1",
                "segment": i,
                "revision": 1,
                "source_ts": ts,
                "final": True,
                "text": f"Sentence {i}",
            }
            session.accept_caption(msg, now=ts)

        # At t=1100, retention cutoff is 1100 - 75 = 1025.
        # Segments with ts < 1025 (segments 1 to 24) should have been pruned!
        # Segments 25 to 100 (76 segments) should be retained.
        self.assertNotIn(1, session.segments)
        self.assertNotIn(24, session.segments)
        self.assertIn(25, session.segments)
        self.assertIn(100, session.segments)

        self.assertEqual(session.oldest_retained_segment, 24)
        self.assertEqual(len(session.finalized_history), 76)
        self.assertEqual(session.finalized_history[0].segment, 25)
        self.assertEqual(session.finalized_history[-1].segment, 100)

        # An incoming update for already-pruned segment 20 must be rejected
        late_msg = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 20,
            "revision": 2,
            "source_ts": 1100.0,
            "final": True,
            "text": "Late segment 20 update",
        }
        self.assertFalse(session.accept_caption(late_msg, now=1100.0))

    def test_preserves_latest_active_segment_during_pruning(self):
        """Active provisional segment is retained even if its source_ts is old."""
        session = SessionState("L1", max_history_seconds=75.0)
        # Segment 1 starts at t=1000 and remains provisional
        p_msg = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 1,
            "revision": 1,
            "source_ts": 1000.0,
            "final": False,
            "text": "Slow provisional speech...",
        }
        session.accept_caption(p_msg, now=1000.0)

        # Time advances to t=1100 (100s later)
        session.prune_history(now=1100.0)

        # Segment 1 must still be retained as latest_active_segment
        self.assertEqual(session.latest_active_segment, 1)
        self.assertIn(1, session.segments)

    def test_idle_source_expiry(self):
        """When the source is idle, time advances and history is safely pruned."""
        session = SessionState("L1", max_history_seconds=75.0)
        t0 = 1000.0
        msg = {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 1,
            "revision": 1,
            "source_ts": t0,
            "final": True,
            "text": "Only sentence before pause.",
        }
        session.accept_caption(msg, now=t0)
        self.assertEqual(len(session.finalized_history), 1)

        # Source goes idle; periodic prune runs at t0 + 40s (within 75s window)
        session.prune_history(now=t0 + 40.0)
        self.assertEqual(len(session.finalized_history), 1)

        # Source remains idle; periodic prune runs at t0 + 80s (exceeding 75s window)
        session.prune_history(now=t0 + 80.0)
        self.assertEqual(len(session.finalized_history), 0)
        self.assertNotIn(1, session.segments)
        self.assertEqual(session.oldest_retained_segment, 1)

    def test_multi_session_isolation(self):
        """Different sessions must have isolated segment state and history."""
        now = 1000.0
        m_l1 = {"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 1, "source_ts": now, "final": True, "text": "L1 text"}
        m_l2 = {"type": "CAPTION_UPDATE", "session": "L2", "segment": 1, "revision": 1, "source_ts": now, "final": False, "text": "L2 text"}

        self.assertTrue(accept_caption(m_l1, now=now))
        self.assertTrue(accept_caption(m_l2, now=now))

        s_l1 = STATE.get_session("L1")
        s_l2 = STATE.get_session("L2")

        self.assertTrue(s_l1.segments[1].final)
        self.assertFalse(s_l2.segments[1].final)
        self.assertEqual(len(s_l1.finalized_history), 1)
        self.assertEqual(len(s_l2.finalized_history), 0)


class TestWebSocketServerIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_server_broadcasts_only_accepted_updates(self):
        """End-to-end WebSocket test: server ignores stale/duplicate updates and does not broadcast them."""
        import asyncio
        import json
        import websockets
        from solution_server import handler

        STATE.reset()
        port = 8789
        async with websockets.serve(handler, "127.0.0.1", port):
            uri = f"ws://127.0.0.1:{port}"

            # 1. Connect client
            async with websockets.connect(uri) as client_ws:
                await client_ws.send(json.dumps({
                    "type": "CLIENT_HELLO",
                    "client_id": 1,
                    "session": "L1",
                    "last_segment": 0,
                    "last_revision": 0,
                    "history_seconds": 30,
                }))
                history_raw = await asyncio.wait_for(client_ws.recv(), timeout=2.0)
                history = json.loads(history_raw)
                self.assertEqual(history.get("type"), "HISTORY")

                # 2. Connect source
                async with websockets.connect(uri) as source_ws:
                    await source_ws.send(json.dumps({
                        "type": "SOURCE_HELLO",
                        "session": "L1",
                    }))

                    # Helper to send and collect received updates on client
                    async def send_source(msg: dict):
                        await source_ws.send(json.dumps(msg))

                    now = time.time()
                    # Message 1: valid update
                    await send_source({"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 1, "source_ts": now, "final": False, "text": "Part 1"})
                    received_raw = await asyncio.wait_for(client_ws.recv(), timeout=2.0)
                    r1 = json.loads(received_raw)
                    self.assertEqual(r1["segment"], 1)
                    self.assertEqual(r1["revision"], 1)

                    # Message 2: duplicate update (should be rejected and NOT broadcast)
                    await send_source({"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 1, "source_ts": now + 0.1, "final": False, "text": "Part 1 dup"})

                    # Message 3: valid final revision 2
                    await send_source({"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 2, "source_ts": now + 0.2, "final": True, "text": "Part 1 completed."})

                    # The next message client receives must be revision 2, NOT the duplicate revision 1!
                    received_raw2 = await asyncio.wait_for(client_ws.recv(), timeout=2.0)
                    r2 = json.loads(received_raw2)
                    self.assertEqual(r2["segment"], 1)
                    self.assertEqual(r2["revision"], 2)
                    self.assertTrue(r2["final"])

                    # Message 4: stale update (revision 1) - must be rejected
                    await send_source({"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 1, "source_ts": now + 0.3, "final": False, "text": "Old"})

                    # Message 5: provisional attempting to overwrite finalized - must be rejected
                    await send_source({"type": "CAPTION_UPDATE", "session": "L1", "segment": 1, "revision": 3, "source_ts": now + 0.4, "final": False, "text": "Provisional over final"})

                    # Message 6: next valid segment
                    await send_source({"type": "CAPTION_UPDATE", "session": "L1", "segment": 2, "revision": 1, "source_ts": now + 0.5, "final": True, "text": "Segment 2"})

                    # Client must receive segment 2 directly
                    received_raw3 = await asyncio.wait_for(client_ws.recv(), timeout=2.0)
                    r3 = json.loads(received_raw3)
                    self.assertEqual(r3["segment"], 2)
                    self.assertEqual(r3["revision"], 1)
                    self.assertTrue(r3["final"])

                    # Verify SOURCE_DONE is handled gracefully without crashing
                    await source_ws.send(json.dumps({"type": "SOURCE_DONE"}))
                    await asyncio.sleep(0.1)

    async def test_client_hello_cursor_tolerance(self):
        """Test resume cursor tolerance for omitted revision and invalid inputs (Issue #21)."""
        from solution_server import handler

        STATE.reset()
        port = 8790
        async with websockets.serve(handler, "127.0.0.1", port):
            uri = f"ws://127.0.0.1:{port}"

            # 1. Connect with last_segment > 0 and omitted last_revision (should succeed, not close with 1008)
            async with websockets.connect(uri) as client_ws:
                await client_ws.send(json.dumps({
                    "type": "CLIENT_HELLO",
                    "client_id": 101,
                    "session": "L1",
                    "last_segment": 5,
                }))
                history_raw = await asyncio.wait_for(client_ws.recv(), timeout=2.0)
                history = json.loads(history_raw)
                self.assertEqual(history.get("type"), "HISTORY")

            # 2. Connect with last_segment: 0 and last_revision: 5 (should normalize to (0, 0) and succeed)
            async with websockets.connect(uri) as client_ws:
                await client_ws.send(json.dumps({
                    "type": "CLIENT_HELLO",
                    "client_id": 102,
                    "session": "L1",
                    "last_segment": 0,
                    "last_revision": 5,
                }))
                history_raw = await asyncio.wait_for(client_ws.recv(), timeout=2.0)
                history = json.loads(history_raw)
                self.assertEqual(history.get("type"), "HISTORY")

            # 3. Connect with negative cursor (should be rejected with 1008)
            with self.assertRaises(websockets.exceptions.ConnectionClosed) as ctx:
                async with websockets.connect(uri) as client_ws:
                    await client_ws.send(json.dumps({
                        "type": "CLIENT_HELLO",
                        "client_id": 103,
                        "session": "L1",
                        "last_segment": -1,
                    }))
                    await client_ws.recv()
            self.assertEqual(ctx.exception.rcvd.code, 1008)


if __name__ == "__main__":
    unittest.main()
