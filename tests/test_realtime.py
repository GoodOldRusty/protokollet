"""Realtime fast-path logic: segment merging, audio block preparation, and
the failure semantics that guarantee fallback to batch transcription."""

import numpy as np

from realtime import RealtimeTranscriber, TARGET_RATE, merge_segments, prepare_block

# ── merge_segments ────────────────────────────────────────────


def test_merge_interleaves_chronologically():
    mine = [(2.0, "Jag håller med."), (5.0, "Vi kör på det.")]
    others = [(1.0, "Vad tycker ni?"), (3.0, "Bra.")]
    out = merge_segments(mine, others, "Jan")
    assert out == ("Others: Vad tycker ni?\n\n"
                   "Jan: Jag håller med.\n\n"
                   "Others: Bra.\n\n"
                   "Jan: Vi kör på det.")


def test_merge_coalesces_consecutive_same_speaker():
    mine = []
    others = [(1.0, "Hej."), (2.0, "Välkomna.")]
    out = merge_segments(mine, others, "Jan")
    assert out == "Others: Hej. Välkomna."


def test_merge_empty_streams_gives_empty_string():
    assert merge_segments([], [], "Jan") == ""


# ── prepare_block ─────────────────────────────────────────────


def test_prepare_block_downmixes_and_resamples():
    # 1 s of stereo int16 at 48 kHz -> 1 s of mono int16 at 24 kHz
    src = np.zeros(48000 * 2, dtype=np.int16).tobytes()
    out = prepare_block(src, 48000, 2)
    assert len(out) == TARGET_RATE * 2  # int16 mono


def test_prepare_block_passthrough_at_target_rate_mono():
    src = np.arange(TARGET_RATE, dtype=np.int16).tobytes()
    out = prepare_block(src, TARGET_RATE, 1)
    assert out == src


# ── failure semantics ─────────────────────────────────────────


def _transcriber():
    return RealtimeTranscriber("key", "klang/pianissimo", "sv",
                               48000, 2, "test")


def test_stop_without_connection_returns_none():
    rt = _transcriber()  # start() never called: like an offline meeting
    rt.feed(b"\x00\x00" * 1024)
    assert rt.stop(timeout=0.5) is None
    assert rt.failed


def test_feed_after_failure_is_noop():
    rt = _transcriber()
    rt._fail("test")
    rt.feed(b"\x00\x00" * 1024)  # must not raise or enqueue
    assert rt._q.empty()


def test_queue_overflow_flips_failed():
    rt = _transcriber()
    chunk = b"\x00\x00" * 1024
    for _ in range(3000):  # exceeds _QUEUE_MAX with no sender draining
        rt.feed(chunk)
    assert rt.failed


# ── event handling (driven directly, no network) ──────────────


def _event(rt, payload):
    rt._on_message(None, __import__("json").dumps(payload))


def test_segments_use_speech_end_time_not_completion_time():
    # A long utterance commits (speech ends) BEFORE a short one, but its
    # transcript completes AFTER - ordering must follow speech time.
    rt = _transcriber()
    _event(rt, {"type": "input_audio_buffer.committed", "item_id": "long"})
    _event(rt, {"type": "input_audio_buffer.committed", "item_id": "short"})
    _event(rt, {"type": "conversation.item.input_audio_transcription.completed",
                "item_id": "short", "transcript": "Ja, precis."})
    _event(rt, {"type": "conversation.item.input_audio_transcription.completed",
                "item_id": "long", "transcript": "En lång fråga om rapporterna?"})
    texts = [t for _, t in sorted(rt._segments)]
    assert texts == ["En lång fråga om rapporterna?", "Ja, precis."]


def test_final_commit_ack_via_committed_event():
    rt = _transcriber()
    rt._commit_sent = True
    _event(rt, {"type": "input_audio_buffer.committed", "item_id": "tail"})
    assert rt._final_acked
    assert not rt.failed


def test_final_commit_ack_via_benign_empty_buffer_error():
    rt = _transcriber()
    rt._commit_sent = True
    _event(rt, {"type": "error",
                "error": {"message": "input audio buffer is empty"}})
    assert rt._final_acked
    assert not rt.failed


def test_server_error_before_stop_flips_failed():
    rt = _transcriber()
    _event(rt, {"type": "error", "error": {"message": "internal error"}})
    assert rt.failed


def test_segment_transcription_failure_flips_failed():
    rt = _transcriber()
    _event(rt, {"type": "conversation.item.input_audio_transcription.failed",
                "item_id": "x", "error": {"message": "boom"}})
    assert rt.failed
