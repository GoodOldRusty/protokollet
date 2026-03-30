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
import subprocess
import time
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
    "llm_model": "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
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
    level_callback=None,
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
        if level_callback is not None:
            samples = np.frombuffer(data, dtype=np.int16)
            rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2)) / 32768.0
            level_callback(min(1.0, rms * 3.0))
    stream.stop_stream()
    stream.close()


def frames_to_wav(frames: list, rate: int, out_path: Path) -> float:
    """Save raw frames as 16-bit mono WAV. Returns duration in seconds."""
    channels = frames[0]
    raw = b"".join(frames[1:])
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    arr /= 32768.0

    if len(arr) == 0:
        pcm = np.array([], dtype=np.int16)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLERATE)
            wf.writeframes(pcm.tobytes())
        return 0.0

    if channels > 1:
        arr = arr.reshape(-1, channels).mean(axis=1)

    if rate != SAMPLERATE and len(arr) > 0:
        from scipy.signal import resample
        n = int(len(arr) * SAMPLERATE / rate)
        if n > 0:
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

CHUNK_SECONDS = 120  # 2 minutes per chunk
MAX_RETRIES = 5
RETRY_BASE_DELAY = 10  # seconds


def _transcribe_file(audio_path: Path, client: OpenAI, cfg: dict) -> str:
    """Transcribe a single audio file via berget.ai API. Returns plain text."""
    with open(audio_path, "rb") as f:
        kwargs = {
            "model": cfg["whisper_model"],
            "file": f,
            "language": cfg["language"],
        }
        if cfg.get("prompt"):
            kwargs["prompt"] = cfg["prompt"]
        result = client.audio.transcriptions.create(**kwargs)
    return result.text.strip()


def _wav_to_mp3(wav_path: Path) -> Path:
    """Convert WAV to mp3 using ffmpeg. Returns mp3 path."""
    mp3_path = wav_path.with_suffix(".mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-ac", "1", "-ar", "16000",
         "-b:a", "64k", str(mp3_path)],
        capture_output=True, check=True,
    )
    log.info("Converted %s: %.1f MB -> %.1f MB mp3",
             wav_path.name, wav_path.stat().st_size / 1e6,
             mp3_path.stat().st_size / 1e6)
    return mp3_path


def _split_wav(wav_path: Path) -> list[Path]:
    """Split a WAV file into chunks. Returns list of chunk WAV paths."""
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        duration = n_frames / framerate

        if duration <= CHUNK_SECONDS:
            return [wav_path]

        chunk_frames = CHUNK_SECONDS * framerate
        chunks = []
        chunk_idx = 0

        while wf.tell() < n_frames:
            frames_to_read = min(chunk_frames, n_frames - wf.tell())
            data = wf.readframes(frames_to_read)

            chunk_path = wav_path.parent / f"{wav_path.stem}_chunk{chunk_idx:03d}.wav"
            with wave.open(str(chunk_path), "wb") as cf:
                cf.setnchannels(n_channels)
                cf.setsampwidth(sampwidth)
                cf.setframerate(framerate)
                cf.writeframes(data)

            chunk_dur = frames_to_read / framerate
            log.info("  Chunk %d: %.0fs", chunk_idx, chunk_dur)
            chunks.append(chunk_path)
            chunk_idx += 1

    return chunks


def _transcribe_with_retry(audio_path: Path, chunk_num: int, total: int,
                           client: OpenAI, cfg: dict) -> str:
    """Convert to mp3 and transcribe with retry + exponential backoff."""
    mp3_path = _wav_to_mp3(audio_path)
    try:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log.info("Transcribing chunk %d/%d (attempt %d, %.1f MB)...",
                         chunk_num, total, attempt, mp3_path.stat().st_size / 1e6)
                text = _transcribe_file(mp3_path, client, cfg)
                log.info("  Chunk %d done (%d chars)", chunk_num, len(text))
                return text
            except Exception as e:
                if attempt == MAX_RETRIES:
                    log.error("  Chunk %d failed after %d attempts: %s",
                              chunk_num, MAX_RETRIES, e)
                    raise
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning("  Chunk %d attempt %d failed, retrying in %ds...",
                            chunk_num, attempt, delay)
                time.sleep(delay)
    finally:
        mp3_path.unlink(missing_ok=True)


def transcribe_stream(wav_path: Path, client: OpenAI, cfg: dict) -> str:
    """Transcribe a WAV file, splitting into chunks and converting to mp3.
    Handles retry with exponential backoff for API failures."""
    chunks = _split_wav(wav_path)

    if len(chunks) == 1 and chunks[0] == wav_path:
        log.info("Transcribing as single file")
        return _transcribe_with_retry(wav_path, 1, 1, client, cfg)

    log.info("Split into %d chunks", len(chunks))
    texts = []
    for i, chunk_path in enumerate(chunks):
        text = _transcribe_with_retry(chunk_path, i + 1, len(chunks), client, cfg)
        texts.append(text)
        if chunk_path != wav_path:
            chunk_path.unlink(missing_ok=True)

    return " ".join(texts)


def format_raw_transcript(mic_text: str, lb_text: str, my_name: str = "Me") -> str:
    """Format mic and loopback transcriptions into labeled transcript."""
    lines = []
    if lb_text:
        lines.append(f"Others: {lb_text}")
    if mic_text:
        lines.append(f"{my_name}: {mic_text}")
    return "\n\n".join(lines)


SUMMARY_PROMPT = """\
Du får en rå transkribering av ett möte. Transkriberingen kan innehålla \
fel och upprepningar från tal-till-text.

Skapa ett strukturerat mötesprotokoll i markdown med följande sektioner:

## Sammanfattning
En kort sammanfattning av mötet (2-4 meningar).

## Beslut
Lista viktiga beslut som fattades. Om inga beslut fattades, skriv "Inga beslut noterade."

## Åtgärdspunkter
Lista konkreta uppgifter som nämndes, med ansvarig person om det framgår. \
Om inga åtgärdspunkter, skriv "Inga åtgärdspunkter noterade."

## Mötesanteckningar
En uppstädad version av samtalet i löpande text. Korrigera uppenbara \
transkriptionsfel, ta bort upprepningar och fyllnadsord, men behåll \
innebörden. Ange vem som sa vad (Me/Others) där det är tydligt.

Skriv allt på svenska."""


def get_llm_client(cfg: dict) -> OpenAI:
    """Get a separate OpenAI client for LLM, using BERGET_API_KEY2 if available."""
    api_key = os.environ.get("BERGET_API_KEY2") or os.environ.get("BERGET_API_KEY", "")
    return OpenAI(api_key=api_key, base_url=cfg["api_base_url"])


def summarize_transcript(raw_transcript: str, cfg: dict) -> str:
    """Post-process raw transcript with LLM to produce structured markdown."""
    llm_client = get_llm_client(cfg)
    response = llm_client.chat.completions.create(
        model=cfg["llm_model"],
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": raw_transcript},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()

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
                   on_transcript=None, audio_levels=None):
    """
    Record until stop_recording is set. Transcribe and save.
    Runs in a background thread.
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    folder = cfg["output_dir"] / ts
    folder.mkdir(parents=True, exist_ok=True)
    mic_wav = folder / "mic.wav"
    lb_wav = folder / "loopback.wav"
    md_path = folder / "transcript.md"

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

    lb_level_cb = audio_levels.update_loopback if audio_levels else None
    mic_level_cb = audio_levels.update_mic if audio_levels else None

    lb_thread = threading.Thread(
        target=record_device,
        args=(p, loopback, lb_frames, stop),
        kwargs={"level_callback": lb_level_cb},
        daemon=True,
    )
    mic_thread = threading.Thread(
        target=record_device,
        args=(p, mic, mic_frames, stop),
        kwargs={"level_callback": mic_level_cb},
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

    mic_text = ""
    lb_text = ""

    if mic_duration > 0:
        mic_text = transcribe_stream(mic_wav, client, cfg)
    else:
        log.info("Mic stream empty - skipping transcription")

    if lb_duration > 0:
        lb_text = transcribe_stream(lb_wav, client, cfg)
    else:
        log.info("Loopback stream empty - skipping transcription")

    my_name = cfg.get("my_name", "Me")
    raw_transcript = format_raw_transcript(mic_text, lb_text, my_name)

    log.info("Summarizing with LLM...")
    ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = summarize_transcript(raw_transcript, cfg)

    md_content = f"# Mötesprotokoll {ts_label}\n\n{summary}\n\n---\n\n## Rå transkribering\n\n{raw_transcript}\n"
    md_path.write_text(md_content, encoding="utf-8")
    log.info("Transcript saved: %s", md_path)

    if not cfg["keep_audio"]:
        mic_wav.unlink(missing_ok=True)
        lb_wav.unlink(missing_ok=True)
        log.info("Audio files deleted.")

    state.set(RecorderState.IDLE)

    if on_transcript:
        on_transcript(str(md_path))
