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
 *   - automatic reconnect + correct resume state (done)
 *   - HISTORY merge/deduplication (done)
 *   - usable final UI
 */

const WS_URL = "ws://127.0.0.1:8765";
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 5000;
const RECONNECT_JITTER_MS = 250;
const statusEl = document.getElementById("status");
const liveEl = document.getElementById("live");
const recallEl = document.getElementById("recall");

let ws;
let reconnectAttempts = 0;
const liveCaptions = new Map();
const finalizedHistory = new Map();
const HISTORY_SECONDS = 70;
let recallSeconds = 30;

// Latest finalized state held locally, sent as the resume cursor.
let lastFinal = { segment: 0, revision: 0 };

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

    // Never move the resume cursor backwards.
    if (msg.segment > lastFinal.segment) {
      lastFinal = { segment: msg.segment, revision: msg.revision };
    }
  }

  liveEl.scrollTop = liveEl.scrollHeight;
}

function scheduleReconnect() {
  // Back off exponentially, with jitter so clients do not retry in lockstep.
  const delay =
    Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** reconnectAttempts) +
    Math.random() * RECONNECT_JITTER_MS;
  reconnectAttempts += 1;

  statusEl.textContent =
    `reconnecting in ${(delay / 1000).toFixed(1)} s (attempt ${reconnectAttempts})`;
  setTimeout(connect, delay);
}

function connect() {
  statusEl.textContent = "connecting";
  const socket = new WebSocket(WS_URL);
  ws = socket;
  let openedAt;

  socket.addEventListener("open", () => {
    // Ignore events from a socket that has been replaced.
    if (socket !== ws) {
      return;
    }

    openedAt = performance.now();
    statusEl.textContent = "recovering";
    socket.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: numericClientId(),
      session: "L1",
      last_segment: lastFinal.segment,
      last_revision: lastFinal.revision,
      history_seconds: 60
    }));
  });

  socket.addEventListener("message", (event) => {
    if (socket !== ws) {
      return;
    }

    const msg = JSON.parse(event.data);

    if (msg.type === "CAPTION_UPDATE") {
      renderCaption(msg);
    } else if (msg.type === "HISTORY") {
      for (const item of msg.items) {
        renderCaption(item);
      }

      // Recovery is complete once HISTORY has been applied.
      reconnectAttempts = 0;
      statusEl.textContent = "live";
      console.log(
        `HISTORY with ${msg.items.length} item(s), recovered in ` +
        `${Math.round(performance.now() - openedAt)} ms`,
        msg
      );
    }

    pruneCaptions();
  });

  // The browser always fires close after error, so only close reconnects.
  socket.addEventListener("close", () => {
    if (socket !== ws) {
      return;
    }

    scheduleReconnect();
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