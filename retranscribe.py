#!/usr/bin/env python3
"""Re-run transcription on existing WAV files in a recording folder.
Splits large files into 5-minute chunks, converts to mp3, and retries on failure."""

import logging
import os
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

from recorder import (
    load_config,
    transcribe_stream,
    format_raw_transcript,
    summarize_transcript,
)
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "recorder.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("retranscribe")

CHUNK_SECONDS = 120  # 2 minutes per chunk
MAX_RETRIES = 5
RETRY_BASE_DELAY = 10  # seconds


def wav_to_mp3(wav_path: Path) -> Path:
    """Convert WAV to mp3 using ffmpeg. Returns mp3 path."""
    mp3_path = wav_path.with_suffix(".mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-ac", "1", "-ar", "16000",
         "-b:a", "64k", str(mp3_path)],
        capture_output=True, check=True,
    )
    wav_size = wav_path.stat().st_size
    mp3_size = mp3_path.stat().st_size
    log.info("  Converted %s: %.1f MB → %.1f MB",
             wav_path.name, wav_size / 1e6, mp3_size / 1e6)
    return mp3_path


def split_wav(wav_path: Path) -> list[Path]:
    """Split a WAV file into chunks. Returns list of chunk paths."""
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
            log.info("  Chunk %d: %.0fs (%s)", chunk_idx, chunk_dur, chunk_path.name)
            chunks.append(chunk_path)
            chunk_idx += 1

    return chunks


def transcribe_chunk_with_retry(chunk_path: Path, chunk_num: int, total: int,
                                 client: OpenAI, cfg: dict) -> str:
    """Convert chunk to mp3, then transcribe with retry and exponential backoff."""
    mp3_path = wav_to_mp3(chunk_path)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info("Transcribing chunk %d/%d (attempt %d, %.1f MB mp3)...",
                     chunk_num, total, attempt, mp3_path.stat().st_size / 1e6)
            text = transcribe_stream(mp3_path, client, cfg)
            log.info("  Chunk %d done (%d chars)", chunk_num, len(text))
            mp3_path.unlink(missing_ok=True)
            return text
        except Exception as e:
            if attempt == MAX_RETRIES:
                log.error("  Chunk %d failed after %d attempts: %s", chunk_num, MAX_RETRIES, e)
                mp3_path.unlink(missing_ok=True)
                raise
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            log.warning("  Chunk %d attempt %d failed, retrying in %ds...",
                        chunk_num, attempt, delay)
            time.sleep(delay)


def transcribe_wav(wav_path: Path, client: OpenAI, cfg: dict) -> str:
    """Transcribe a WAV file, splitting into chunks if needed.
    Converts to mp3 and saves progress per chunk."""
    chunks = split_wav(wav_path)
    progress_dir = wav_path.parent

    if len(chunks) == 1 and chunks[0] == wav_path:
        log.info("File is small enough, sending as single mp3")
        return transcribe_chunk_with_retry(wav_path, 1, 1, client, cfg)

    log.info("Split into %d chunks", len(chunks))
    texts = []
    for i, chunk_path in enumerate(chunks):
        cache_file = progress_dir / f".transcript_chunk{i:03d}.txt"
        if cache_file.exists():
            text = cache_file.read_text(encoding="utf-8")
            log.info("Chunk %d/%d already transcribed (%d chars), skipping",
                     i + 1, len(chunks), len(text))
            texts.append(text)
            if chunk_path != wav_path and chunk_path.exists():
                chunk_path.unlink()
            continue

        text = transcribe_chunk_with_retry(chunk_path, i + 1, len(chunks), client, cfg)
        cache_file.write_text(text, encoding="utf-8")
        texts.append(text)
        if chunk_path != wav_path:
            chunk_path.unlink()

    # Clean up cache files
    for cache in progress_dir.glob(".transcript_chunk*.txt"):
        cache.unlink()

    return " ".join(texts)


folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not folder or not folder.exists():
    print("Usage: python retranscribe.py <recording_folder>")
    sys.exit(1)

mic_wav = folder / "mic.wav"
lb_wav = folder / "loopback.wav"
md_path = folder / "transcript.md"

cfg = load_config()
api_key = os.environ.get("BERGET_API_KEY", "")
if not api_key:
    log.error("BERGET_API_KEY not set. Add it to .env file.")
    sys.exit(1)

client = OpenAI(api_key=api_key, base_url=cfg["api_base_url"])

mic_text = ""
lb_text = ""

if mic_wav.exists() and mic_wav.stat().st_size > 44:
    log.info("Transcribing mic (%d bytes / %.1f MB)...",
             mic_wav.stat().st_size, mic_wav.stat().st_size / 1e6)
    mic_text = transcribe_wav(mic_wav, client, cfg)
    log.info("Mic transcription done (%d chars)", len(mic_text))
else:
    log.info("Mic WAV empty or missing - skipping")

if lb_wav.exists() and lb_wav.stat().st_size > 44:
    log.info("Transcribing loopback (%d bytes / %.1f MB)...",
             lb_wav.stat().st_size, lb_wav.stat().st_size / 1e6)
    lb_text = transcribe_wav(lb_wav, client, cfg)
    log.info("Loopback transcription done (%d chars)", len(lb_text))
else:
    log.info("Loopback WAV empty or missing - skipping")

my_name = cfg.get("my_name", "Me")
raw_transcript = format_raw_transcript(mic_text, lb_text, my_name)

log.info("Summarizing with LLM...")
ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
summary = summarize_transcript(raw_transcript, cfg)
log.info("Summary done (%d chars)", len(summary))

md_content = f"# Mötesprotokoll {ts_label}\n\n{summary}\n\n---\n\n## Rå transkribering\n\n{raw_transcript}\n"
md_path.write_text(md_content, encoding="utf-8")
log.info("Transcript saved: %s", md_path)
