# protokollet — PRD

Current as of v1.7.0 (2026-06-11). Formerly "Meeting Recorder"; renamed
for public release. Feature history lives in the README changelog.

## Overview

A Windows system tray application that records meetings via manual
start/stop, captures both sides of the conversation (mic + system audio),
transcribes using berget.ai's KB-Whisper (the National Library of
Sweden's Swedish-optimized speech model), and produces structured meeting
notes with summary, decisions, and action items via LLM post-processing.

Recording is local and app-agnostic: it works with Teams, Zoom, Google
Meet, a phone on speaker, or a physical meeting room. A recording is
never lost — transcription survives network outages, app restarts, and
computer shutdowns, and resumes automatically.

## Goals

- Manual start/stop: user controls when recording begins and ends
- Speaker identification: distinguish "Me" (mic) from "Others" (loopback)
- Cloud transcription: fast, accurate Swedish transcription via berget.ai
- LLM summary: structured meeting notes with decisions and action items
- System tray: runs quietly in the background with minimal UI
- No GPU required: all heavy processing happens server-side
- Resilience: a stopped recording is always either transcribed or kept on
  disk with a pending marker — offline, crash, and shutdown safe
- Glanceable status: tray color + recording pill answer "is it recording,
  is audio flowing, is anything queued" without opening a window

## Non-goals

- Automatic call detection (future consideration)
- Meeting-app integrations (no bot joins the call — system-audio capture
  makes the app work with any tool, so integrations are unnecessary)
- Real-time transcription during calls
- Individual speaker identification among remote participants
- Cross-platform support (Windows only)
- A full GUI: the state machine is self-healing by design and surfaces
  through tray states, the pill, and toasts. If the app gains a GUI
  later, the first candidate is a small Settings dialog replacing
  raw `config.json` editing — not a status dashboard.

---

## Feature blocks (shipped)

### FB1 — Configuration

`config.json` for all user-facing settings, `.env` for API keys.

| Key              | Type   | Default                                            | Description                          |
| ---------------- | ------ | -------------------------------------------------- | ------------------------------------ |
| `whisper_model`  | string | `"KBLab/kb-whisper-large"`                         | Whisper model on berget.ai           |
| `llm_model`      | string | `"mistralai/Mistral-Small-3.2-24B-Instruct-2506"` | LLM for summary post-processing     |
| `my_name`        | string | `"Me"`                                             | Your name in the transcript          |
| `language`       | string | `"sv"`                                             | Transcription language               |
| `keep_audio`     | bool   | `false`                                            | Keep WAV after transcription         |
| `min_seconds`    | int    | `30`                                               | Discard recordings shorter than this |
| `output_dir`     | string | `"~/Recordings"`                                   | Where to save recordings             |
| `api_base_url`   | string | `"https://api.berget.ai/v1"`                       | API endpoint                         |
| `prompt`         | string | *(domain terms)*                                   | Vocabulary hints for Whisper (max 224 tokens) |

Environment variables: `BERGET_API_KEY` (whisper), `BERGET_API_KEY2`
(LLM, falls back to the first). `config.example.json` and `.env.example`
are committed; the real files are gitignored. Config is re-read fresh at
each recording — no restart needed.

### FB2 — Core recording engine

- Records loopback (system audio, WASAPI) and mic as **separate streams**
- Downmixes stereo to mono, resamples to 16 kHz, saves `mic.wav` +
  `loopback.wav` to `output_dir/<YYYY-MM-DD_HH-MM>/`
- Discards recordings under `min_seconds`; handles empty streams
- A `.pending` marker is written once transcription is owed (see FB7)

### FB3 — Transcription via berget.ai API

- Each stream sent separately; mic labeled with `my_name`, loopback
  labeled "Others"; domain vocabulary via `prompt`
- Long files split into 2-minute chunks, converted to mp3, sent with the
  app's own retry loop (5 attempts, exponential backoff, cancellable
  between attempts and during backoff waits)
- API timeout 60 s with SDK retries disabled — a hung request can never
  block Cancel for more than a minute

### FB4 — LLM summary post-processing

- Mistral via berget.ai (OpenAI-compatible), temperature 0.3, 120 s timeout
- Two files per meeting: `transkript.md` (raw speaker-labeled transcript,
  written BEFORE the LLM step — the durable artifact) and the protokoll
  (Sammanfattning, Beslut, Åtgärdspunkter, Mötesanteckningar) which links
  to the transcript instead of embedding it — shareable without the
  verbatim conversation
- LLM generates a meeting title that becomes the protokoll filename
  (`<timestamp>_<slug>.md`, fallback `<timestamp>_protokoll.md`); on LLM
  failure the transcript is already safe on disk and the pending marker
  stays, so the next app start redoes only the summary step

### FB5 — System tray application

Four-state icon: grey (ready), red (recording), blue (transcribing),
orange (waiting for connection — transcription queued). Tooltip shows
"(N queued)" during a startup resume batch.

Menu: status label, Start/Stop Recording, Cancel Transcription (also
available in the orange state), Open Recordings, Settings…, Quit.
Windows toasts narrate every outcome: saved, failed (audio kept),
offline (will auto-resume), back online, resuming unfinished recordings.

### FB6 — Recording pill

Frameless always-on-top tkinter window (rounded corners via transparent
color key) docked bottom-right above the taskbar (SPI_GETWORKAREA):
pulsing REC dot, elapsed timer, slim live level bars for MIC and OTHERS.
Draggable. Replaces the earlier title-barred "Audio Levels" window.

### FB7 — Offline resilience and recovery

The invariant: **a stopped recording ≥ `min_seconds` is either fully
processed (transkript.md + protokoll) or sits on disk with the `.pending`
marker plus whatever already exists (audio and/or transcript) — and the
next start redoes only the missing step.**

- At Stop, a TCP reachability check against the API host decides:
  process now, or enter the orange waiting state and poll every 15 s,
  resuming automatically when connectivity returns
- The `.pending` marker is created when work is owed, removed when the
  protokoll is saved **or on deliberate cancel** (cancel means "never
  auto-process this"), kept on failure/crash/shutdown
- At startup, marked folders are resumed automatically (toast announces
  it): with a transcript on disk only the summary is redone (no audio
  needed); folders that already have a protokoll are treated as done and
  their stale marker is cleaned
- `retranscribe.py` recovers any kept folder manually (same
  skip-what-is-done logic) and clears the marker

### FB8 — Setup and distribution

- `setup.bat`: guided one-time install (checks Python, creates venv,
  installs deps incl. bundled ffmpeg via `imageio-ffmpeg`, prompts for
  API key)
- `Recorder.bat`: one-click launcher; `create_startup_shortcut.vbs` for
  auto-start at login
- Friendly first-run dialog when the API key is missing
- Bilingual docs: `README.md` (Swedish, default view) + `README.en.md`
  (English twin), cross-linked; MIT license; distributed via GitHub
  (`GoodOldRusty/protokollet`, public release planned)

---

## Technical decisions

- **Speaker identification:** Two-stream approach (mic vs. loopback)
  gives speaker identification for free. Distinguishes "Me" from
  "Others" but does not identify individual remote participants.
- **WASAPI loopback** captures all system audio, not just the meeting
  app. Other apps playing audio during a call will be included.
- **Transcription:** berget.ai API with KB-Whisper (kb-whisper-large).
  No local model, no GPU needed. Positioning claim kept verifiable:
  KBLab reports ~47% lower WER on Swedish vs whisper-large-v3.
- **Retry ownership:** SDK retries are disabled (`max_retries=0` for
  whisper) so the app's own loop owns retrying — it is the only layer
  that can honor Cancel between attempts.
- **Cancel vs. failure semantics:** cancel deletes the pending marker
  (user said no), failure keeps it (system owes the work). Audio is kept
  in both cases; deletion happens only after a successful save.
- **Connectivity check:** TCP connect to the API host (not a generic
  internet probe) — it tests the connectivity that actually matters.
- **System tray:** `pystray` + `Pillow`. The tray menu is a native
  Windows menu — styling is out of our control by design.
- **Pill window:** plain tkinter, no GUI framework. Drawing into the
  Windows 11 taskbar band is impossible (deskbands removed); the docked
  pill is the closest legal placement.
- **Threading model:** Recording runs in a background thread with two
  capture sub-threads. Transcription/LLM run sequentially in that thread.
  The pill owns the tk mainloop on the main thread; cross-thread
  communication is via plain flags polled by the tk thread. The startup
  resume runs in its own thread, gated by the same state machine.
- **No timestamps in transcript:** the two-stream approach doesn't allow
  reliable chronological interleaving without diarization.
- **Identity:** repo-local git identity (goodoldrusty); commits carry no
  AI attribution; tags follow `protokollet_vX.Y.Z`.

## Dependencies

- `pyaudiowpatch` — WASAPI loopback recording
- `pycaw` — Windows audio session enumeration
- `numpy` / `scipy` — audio processing and resampling
- `openai` — berget.ai API client (OpenAI-compatible)
- `imageio-ffmpeg` — bundled ffmpeg binary for mp3 conversion
- `pystray` + `Pillow` — system tray icon
- `plyer` — Windows toast notifications
- `tkinter` (stdlib) — recording pill

## File structure

```
Recorder/
  recorder.py                 # recording, transcription, LLM, pending logic
  tray.py                     # system tray application (entry point)
  vu_meter.py                 # recording pill window (tkinter)
  retranscribe.py             # manual recovery of kept recordings
  setup.bat                   # guided one-time install
  Recorder.bat                # launcher
  create_startup_shortcut.vbs # add app to Windows startup
  config.example.json         # committed example config
  config.json                 # gitignored, user's real config
  .env.example                # committed, documents API key variables
  .env                        # gitignored, API keys
  requirements.txt
  LICENSE                     # MIT
  README.md                   # Swedish (default view on GitHub)
  README.en.md                # English twin
  prd.md
  .local/                     # gitignored scratch (test/demo scripts)
```
