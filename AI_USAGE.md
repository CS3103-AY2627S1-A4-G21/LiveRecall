# AI / Coding-Assistant Usage

## Tools used

The team utilized generative AI coding assistants (Google Antigravity, Anthropic Claude, and OpenAI ChatGPT) across the development lifecycle for:
- Interactive pair-programming and refactoring of asynchronous Python (`asyncio`, `websockets`) and client JavaScript.
- Generating and structuring unit test suites (`test_flow_control.py`, `test_caption_handling.py`, and `test_coalescing_queue.py`).
- Performing systematic code reviews on pull requests to identify edge cases, race conditions, and specification ambiguities.
- Parsing and aggregating benchmark log outputs into median statistical tables.

## One useful suggestion

**RFC 6455 Ping/Pong Sliding Flow Window (`FLOW_WINDOW = 4`)**
- **The Suggestion:** When addressing slow-reader lag in Issue #4, the assistant suggested utilizing RFC 6455 WebSocket control frames (Ping and Pong) as cumulative transport-level acknowledgements to bound in-flight messages (`client.sent - client.acked < FLOW_WINDOW`) without modifying client-side application logic.
- **Why it materially helped:** In asynchronous WebSocket servers, `await ws.send()` completes as soon as data enters the OS kernel TCP send buffer (`SO_SNDBUF`, $\sim 128\text{ KB}$). This created an OS buffer blind spot where the server believed clients were consuming smoothly, but slow clients accumulated over 600 frames of obsolete revisions inside the kernel, leading to massive tail latency ($P_{99} > 24\text{ s}$) and dropped final captions. The flow window halted the sender coroutine, forcing the backlog into the server's user-space `CoalescingQueue` where obsolete revisions could be replaced in-place.
- **Verification:** Verified via the mandatory public benchmark suite (`T3` with 10% slow readers @ 500ms delay). The flow window elevated final caption completeness from **95.13% to 98.68%** and reduced $P_{99}$ latency from **24.02s to 8.82s**. Combined with RTT-relative slow mode, completeness reached **99.21%**, passing the mandatory $\ge 99\%$ correctness gate.

## One suggestion that was wrong, inefficient, or required modification

**Proposed Reduction of `SLOW_EXIT_MESSAGES` to 6 (Mode Flapping)**
- **The Suggestion:** During the critical review of PR #26, the assistant observed that in slow mode, clients receive only final captions ($\approx 1.25\text{ finals/s}$). It calculated that waiting for `SLOW_EXIT_MESSAGES = 50` confirmed messages would require $\approx 40\text{ seconds}$ to exit slow mode, which is irreversible in 20-second runs (`T1`). It proposed lowering `SLOW_EXIT_MESSAGES` from 50 to 6 ($\approx 5\text{ seconds}$).
- **The Problem:** When evaluated experimentally on the `T3` benchmark, setting `SLOW_EXIT_MESSAGES = 6` caused severe **mode flapping (hysteresis thrashing)**. A slow client consuming at 500 ms per message easily kept up with 6 final captions, triggering premature exit from slow mode. The server immediately resumed pushing high-rate provisional updates ($\approx 35\text{ updates/s}$), instantly saturating the client's buffers and causing final captions to be dropped before slow mode could re-engage. As a result, T3 final caption completeness dropped below the required 99% threshold.
- **The Correction:** The team rejected the proposed change and preserved `SLOW_EXIT_MESSAGES = 50`. Normal clients on local and impaired networks never enter slow mode in the first place because detection scales to $10 \times \mathrm{min_rtt}$  and requires latency $> 250\text{ ms}$ (verified by 100% normal coverage in T1, T2, T4, and 99.24% in T5). Retaining 50 messages stabilized genuinely slow readers, preventing hysteresis thrashing and maintaining **99.21% completeness**.
