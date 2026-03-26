#!/usr/bin/env python3
"""
Meeting Recorder
Records loopback + mic separately, transcribes via berget.ai API
(kb-whisper-large), produces speaker-labeled transcript.
Manual start/stop via system tray.
"""

import json
import os
import shutil
import wave
import threading
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
from openai import OpenAI

log = logging.getLogger("recorder")

# ── Config ────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"
EXAMPLE_CONFIG_PATH = Path(__file__).parent / "config.example.json"
ENV_PATH = Path(__file__).parent / ".env"

DEFAULTS = {
    "whisper_model": "KBLab/kb-whisper-large",
    "language": "sv",
    "keep_audio": False,
    "min_seconds": 30,
    "output_dir": "~/Recordings",
    "api_base_url": "https://api.berget.ai/v1",
}


def load_env():
    """Load .env file into environment variables."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_config() -> dict:
    """Load config.json, creating from example if missing."""
    load_env()

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
    """Record from device into frames[] until stop_event is set.
    Stores channel count as first element for downmix."""
    rate = int(device_info["defaultSampleRate"])
    channels = max(1, int(device_info["maxInputChannels"]))
    stream = p.open(
        format=FORMAT,
        channels=channels,
        rate=rate,
        input=True,
        input_device_index=int(device_info["index"]),
        frames_per_buffer=CHUNK,
    )
    frames.append(channels)
    while not stop_event.is_set():
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
    stream.stop_stream()
    stream.close()


def frames_to_wav(frames: list, rate: int, out_path: Path) -> float:
    """Save raw frames as 16-bit mono WAV. Returns duration in seconds."""
    channels = frames[0]
    raw = b"".join(frames[1:])
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    arr /= 32768.0

    if channels > 1:
        arr = arr.reshape(-1, channels).mean(axis=1)

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


def transcribe_stream(wav_path: Path, client: OpenAI, cfg: dict) -> str:
    """Transcribe a WAV file via berget.ai API. Returns plain text."""
    with open(wav_path, "rb") as f:
        kwargs = {
            "model": cfg["whisper_model"],
            "file": f,
            "language": cfg["language"],
        }
        if cfg.get("prompt"):
            kwargs["prompt"] = cfg["prompt"]
        result = client.audio.transcriptions.create(**kwargs)
    return result.text.strip()


def format_transcript(mic_text: str, lb_text: str) -> str:
    """Format mic and loopback transcriptions into labeled transcript."""
    lines = []
    if lb_text:
        lines.append(f"Others: {lb_text}")
    if mic_text:
        lines.append(f"Me: {mic_text}")
    return "\n\n".join(lines)

# ── State ─────────────────────────────────────────────────────


class RecorderState:
    """Observable state for the tray icon."""
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"

    def __init__(self):
        self.status = self.IDLE
        self._listeners = []

    def set(self, status: str):
        self.status = status
        for fn in self._listeners:
            fn(status)

    def on_change(self, fn):
        self._listeners.append(fn)

# ── Recording session ─────────────────────────────────────────


def record_meeting(p: pyaudio.PyAudio, client: OpenAI, cfg: dict,
                   state: RecorderState,
                   stop_recording: threading.Event,
                   on_transcript=None):
    """
    Record until stop_recording is set. Transcribe and save.
    Runs in a background thread.
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
        state.set(RecorderState.IDLE)
        return

    try:
        mic = get_default_mic(p)
    except Exception as e:
        log.error("Could not get microphone: %s", e)
        state.set(RecorderState.IDLE)
        return

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
    log.info("[%s] Recording started", ts)
    lb_thread.start()
    mic_thread.start()

    stop_recording.wait()

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
        return

    state.set(RecorderState.TRANSCRIBING)
    log.info("Transcribing via API...")

    mic_text = transcribe_stream(mic_wav, client, cfg)
    lb_text = transcribe_stream(lb_wav, client, cfg)

    transcript = format_transcript(mic_text, lb_text)

    txt_path.write_text(transcript, encoding="utf-8")
    log.info("Transcript saved: %s", txt_path)

    if not cfg["keep_audio"]:
        mic_wav.unlink(missing_ok=True)
        lb_wav.unlink(missing_ok=True)
        log.info("Audio files deleted.")

    state.set(RecorderState.IDLE)

    if on_transcript:
        on_transcript(str(txt_path))
