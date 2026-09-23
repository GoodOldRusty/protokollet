"""Realtime transcription fast path via Berget's OpenAI-compatible realtime
WebSocket (klang/pianissimo). One transcriber per capture stream.

Failure policy: any problem — connect, send, backlog, server error — flips
`failed` and the caller falls back to the batch kb-whisper pipeline, so a
realtime hiccup can never cost a meeting. Nothing here may raise into the
capture thread."""

import base64
import json
import logging
import queue
import threading
import time

import numpy as np
import websocket

log = logging.getLogger("recorder")

REALTIME_URL = "wss://api.berget.ai/v1/realtime"
TARGET_RATE = 24000

# Raw capture chunks are ~23 ms each; 2048 queued chunks is ~45 s of audio.
# A backlog beyond that means the network can't keep up - fail to batch.
_QUEUE_MAX = 2048


class RealtimeTranscriber:
    """Streams one capture stream to the realtime API, collects completed
    transcript segments with arrival timestamps for cross-stream merging."""

    def __init__(self, api_key: str, model: str, language: str,
                 src_rate: int, src_channels: int, label: str):
        self._api_key = api_key
        self._model = model
        self._language = language
        self._src_rate = src_rate
        self._src_channels = src_channels
        self._label = label

        self.failed = False
        self._segments = []    # (speech-end time, text)
        self._commit_times = {}  # item_id -> committed-event arrival time
        self._committed = set()
        self._completed = set()
        self._commit_sent = False  # the final flush commit has been sent
        self._final_acked = False  # ...and the server has answered it
        self._q = queue.Queue(maxsize=_QUEUE_MAX)
        self._ws = None
        self._sender = None
        self._opened = threading.Event()
        self._stopping = False

    # ── lifecycle ────────────────────────────────────────────

    def start(self):
        self._ws = websocket.WebSocketApp(
            REALTIME_URL,
            header={"Authorization": f"Bearer {self._api_key}"},
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        threading.Thread(target=self._ws.run_forever, daemon=True,
                         name=f"rt-ws-{self._label}").start()

    def feed(self, data: bytes):
        """Called from the capture thread for every chunk. Never raises."""
        if self.failed:
            return
        try:
            self._q.put_nowait(data)
        except queue.Full:
            self._fail("audio backlog - network too slow")
        except Exception as e:
            self._fail(f"feed: {e}")

    def stop(self, timeout: float = 10.0):
        """Flush remaining audio, commit, await final transcripts.
        Returns [(timestamp, text), ...] on success or None on failure."""
        self._stopping = True
        deadline = time.monotonic() + timeout

        if not self._opened.is_set():
            self._fail("never connected")
        else:
            try:
                self._q.put(None, timeout=1)  # sentinel: flush + commit
            except queue.Full:
                self._fail("audio backlog at stop")

        # Success needs all three: sender drained and exited, the final
        # commit acknowledged by the server (its committed event or a benign
        # empty-buffer error), and a transcript for every committed segment.
        # Anything less at the deadline is a failure - a truncated transcript
        # reported as success would silently lose the end of the meeting.
        while not self.failed and time.monotonic() < deadline:
            sender_done = self._sender is None or not self._sender.is_alive()
            if (sender_done and self._final_acked
                    and self._committed <= self._completed):
                break
            time.sleep(0.2)
        else:
            if not self.failed:
                sender_alive = (self._sender is not None
                                and self._sender.is_alive())
                self._fail(
                    "timed out waiting for final transcripts (sender_alive="
                    f"{sender_alive}, commit_sent={self._commit_sent}, "
                    f"final_acked={self._final_acked}, "
                    f"committed={len(self._committed)}, "
                    f"completed={len(self._completed)}, "
                    f"segments={len(self._segments)})")

        try:
            self._ws.close()
        except Exception:
            pass

        if self.failed:
            return None
        return list(self._segments)

    def abort(self):
        """Close immediately without waiting for transcripts (crash path)."""
        self._stopping = True
        self.failed = True
        try:
            # Wake a sender blocked on the queue so the thread can exit.
            self._q.put_nowait(None)
        except queue.Full:
            pass
        try:
            self._ws.close()
        except Exception:
            pass

    # ── internals ────────────────────────────────────────────

    def _fail(self, why: str):
        if not self.failed:
            self.failed = True
            log.warning("Realtime %s stream: falling back to batch (%s)",
                        self._label, why)

    def _on_open(self, ws):
        try:
            ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm",
                                       "rate": TARGET_RATE},
                            "transcription": {"model": self._model,
                                              "language": self._language},
                        },
                    },
                },
            }))
            self._sender = threading.Thread(target=self._send_loop,
                                            daemon=True,
                                            name=f"rt-send-{self._label}")
            self._sender.start()
            self._opened.set()
        except Exception as e:
            self._fail(f"session setup: {e}")

    def _on_message(self, ws, msg):
        try:
            ev = json.loads(msg)
            etype = ev.get("type", "")
            if etype == "conversation.item.input_audio_transcription.completed":
                text = (ev.get("transcript") or "").strip()
                item_id = ev.get("item_id")
                if text:
                    # Timestamp with the segment's speech-end (committed
                    # event) time, not transcription-completion time: a long
                    # utterance finishes transcribing after a short reply to
                    # it, and completion order would misorder the dialogue.
                    ts = self._commit_times.get(item_id, time.monotonic())
                    self._segments.append((ts, text))
                self._completed.add(item_id)
            elif etype == "conversation.item.input_audio_transcription.failed":
                self._fail(f"segment transcription failed: {str(ev)[:200]}")
            elif etype == "input_audio_buffer.committed":
                item_id = ev.get("item_id")
                self._committed.add(item_id)
                self._commit_times[item_id] = time.monotonic()
                # Messages are processed in order, so the first committed
                # event after our flush commit was sent acknowledges it.
                if self._commit_sent:
                    self._final_acked = True
            elif etype == "error":
                err = str(ev.get("error", ev)).lower()
                if self._commit_sent and ("empty" in err or "too small" in err):
                    # Committing a silent tail buffer at stop is benign and
                    # doubles as the final-commit acknowledgement.
                    self._final_acked = True
                    return
                self._fail(f"server error: {str(ev)[:200]}")
        except Exception as e:
            self._fail(f"event handling: {e}")

    def _on_error(self, ws, err):
        self._fail(f"websocket: {err}")

    def _on_close(self, ws, code, reason):
        if not self._stopping:
            self._fail(f"connection closed ({code})")

    def _send_loop(self):
        # 1 s of raw source audio per API message.
        block_bytes = self._src_rate * self._src_channels * 2
        buf = bytearray()
        try:
            while True:
                item = self._q.get()
                if item is None:
                    if buf:
                        self._send_block(bytes(buf))
                    # Flag first: the server's answer must not race the flag.
                    self._commit_sent = True
                    self._ws.send(json.dumps(
                        {"type": "input_audio_buffer.commit"}))
                    return
                buf += item
                while len(buf) >= block_bytes:
                    self._send_block(bytes(buf[:block_bytes]))
                    del buf[:block_bytes]
        except Exception as e:
            self._fail(f"send: {e}")

    def _send_block(self, raw: bytes):
        pcm = prepare_block(raw, self._src_rate, self._src_channels)
        self._ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode(),
        }))


def prepare_block(raw: bytes, src_rate: int, src_channels: int) -> bytes:
    """Downmix interleaved int16 to mono and resample to TARGET_RATE."""
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if src_channels > 1:
        arr = arr.reshape(-1, src_channels).mean(axis=1)
    if src_rate != TARGET_RATE:
        from scipy.signal import resample_poly
        arr = resample_poly(arr, TARGET_RATE, src_rate)
    return np.clip(arr, -32768, 32767).astype(np.int16).tobytes()


def merge_segments(mine: list, others: list, my_name: str = "Me") -> str:
    """Merge two streams' (timestamp, text) segments into a chronological
    dialogue, coalescing consecutive lines from the same speaker."""
    tagged = ([(ts, my_name, text) for ts, text in mine]
              + [(ts, "Others", text) for ts, text in others])
    tagged.sort(key=lambda x: x[0])
    lines = []
    for _, who, text in tagged:
        if lines and lines[-1][0] == who:
            lines[-1] = (who, lines[-1][1] + " " + text)
        else:
            lines.append((who, text))
    return "\n\n".join(f"{who}: {text}" for who, text in lines)
