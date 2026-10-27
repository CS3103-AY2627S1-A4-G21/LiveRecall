/*
 * Working but deliberately naive LiveRecall browser starter.
 *
 * Provided mechanical behavior:
 *   - opens a WebSocket
 *   - sends CLIENT_HELLO
 *   - visibly appends every received CAPTION_UPDATE
 *   - displays whether an update is provisional/final
 *
 * Graded TODOs:
 *   - replace revisions rather than appending duplicates (done)
 *   - maintain >=60 s of finalized local state (done)
 *   - implement 30 s default recall + 15/30/60 s views (done)
 *   - automatic reconnect + correct resume state
 *   - HISTORY merge/deduplication (done)
 *   - usable final UI
 */

const WS_URL = "ws://127.0.0.1:8765";
const statusEl = document.getElementById("status");
const liveEl = document.getElementById("live");
const recallEl = document.getElementById("recall");

let ws;
const liveCaptions = new Map();
const finalizedHistory = new Map();
const HISTORY_SECONDS = 70;
let recallSeconds = 30;

function numericClientId() {
  const key = "liverecall-client-id";
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = String(Math.floor(100000 + Math.random() * 900000));
    sessionStorage.setItem(key, value);
  }
  return Number(value);
}

function pruneCaptions() {
  const cutoff = Date.now() / 1000 - HISTORY_SECONDS;

  for (const [segment, caption] of finalizedHistory) {
    if (caption.source_ts < cutoff) {
      finalizedHistory.delete(segment);
    }
  }

  for (const [segment, caption] of liveCaptions) {
    if (caption.source_ts < cutoff) {
      caption.row.remove();
      liveCaptions.delete(segment);
    }
  }
}

function showRecall() {
  const now = Date.now() / 1000;
  const captions = [...finalizedHistory.entries()]
    .filter(([, caption]) =>
      caption.source_ts >= now - recallSeconds &&
      caption.source_ts <= now + 1
    )
    .sort(([a], [b]) => a - b)
    .map(([, caption]) => caption.text);

  if (captions.length === 0) {
    recallEl.textContent =
      "No finalized captions in the previous " + recallSeconds + " seconds.";
  } else {
    recallEl.textContent = captions.join("\n");
  }
}

function renderCaption(msg) {
  // Do not recreate expired rows from old recovery messages.
  if (msg.source_ts < Date.now() / 1000 - HISTORY_SECONDS) {
    return;
  }

  const current = liveCaptions.get(msg.segment);

  if (current) {
    // Ignore updates to finalized captions and duplicate or older revisions.
    if (current.final || msg.revision <= current.revision) {
      return;
    }
  }

  let row;
  if (current) {
    row = current.row;
  } else {
    row = document.createElement("div");
  }

  row.className = "naive-line";

  let state;
  if (msg.final) {
    state = "FINAL";
  } else {
    state = "PROVISIONAL";
  }

  row.textContent =
    `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;

  if (!current) {
    // Recovered captions may precede captions already displayed.
    let nextRow = null;
    let nextSegment = Infinity;

    for (const [segment, caption] of liveCaptions) {
      if (segment > msg.segment && segment < nextSegment) {
        nextSegment = segment;
        nextRow = caption.row;
      }
    }

    liveEl.insertBefore(row, nextRow);
  }

  liveCaptions.set(msg.segment, {
    revision: msg.revision,
    final: msg.final,
    source_ts: msg.source_ts,
    row
  });

  // Store only recent finalized captions for local recall.
  const cutoff = Date.now() / 1000 - HISTORY_SECONDS;

  if (msg.final && msg.source_ts >= cutoff) {
    finalizedHistory.set(msg.segment, {
      text: msg.text,
      source_ts: msg.source_ts
    });
  }

  liveEl.scrollTop = liveEl.scrollHeight;
}

function connect() {
  statusEl.textContent = "connecting";
  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    statusEl.textContent = "connected";
    ws.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: numericClientId(),
      session: "L1",
      last_segment: 0,       // TODO: resume latest finalized state
      last_revision: 0,
      history_seconds: 60
    }));
  });

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "CAPTION_UPDATE") {
      renderCaption(msg);
    } else if (msg.type === "HISTORY") {
      console.log(`HISTORY with ${msg.items?.length ?? 0} item(s)`, msg);

      for (const item of msg.items) {
        renderCaption(item);
      }
    }

    pruneCaptions();
  });

  ws.addEventListener("close", () => {
    statusEl.textContent = "disconnected";
    // TODO: automatic reconnect after a short delay, using finalized resume state.
  });

  ws.addEventListener("error", () => {
    statusEl.textContent = "connection error";
  });
}

for (const button of document.querySelectorAll("button[data-seconds]")) {
  button.addEventListener("click", () => {
    recallSeconds = Number(button.dataset.seconds);
    pruneCaptions();
    showRecall();
  });
}

// Expire stored captions and live rows without changing the recall snapshot.
setInterval(pruneCaptions, 1000);

connect();