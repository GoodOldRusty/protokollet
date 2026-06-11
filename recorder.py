#!/usr/bin/env python3
"""
Meeting Recorder
Records loopback + mic separately, transcribes via berget.ai API
(kb-whisper-large), produces speaker-labeled transcript.
Manual start/stop via system tray.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import time
import wave
import threading
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pyaudiowpatch as pyaudio
from openai import OpenAI

log = logging.getLogger("recorder")

# Suppress the console window Windows spawns for child processes (ffmpeg).
# The tray app runs windowless, so each subprocess would otherwise flash a console.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ffmpeg_exe() -> str:
    """Path to the ffmpeg binary bundled by the imageio-ffmpeg package.
    Avoids requiring users to install ffmpeg separately."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

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
    if not frames:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLERATE)
            wf.writeframes(b"")
        return 0.0
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
OFFLINE_POLL_SECONDS = 15  # how often to re-check connectivity while waiting

# Marker file for a recording that is owed a transcription. Created when
# transcription is about to start, removed on success or deliberate cancel,
# kept on failure/shutdown so the next app start can resume the work.
PENDING_MARKER = ".pending"


def is_api_reachable(cfg: dict, timeout: float = 5.0) -> bool:
    """Cheap online check: can we open a TCP connection to the API host?
    Checks the actual transcription endpoint host rather than a generic
    internet probe, since that is the connectivity that matters here."""
    try:
        parsed = urlparse(cfg["api_base_url"])
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        # ValueError covers malformed api_base_url (bad port, missing scheme)
        return False


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
        [_ffmpeg_exe(), "-y", "-i", str(wav_path), "-ac", "1", "-ar", "16000",
         "-b:a", "64k", str(mp3_path)],
        capture_output=True, check=True, creationflags=_NO_WINDOW,
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


class TranscriptionCancelled(Exception):
    """Raised when transcription is cancelled by the user."""


def _transcribe_with_retry(audio_path: Path, chunk_num: int, total: int,
                           client: OpenAI, cfg: dict,
                           cancel_event: threading.Event = None) -> str:
    """Convert to mp3 and transcribe with retry + exponential backoff.
    Checks cancel_event during retry waits to allow early abort."""
    mp3_path = _wav_to_mp3(audio_path)
    try:
        for attempt in range(1, MAX_RETRIES + 1):
            if cancel_event and cancel_event.is_set():
                raise TranscriptionCancelled()
            try:
                log.info("Transcribing chunk %d/%d (attempt %d, %.1f MB)...",
                         chunk_num, total, attempt, mp3_path.stat().st_size / 1e6)
                text = _transcribe_file(mp3_path, client, cfg)
                log.info("  Chunk %d done (%d chars)", chunk_num, len(text))
                return text
            except TranscriptionCancelled:
                raise
            except Exception as e:
                if attempt == MAX_RETRIES:
                    log.error("  Chunk %d failed after %d attempts: %s",
                              chunk_num, MAX_RETRIES, e)
                    raise
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning("  Chunk %d attempt %d failed, retrying in %ds...",
                            chunk_num, attempt, delay)
                # Sleep in small increments to allow cancel check
                for _ in range(delay):
                    if cancel_event and cancel_event.is_set():
                        raise TranscriptionCancelled()
                    time.sleep(1)
    finally:
        mp3_path.unlink(missing_ok=True)


def transcribe_stream(wav_path: Path, client: OpenAI, cfg: dict,
                      cancel_event: threading.Event = None) -> str:
    """Transcribe a WAV file, splitting into chunks and converting to mp3.
    Handles retry with exponential backoff for API failures.
    Checks cancel_event between chunks to allow early abort."""
    chunks = _split_wav(wav_path)

    if len(chunks) == 1 and chunks[0] == wav_path:
        log.info("Transcribing as single file")
        return _transcribe_with_retry(wav_path, 1, 1, client, cfg,
                                      cancel_event=cancel_event)

    log.info("Split into %d chunks", len(chunks))
    texts = []
    try:
        for i, chunk_path in enumerate(chunks):
            if cancel_event and cancel_event.is_set():
                raise TranscriptionCancelled()
            text = _transcribe_with_retry(chunk_path, i + 1, len(chunks), client, cfg,
                                          cancel_event=cancel_event)
            texts.append(text)
            if chunk_path != wav_path:
                chunk_path.unlink(missing_ok=True)
    except Exception:
        # Cancel or failure (e.g. network down) can fire mid-chunk, so remove
        # every chunk file (the in-flight one and any not yet processed).
        # Already-done chunks were deleted above; missing_ok makes the
        # re-delete harmless. The original wav_path is kept.
        for chunk_path in chunks:
            if chunk_path != wav_path:
                chunk_path.unlink(missing_ok=True)
        raise

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

TITLE: <kort beskrivande titel för mötet, 2-5 ord, på svenska>

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

Skriv allt på svenska. Börja svaret med TITLE-raden."""


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


def parse_title_from_summary(summary: str) -> tuple[str, str]:
    """Extract TITLE: line from summary. Returns (title, summary_without_title)."""
    match = re.match(r"TITLE:\s*(.+)", summary)
    if not match:
        return "", summary
    title = match.group(1).strip()
    rest = summary[match.end():].lstrip("\n")
    return title, rest


def title_to_filename(title: str, ts: str) -> str:
    """Convert a title to a filesystem-safe filename like '2026-04-01_14-31_budgetplanering-q3.md'."""
    slug = title.lower()
    slug = re.sub(r"[^\w\s\-åäöÅÄÖ]", "", slug)  # remove non-word chars except spaces/hyphens/Swedish
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    slug = slug[:60]  # cap length
    if slug:
        return f"{ts}_{slug}.md"
    return f"{ts}_transcript.md"


def find_pending(cfg: dict) -> list[Path]:
    """Recording folders whose transcription never finished: pending marker
    present and audio still on disk. Stale markers without audio are removed."""
    out_dir = Path(cfg["output_dir"])
    pending = []
    if not out_dir.exists():
        return pending
    for marker in sorted(out_dir.glob(f"*/{PENDING_MARKER}")):
        folder = marker.parent
        has_audio = (folder / "mic.wav").exists() or (folder / "loopback.wav").exists()
        has_transcript = any(folder.glob("*.md"))
        if has_audio and not has_transcript:
            pending.append(folder)
        else:
            # Stale marker: audio is gone, or a transcript already exists
            # (e.g. the marker unlink failed right after a successful save).
            marker.unlink(missing_ok=True)
    return pending


# ── State ─────────────────────────────────────────────────────


class RecorderState:
    """Observable state for the tray icon."""
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    WAITING = "waiting"  # offline - transcription queued until back online

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


def transcribe_folder(folder: Path, client: OpenAI, cfg: dict,
                      state: RecorderState, stop_recording: threading.Event,
                      on_transcript=None, on_error=None,
                      on_offline=None, on_online=None):
    """Transcribe a recording folder (mic.wav/loopback.wav) into a meeting
    transcript. Shared by the live recording flow and the startup resume of
    pending recordings. Waits for connectivity if offline, supports cancel,
    and maintains the pending marker: removed on success or cancel, kept on
    failure so the next app start retries automatically."""
    mic_wav = folder / "mic.wav"
    lb_wav = folder / "loopback.wav"
    md_path = folder / "transcript.md"
    ts = folder.name  # folder is named with the recording timestamp

    try:
        # If the API host is unreachable (e.g. offline), tell the user right
        # away and wait for connectivity instead of burning retries. Cancel
        # works during the wait; the audio is already safe on disk.
        if not is_api_reachable(cfg):
            log.info("Offline - transcription postponed. Audio kept in: %s", folder)
            state.set(RecorderState.WAITING)
            if on_offline:
                on_offline(str(folder))
            while True:
                for _ in range(OFFLINE_POLL_SECONDS):
                    if stop_recording.is_set():
                        raise TranscriptionCancelled()
                    time.sleep(1)
                if is_api_reachable(cfg):
                    break
            log.info("Back online - starting transcription")
            state.set(RecorderState.TRANSCRIBING)
            if on_online:
                on_online()

        mic_text = ""
        lb_text = ""

        if mic_wav.exists() and mic_wav.stat().st_size > 44:  # > bare WAV header = has frames
            mic_text = transcribe_stream(mic_wav, client, cfg,
                                         cancel_event=stop_recording)
        else:
            log.info("Mic stream empty - skipping transcription")

        if stop_recording.is_set():
            raise TranscriptionCancelled()

        if lb_wav.exists() and lb_wav.stat().st_size > 44:
            lb_text = transcribe_stream(lb_wav, client, cfg,
                                        cancel_event=stop_recording)
        else:
            log.info("Loopback stream empty - skipping transcription")

        if stop_recording.is_set():
            raise TranscriptionCancelled()

        my_name = cfg.get("my_name", "Me")
        raw_transcript = format_raw_transcript(mic_text, lb_text, my_name)

        log.info("Summarizing with LLM...")
        ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = ""
        try:
            raw_summary = summarize_transcript(raw_transcript, cfg)
            title, summary = parse_title_from_summary(raw_summary)
        except Exception:
            log.exception("LLM summarization failed - saving raw transcript only")
            summary = "*Sammanfattning kunde inte genereras (LLM-fel). Kör retranscribe.py för att försöka igen.*"

        if title:
            md_path = folder / title_to_filename(title, ts)
            heading = f"# {title} — {ts_label}"
        else:
            heading = f"# Mötesprotokoll {ts_label}"

        md_content = f"{heading}\n\n{summary}\n\n---\n\n## Rå transkribering\n\n{raw_transcript}\n"
        md_path.write_text(md_content, encoding="utf-8")
        log.info("Transcript saved: %s", md_path)

        try:
            (folder / PENDING_MARKER).unlink(missing_ok=True)
        except OSError:
            # A locked marker is harmless: find_pending treats folders that
            # already have a transcript as done and cleans the marker then.
            log.warning("Could not remove pending marker in %s", folder)

        if not cfg["keep_audio"]:
            mic_wav.unlink(missing_ok=True)
            lb_wav.unlink(missing_ok=True)
            log.info("Audio files deleted.")

        state.set(RecorderState.IDLE)

        if on_transcript:
            on_transcript(str(md_path))

    except TranscriptionCancelled:
        # Keep the audio (even if keep_audio is false) so a cancelled meeting
        # can be recovered rather than lost, but drop the pending marker:
        # cancel means "don't transcribe this automatically".
        try:
            (folder / PENDING_MARKER).unlink(missing_ok=True)
        except OSError:
            log.warning("Could not remove pending marker in %s", folder)
        log.info("Transcription cancelled. Audio kept in: %s", folder)
        log.info("To finish it later, run: python retranscribe.py \"%s\"", folder)
        state.set(RecorderState.IDLE)
    except Exception:
        # API/network failures land here. The audio is already on disk and
        # the pending marker is kept, so the next app start retries this
        # folder automatically.
        log.exception("Transcription failed. Audio kept in: %s", folder)
        log.info("To finish it later, run: python retranscribe.py \"%s\"", folder)
        state.set(RecorderState.IDLE)
        if on_error:
            on_error(str(folder))


def record_meeting(p: pyaudio.PyAudio, client: OpenAI, cfg: dict,
                   state: RecorderState,
                   stop_recording: threading.Event,
                   on_transcript=None, audio_levels=None, on_error=None,
                   on_offline=None, on_online=None):
    """
    Record until stop_recording is set. Transcribe and save.
    Runs in a background thread.
    """
    try:
        _record_meeting_inner(p, client, cfg, state, stop_recording,
                              on_transcript, audio_levels, on_error,
                              on_offline, on_online)
    except Exception:
        log.exception("record_meeting crashed")
        state.set(RecorderState.IDLE)


def _record_meeting_inner(p, client, cfg, state, stop_recording,
                          on_transcript, audio_levels, on_error,
                          on_offline, on_online):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    folder = cfg["output_dir"] / ts
    folder.mkdir(parents=True, exist_ok=True)
    mic_wav = folder / "mic.wav"
    lb_wav = folder / "loopback.wav"

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
    stop_recording.clear()  # reset so it can be reused for transcription cancel

    # Show "processing" immediately so the user sees their Stop registered.
    # Saving a long recording can take minutes; without this the icon stays
    # red and users click Stop again, which used to cancel transcription.
    state.set(RecorderState.TRANSCRIBING)

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

    # Drop any stray Stop/Cancel clicks that landed during the slow save,
    # so they don't immediately abort transcription before it even starts.
    stop_recording.clear()
    log.info("Transcribing via API...")

    # Mark the folder as awaiting transcription. The marker survives crashes
    # and shutdowns, so unfinished work is found and resumed at next start.
    (folder / PENDING_MARKER).touch()

    transcribe_folder(folder, client, cfg, state, stop_recording,
                      on_transcript=on_transcript, on_error=on_error,
                      on_offline=on_offline, on_online=on_online)
