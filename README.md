# Team 21 - LiveRecall

A semantics-aware, resilient real-time lecture captioning and historical recall architecture built on RFC 6455 WebSockets and Python `asyncio`.

---

## Team Members

| Name | Student ID | Main Responsibilities |
|---|---|---|
| Lim Kai Wei |  | Server Architecture, State Ingestion, Deduplication & Queue Management |
| Jansen Ken Pegrasio |  | WebSocket Ping/Pong Flow Window, Latency Tracking & Backpressure Optimization |
| Christopher Chong Jia Cheng |  | Browser Client UI, Reconnect Logic & Local Recall Caching |
| Chen Junyao |  | Test Harness, Linux Traffic Control (tc/netem) Impairments & Benchmarks |

---

## Ubuntu Setup

Tested and verified on a fresh **Ubuntu 22.04 LTS** environment:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iproute2
```

---

## Install

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies (websockets, etc.)
pip install -r requirements.txt
```

---

## Required Server

Run the authoritative LiveRecall server:

```bash
python solution_server.py --port 8765
```

CLI options:
- `--host`: Bind address (default: `0.0.0.0`).
- `--port`: WebSocket listening port (default: `8765`).

---

## Browser Client

The browser client (`client/index.html` and `client/app.js`) connects to `ws://127.0.0.1:8765` by default.

### Running the Browser Client:
1. Start the server (see above).
2. Serve the `client/` directory with Python's HTTP server:
   ```bash
   python3 -m http.server 8000 --directory client
   ```
3. Open `http://localhost:8000` in any modern web browser (Chrome, Firefox, Edge, Safari).
4. Alternatively, open `client/index.html` directly in the browser via file URL.

---

## Public Deterministic Tests

Run all public benchmark suites using the supplied test harness. Each test runs **three independent times** to report median results:

```bash
# T1 - Basic Correctness (20 clients, 20s)
python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem t1

# T2 - Public Scale (100 clients, 40s)
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t2

# T3 - Slow Readers (100 clients, 10% slow @ 500ms delay, 60s)
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --slow-percent 10 --slow-ms 500 --output-stem t3

# T4 - Temporary Disconnect & Reconnect (100 clients, 20% disconnect @ 15s for 5s, 60s)
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
  --output-stem t4

# T5 - Network Impairment (100 clients, 120ms netem delay, 15ms jitter, 1% loss, 40s)
sudo ./network_profiles/delay_loss.sh lo
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t5
sudo ./network_profiles/reset.sh lo

# Bandwidth Challenge (300 clients, 2 Mbit/s bottleneck)
sudo ./network_profiles/bandwidth_2mbit.sh lo
python run_demo.py --clients 300 --duration 40 --runs 3 --output-stem bw300
sudo ./network_profiles/reset.sh lo
```

### Burst Stress Tests (0ms revision gap):
```bash
# Burst 20 clients
python solution_server.py --port 8765 &
python load_clients.py --uri ws://127.0.0.1:8765 --clients 20 --duration 20 --output burst20.csv --seed 3103 --history-seconds 30 &
sleep 1
python caption_source.py --uri ws://127.0.0.1:8765 --segments 22 --revision-delay 0 --segment-gap 0.75 --quiet
wait %2; kill %1
python analyse_results.py burst20.csv --expected-finals 22 --expected-updates 66 --json-output burst20.json

# Burst 100 clients
python solution_server.py --port 8765 &
python load_clients.py --uri ws://127.0.0.1:8765 --clients 100 --duration 40 --output burst100.csv --seed 3103 --history-seconds 30 &
sleep 1
python caption_source.py --uri ws://127.0.0.1:8765 --segments 49 --revision-delay 0 --segment-gap 0.75 --quiet
wait %2; kill %1
python analyse_results.py burst100.csv --expected-finals 49 --expected-updates 147 --json-output burst100.json
```

---

## Mandatory Deterministic Application Demo

To demonstrate all interactive features required by Section 6 of the project specification:

### Step 1: Start Server & Client Server
```bash
# Terminal 1: Start LiveRecall WebSocket Server
python solution_server.py --port 8765

# Terminal 2: Serve Client Web Page
python3 -m http.server 8000 --directory client
```

### Step 2: Open Browser Clients
Open two browser windows side-by-side at `http://localhost:8000`. Both will show `Connection: connected`.

### Step 3: Stream Deterministic Captions
```bash
# Terminal 3: Start deterministic upstream caption source
python caption_source.py --uri ws://127.0.0.1:8765 --segments 30 --revision-delay 0.2 --segment-gap 1.0
```

### Demonstration Checklist:
1. **Live Revision Replacement:** Observe incoming provisional captions (yellow italic badge) updating in-place on the same line as new decodings arrive, locking into bold final text (green badge) without duplicate lines.
2. **What did I miss? (Local Recall):** Click the "What did I miss? (30 s)", "15 s", and "60 s" buttons. Finalized captions from the past window are rendered instantly from the client's local cache without issuing unnecessary network requests.
3. **Late Join:** Open a third browser window midway through the speech stream. It immediately receives recent context via a `HISTORY` message and then continues streaming live captions in real time.
4. **Disconnect & Reconnect Recovery:** Close one browser tab or disconnect Wi-Fi. Reopen or reconnect; the client uses its resume cursor `(last_segment, last_revision)` to perform incremental recovery, recovering strictly missed finals with **zero duplicate captions**.

---

## Design Notes

- **Revision and Deduplication State:** `accept_caption` enforces strict monotonicity. Out-of-order or duplicate provisional revisions ($R \le R_{\text{current}}$) are dropped. Once a segment is finalized ($F = \text{true}$), all further updates for that segment are rejected.
- **Bounded Server History:** `prune_history` bounds server memory by evicting finalized segments older than 60 seconds on every connection and live update. Memory is naturally capped at $\le 80$ segments per session ($\approx 15\text{ KB}$ RAM).
- **Reconnect & Late-Join Recovery:** Clients provide their durable cursor `(last_segment, last_revision)` in `CLIENT_HELLO`. The server streams only segments newer than this cursor within the requested window, achieving sub-3ms recovery ($P_{95} = 2.43\text{ ms}$). User recall is decoupled from the connection resume cursor to prevent duplicate streaming loops.
- **Per-Client Buffering & Flow Control:** Naive WebSocket servers hide hundreds of frames inside the OS kernel TCP send buffer (`SO_SNDBUF`). LiveRecall introduces an RFC 6455 Ping/Pong sliding flow window (`FLOW_WINDOW = 4`). Control frames act as cumulative transport ACKs, exposing socket backpressure to user-space Python memory.
- **Overload Behavior & Trade-offs:** Under strain (`depth >= 15`, `head_age >= 250ms`, `send_ema >= 50ms`, or flow window full), `CoalescingQueue` merges obsolete provisional revisions of the same segment in-place, while strictly preserving final captions. Slow readers are isolated via dual-trigger classification ($10\times$min_rtt and 3-streak $> 500\text{ ms}$ pongs) and gracefully degraded to finals-only delivery. Frozen clients accumulating $> 128$ finals are safely disconnected with code `1013`.
