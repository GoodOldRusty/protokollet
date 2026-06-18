#!/usr/bin/env python3
"""Manually finish a recording folder: transcribes WAV files (skipped if
transkript.md already exists) and writes the protokoll. Splits large files
into 2-minute chunks, converts to mp3, and retries on failure."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from recorder import (
    PENDING_MARKER,
    TRANSCRIPT_FILENAME,
    load_config,
    transcribe_stream,
    format_raw_transcript,
    summarize_transcript,
    parse_title_from_summary,
    title_to_filename,
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


folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not folder or not folder.exists():
    print("Usage: python retranscribe.py <recording_folder>")
    sys.exit(1)

mic_wav = folder / "mic.wav"
lb_wav = folder / "loopback.wav"
transcript_path = folder / TRANSCRIPT_FILENAME

cfg = load_config()
api_key = os.environ.get("BERGET_API_KEY", "")
if not api_key:
    log.error("BERGET_API_KEY not set. Add it to .env file.")
    sys.exit(1)

client = OpenAI(api_key=api_key, base_url=cfg["api_base_url"],
                timeout=60, max_retries=0)

if transcript_path.exists():
    # Transcription already done in an earlier attempt - only re-summarize.
    raw_transcript = transcript_path.read_text(encoding="utf-8").strip()
    log.info("Raw transcript already on disk - only summarizing")
else:
    mic_text = ""
    lb_text = ""

    if mic_wav.exists() and mic_wav.stat().st_size > 44:
        log.info("Transcribing mic (%d bytes / %.1f MB)...",
                 mic_wav.stat().st_size, mic_wav.stat().st_size / 1e6)
        mic_text = transcribe_stream(mic_wav, client, cfg)
        log.info("Mic transcription done (%d chars)", len(mic_text))
    else:
        log.info("Mic WAV empty or missing - skipping")

    if lb_wav.exists() and lb_wav.stat().st_size > 44:
        log.info("Transcribing loopback (%d bytes / %.1f MB)...",
                 lb_wav.stat().st_size, lb_wav.stat().st_size / 1e6)
        lb_text = transcribe_stream(lb_wav, client, cfg)
        log.info("Loopback transcription done (%d chars)", len(lb_text))
    else:
        log.info("Loopback WAV empty or missing - skipping")

    my_name = cfg.get("my_name", "Me")
    raw_transcript = format_raw_transcript(mic_text, lb_text, my_name)

    # Written before the LLM step so a summary failure cannot lose the meeting.
    transcript_path.write_text(raw_transcript + "\n", encoding="utf-8")
    log.info("Raw transcript saved: %s", transcript_path)
    # Transcript is durable now; the per-chunk caches (both streams) are spent.
    for cache_file in folder.glob(".transcript_*chunk*.txt"):
        cache_file.unlink(missing_ok=True)

log.info("Summarizing with LLM...")
ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
raw_summary = summarize_transcript(raw_transcript, cfg)
title, summary = parse_title_from_summary(raw_summary)
log.info("Summary done (%d chars)", len(summary))

ts_from_folder = folder.name  # e.g. "2026-04-01_14-31"
md_path = folder / title_to_filename(title, ts_from_folder)
heading = f"# {title} — {ts_label}" if title else f"# Mötesprotokoll {ts_label}"

md_content = (f"{heading}\n\n{summary}\n\n---\n\n"
              f"*Rå transkribering: [{TRANSCRIPT_FILENAME}]({TRANSCRIPT_FILENAME})*\n")
md_path.write_text(md_content, encoding="utf-8")
log.info("Protokoll saved: %s", md_path)

# Clear the pending marker so the tray app does not redo this folder at
# next start.
(folder / PENDING_MARKER).unlink(missing_ok=True)
