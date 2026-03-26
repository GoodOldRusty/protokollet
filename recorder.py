#!/usr/bin/env python3
"""
Meeting Recorder
Auto-detects Teams calls via Windows audio session.
Records loopback + mic separately, transcribes with Whisper,
produces timestamped speaker-labeled transcript.
Runs as a Windows system tray application.
"""

import json
import shutil
import sys
import time
import wave
import threading
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
import whisper
from pycaw.pycaw import AudioUtilities

log = logging.getLogger("recorder")

# ── Config ────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"
EXAMPLE_CONFIG_PATH = Path(__file__).parent / "config.example.json"

DEFAULTS = {
    "whisper_model": "large-v3",
    "language": "sv",
    "keep_audio": False,
    "poll_seconds": 5,
    "min_seconds": 30,
    "output_dir": "~/Recordings",
}


def load_config() -> dict:
    """Load config.json, creating from example if missing."""
    if not CONFIG_PATH.exists():
        if EXAMPLE_CONFIG_PATH.exists():
            shutil.copy(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
            log.info("Created config.json from config.example.json")
        else:
            CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=4), encoding="utf-8")
            log.info("Created config.json with defaults")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        user_cfg = json.load(f)

    cfg = {**DEFAULTS, **user_cfg}
    cfg["output_dir"] = Path(cfg["output_dir"]).expanduser()
    return cfg

# ── Audio constants ───────────────────────────────────────────

SAMPLERATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16

# ── Teams detection ───────────────────────────────────────────


def is_teams_in_call() -> bool:
    """True if Teams process has an active Windows audio session."""
    try:
        for session in AudioUtilities.GetAllSessions():
            if session.Process and "teams" in session.Process.name().lower():
                return True
    except Exception:
        pass
    return False

# ── Audio devices ─────────────────────────────────────────────


def get_loopback_device(p: pyaudio.PyAudio) -> dict:
    """Return device info for default WASAPI loopback (speakers)."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    out_idx = wasapi["defaultOutputDevice"]
    return p.get_wasapi_loopback_analogue_by_index(out_idx)


def get_default_mic(p: pyaudio.PyAudio) -> dict:
    """Return default microphone device info."""
    idx = p.get_default_input_device_info()["index"]
    return p.get_device_info_by_index(idx)

# ── Recording ─────────────────────────────────────────────────


def record_device(
    p: pyaudio.PyAudio,
    device_info: dict,
    frames: list,
    stop_event: threading.Event,
):
    """Record from device into frames[] until stop_event is set."""
    rate = int(device_info["defaultSampleRate"])
    channels = min(CHANNELS, int(device_info["maxInputChannels"]))
    stream = p.open(
        format=FORMAT,
        channels=channels,
        rate=rate,
        input=True,
        input_device_index=int(device_info["index"]),
        frames_per_buffer=CHUNK,
    )
    while not stop_event.is_set():
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
    stream.stop_stream()
    stream.close()


def frames_to_wav(frames: list, rate: int, out_path: Path) -> float:
    """Save raw frames as 16-bit mono WAV. Returns duration in seconds."""
    raw = b"".join(frames)
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    arr /= 32768.0

    if rate != SAMPLERATE:
        from scipy.signal import resample
        n = int(len(arr) * SAMPLERATE / rate)
        arr = resample(arr, n)

    pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLERATE)
        wf.writeframes(pcm.tobytes())

    return len(pcm) / SAMPLERATE

# ── Transcription ─────────────────────────────────────────────


def transcribe_stream(wav_path: Path, model, language: str | None) -> list[dict]:
    """
    Transcribe a WAV file and return segments with timestamps.
    Each segment: {"start": float, "end": float, "text": str}
    """
    result = model.transcribe(
        str(wav_path),
        language=language,
        verbose=False,
    )
    segments = []
    for seg in result.get("segments", []):
        text = seg["text"].strip()
        if text:
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": text,
            })
    return segments


def merge_segments(mic_segments: list[dict], lb_segments: list[dict],
                   gap_threshold: float = 2.0) -> list[dict]:
    """
    Merge mic and loopback segments chronologically.
    Label mic as 'Me', loopback as 'Others'.
    Merge consecutive same-speaker segments if gap < gap_threshold.
    """
    tagged = []
    for seg in mic_segments:
        tagged.append({**seg, "speaker": "Me"})
    for seg in lb_segments:
        tagged.append({**seg, "speaker": "Others"})

    tagged.sort(key=lambda s: s["start"])

    if not tagged:
        return []

    merged = [tagged[0]]
    for seg in tagged[1:]:
        prev = merged[-1]
        if (seg["speaker"] == prev["speaker"]
                and seg["start"] - prev["end"] < gap_threshold):
            prev["text"] += " " + seg["text"]
            prev["end"] = seg["end"]
        else:
            merged.append(seg)

    return merged


def format_timestamp(seconds: float) -> str:
    """Format seconds as [HH:MM:SS]."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def format_transcript(segments: list[dict]) -> str:
    """Format merged segments into readable transcript text."""
    lines = []
    for seg in segments:
        ts = format_timestamp(seg["start"])
        lines.append(f"{ts} {seg['speaker']}: {seg['text']}")
    return "\n".join(lines)

# ── Meeting lifecycle ─────────────────────────────────────────


class RecorderState:
    """Observable state for the tray icon."""
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    LOADING = "loading"

    def __init__(self):
        self.status = self.LOADING
        self._listeners = []

    def set(self, status: str):
        self.status = status
        for fn in self._listeners:
            fn(status)

    def on_change(self, fn):
        self._listeners.append(fn)


def record_meeting(p: pyaudio.PyAudio, model, cfg: dict,
                   state: RecorderState,
                   shutdown_event: threading.Event | None = None) -> str | None:
    """
    Record a single meeting. Returns path to transcript or None.
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    folder = cfg["output_dir"] / ts
    folder.mkdir(parents=True, exist_ok=True)
    mic_wav = folder / "mic.wav"
    lb_wav = folder / "loopback.wav"
    txt_path = folder / "transcript.txt"

    try:
        loopback = get_loopback_device(p)
    except Exception as e:
        log.error("Could not get loopback device: %s", e)
        return None

    try:
        mic = get_default_mic(p)
    except Exception as e:
        log.error("Could not get microphone: %s", e)
        return None

    lb_frames, mic_frames = [], []
    stop = threading.Event()

    lb_thread = threading.Thread(
        target=record_device,
        args=(p, loopback, lb_frames, stop),
        daemon=True,
    )
    mic_thread = threading.Thread(
        target=record_device,
        args=(p, mic, mic_frames, stop),
        daemon=True,
    )

    state.set(RecorderState.RECORDING)
    log.info("[%s] Call detected - recording started", ts)
    lb_thread.start()
    mic_thread.start()

    while is_teams_in_call():
        if shutdown_event and shutdown_event.is_set():
            break
        time.sleep(cfg["poll_seconds"])

    stop.set()
    lb_thread.join(timeout=5)
    mic_thread.join(timeout=5)

    lb_rate = int(loopback["defaultSampleRate"])
    mic_rate = int(mic["defaultSampleRate"])

    log.info("Saving audio streams...")
    mic_duration = frames_to_wav(mic_frames, mic_rate, mic_wav)
    lb_duration = frames_to_wav(lb_frames, lb_rate, lb_wav)
    duration = max(mic_duration, lb_duration)

    log.info("Duration: %.0fs", duration)

    if duration < cfg["min_seconds"]:
        log.info("Under %ds - discarding.", cfg["min_seconds"])
        shutil.rmtree(folder)
        state.set(RecorderState.IDLE)
        return None

    state.set(RecorderState.TRANSCRIBING)
    log.info("Transcribing...")

    lang = cfg["language"]
    mic_segments = transcribe_stream(mic_wav, model, lang)
    lb_segments = transcribe_stream(lb_wav, model, lang)

    merged = merge_segments(mic_segments, lb_segments)
    transcript = format_transcript(merged)

    txt_path.write_text(transcript, encoding="utf-8")
    log.info("Transcript saved: %s", txt_path)

    if not cfg["keep_audio"]:
        mic_wav.unlink(missing_ok=True)
        lb_wav.unlink(missing_ok=True)
        log.info("Audio files deleted.")

    state.set(RecorderState.IDLE)
    return str(txt_path)

# ── Main loop ─────────────────────────────────────────────────


def monitor_loop(p: pyaudio.PyAudio, model, cfg: dict,
                 state: RecorderState, stop_event: threading.Event,
                 on_transcript=None):
    """Poll for Teams calls. Runs in a thread."""
    in_call = False
    while not stop_event.is_set():
        currently = is_teams_in_call()
        if currently and not in_call:
            in_call = True
            result = record_meeting(p, model, cfg, state, stop_event)
            if result and on_transcript:
                on_transcript(result)
            in_call = False
        elif not currently:
            in_call = False
        stop_event.wait(cfg["poll_seconds"])


def main():
    """CLI entry point (no tray). Use tray.py for system tray."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config()
    state = RecorderState()

    log.info("Loading Whisper (%s)...", cfg["whisper_model"])
    model = whisper.load_model(cfg["whisper_model"])
    log.info("Model ready. Monitoring for Teams calls...")
    state.set(RecorderState.IDLE)

    p = pyaudio.PyAudio()
    stop = threading.Event()
    try:
        monitor_loop(p, model, cfg, state, stop)
    except KeyboardInterrupt:
        log.info("Stopped.")
        stop.set()
    finally:
        p.terminate()


if __name__ == "__main__":
    main()
