# Meeting Recorder — PRD

## Overview

A Windows system tray application that records meetings via manual
start/stop, captures both sides of the conversation (mic + system audio),
transcribes using berget.ai's kb-whisper-large (Swedish-optimized), and
produces structured meeting notes with summary, decisions, and action
items via LLM post-processing.

## Goals

- Manual start/stop: user controls when recording begins and ends
- Speaker identification: distinguish "Me" (mic) from "Others" (loopback)
- Cloud transcription: fast, accurate Swedish transcription via berget.ai
- LLM summary: structured meeting notes with decisions and action items
- System tray: runs quietly in the background with minimal UI
- No GPU required: all heavy processing happens server-side

## Non-goals

- Automatic call detection (future consideration)
- Support for apps other than Teams
- Real-time transcription during calls
- Individual speaker identification among remote participants
- Cross-platform support (Windows only)

---

## Feature blocks

### FB1 — Project setup and config

Set up the project structure with a `config.json` for all user-facing
settings. Environment variables for API keys via `.env` file.

**Config file (`config.json`):**

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

**Environment variables (`.env`):**

| Key               | Description                                      |
| ----------------- | ------------------------------------------------ |
| `BERGET_API_KEY`  | API key for Whisper transcription                |
| `BERGET_API_KEY2` | API key for LLM (falls back to `BERGET_API_KEY`) |

Provide a `config.example.json` (committed) and `.gitignore` the real
`config.json`. If `config.json` is missing at startup, copy from example.

### FB2 — Core recording engine

Record mic and system audio as separate streams via manual start/stop.

- Record loopback (system audio) via WASAPI and mic as **separate streams**
- Downmix stereo loopback to mono, resample both streams to 16 kHz
- Save as two separate mono WAV files (`mic.wav`, `loopback.wav`)
- Discard recordings under `min_seconds`
- Save to `output_dir/<YYYY-MM-DD_HH-MM>/`
- Handle empty audio streams gracefully (skip transcription for empty streams)

### FB3 — Transcription via berget.ai API

Transcribe using berget.ai's OpenAI-compatible API with kb-whisper-large.

- Send each WAV file to the API separately
- Label mic stream with configurable `my_name`, loopback as "Others"
- Support domain vocabulary hints via `prompt` config field
- Output raw transcript with speaker labels (no timestamps)
- Skip transcription for empty/silent streams

### FB4 — LLM summary post-processing

Post-process raw transcript with an LLM to produce structured meeting notes.

- Use Mistral (configurable) via berget.ai's OpenAI-compatible API
- Support separate API key for LLM endpoint (`BERGET_API_KEY2`)
- Produce structured markdown output:
  - `## Sammanfattning` — 2-4 sentence summary
  - `## Beslut` — key decisions made
  - `## Åtgärdspunkter` — action items with owners
  - `## Mötesanteckningar` — cleaned-up prose version
- Final output file (`transcript.md`) combines LLM summary with raw
  transcript appended under `## Rå transkribering`

### FB5 — System tray application

Wrap the recorder in a system tray app using `pystray`.

- Tray icon with status indicator:
  - Grey — ready (idle)
  - Red — recording
  - Blue — transcribing
- Right-click menu:
  - Status label (disabled, informational)
  - "Start Recording" — visible when idle
  - "Stop Recording" — visible when recording
  - "Open Recordings" — opens output folder in Explorer
  - "Settings..." — opens `config.json` in default editor
  - "Quit" — clean shutdown
- Config is re-read fresh each recording (no restart needed for changes)
- Windows toast notification when transcription is complete

### FB6 — Launcher and packaging

- `Recorder.bat` — one-click launcher: activates venv and runs the app
- `requirements.txt` with all dependencies
- README with setup instructions, configuration reference, and changelog

---

## Launch readiness (v1.4.0)

Goal: make the repo public-launch ready — a non-technical Windows user
should understand what it does and set it up with minimal effort, while
the project stays fully transparent (plain Python scripts, no opaque
`.exe`). Distributed via GitHub (download ZIP, no git knowledge needed).

Two manual steps remain unavoidable and are documented clearly:
install Python, and obtain + paste a berget.ai API key.

### LR1 — Bundle ffmpeg via pip (remove hidden dependency)

`ffmpeg` is currently required (mp3 conversion of audio chunks) but never
documented — a non-technical user hits a cryptic crash. Replace the bare
`ffmpeg` PATH call with the binary shipped by the `imageio-ffmpeg` pip
package so it installs automatically with the other dependencies.

- Add `imageio-ffmpeg` to `requirements.txt`
- Resolve the ffmpeg binary path via `imageio_ffmpeg.get_ffmpeg_exe()`
  in `recorder.py` and `retranscribe.py`
- No behavior change to output; keeps `CREATE_NO_WINDOW` suppression

### LR2 — Guided one-time setup (`setup.bat`)

Transparent, plain-language setup a non-technical user can run by
double-clicking:

- Verify Python is installed; if not, point to the download with a clear
  message
- Create the `.venv` and `pip install -r requirements.txt`
- Prompt for the berget.ai API key and write `.env` (skip if already set)
- Echo each step so the user sees what is happening

### LR3 — Friendly first-run in the app

`tray.py` currently exits silently when the API key is missing (runs under
`pythonw`, so the user sees nothing). Replace with a clear GUI message box
directing the user to run `setup.bat`, for missing key and missing config.

### LR4 — README overhaul for public audience

- Plain-language "what it does" + privacy note (audio is sent to berget.ai)
- Prerequisites with direct links (Python, berget.ai signup)
- 4-step setup: install Python → download ZIP → run `setup.bat` → run
  `Recorder.bat`
- Screenshot/GIF placeholders (user supplies captures of the running app)
- Troubleshooting + FAQ

### LR5 — Repo hygiene

- Add `.env.example` (committed) documenting the two API key variables
- Add a `LICENSE` file
- Verify `.gitignore` never commits keys, recordings, logs, or config

---

## Technical decisions

- **Speaker identification:** Two-stream approach (mic vs. loopback)
  gives speaker identification for free. Distinguishes "Me" from
  "Others" but does not identify individual remote participants.
- **WASAPI loopback** captures all system audio, not just the meeting
  app. Other apps playing audio during a call will be included.
- **Transcription:** berget.ai API with kb-whisper-large
  (Swedish-optimized). No local model, no GPU needed.
- **LLM post-processing:** Mistral via berget.ai. Produces structured
  Swedish meeting notes. Temperature 0.3 for consistency.
- **System tray:** `pystray` + `Pillow` for icon generation. Lightweight,
  no heavy GUI framework.
- **Threading model:** Recording runs in a background thread. Two
  sub-threads capture mic and loopback simultaneously. Transcription
  and LLM processing run sequentially in the same background thread.
- **No timestamps in transcript:** Whisper segment timestamps are not
  used — the two-stream approach doesn't allow reliable chronological
  interleaving without diarization.

## Dependencies

- `pyaudiowpatch` — WASAPI loopback recording
- `pycaw` — Windows audio session enumeration (installed as dependency)
- `numpy` — audio array processing
- `scipy` — resampling
- `openai` — berget.ai API client (OpenAI-compatible)
- `pystray` — system tray
- `Pillow` — icon rendering for tray
- `plyer` — Windows toast notifications

## File structure

```
Recorder/
  recorder.py                 # core recording, transcription, and LLM logic
  tray.py                     # system tray application (entry point)
  vu_meter.py                 # floating VU meter window (tkinter)
  retranscribe.py             # re-transcribe existing WAV files
  create_startup_shortcut.vbs # add app to Windows startup
  config.example.json         # committed example config
  config.json                 # gitignored, user's real config
  .env                        # gitignored, API keys
  requirements.txt
  Recorder.bat
  README.md
  prd.md
```
