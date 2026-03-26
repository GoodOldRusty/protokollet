# Meeting Recorder — PRD

## Overview

A Windows system tray application that automatically detects Microsoft
Teams calls, records both sides of the conversation (mic + system audio),
and produces a timestamped, speaker-labeled transcript using local
Whisper inference. No data leaves the machine.

## Goals

- Fully automatic: start the app, forget about it, find transcripts later
- Speaker identification: distinguish "Me" (mic) from "Others" (loopback)
- Timestamped output: know when each segment was spoken
- System tray: runs quietly in the background with minimal UI
- Local only: no API calls, no cloud services, all processing on-device

## Non-goals

- Support for apps other than Teams
- Cloud-based transcription
- Real-time transcription during calls
- Summarization or post-processing with LLMs
- Cross-platform support (Windows only)

---

## Feature blocks

### FB1 — Project setup and config

Set up the project structure with a `config.json` for all user-facing
settings.

**Config file (`config.json`):**

| Key              | Type   | Default       | Description                          |
| ---------------- | ------ | ------------- | ------------------------------------ |
| `whisper_model`  | string | `"large-v3"`  | Whisper model size                   |
| `language`       | string | `"sv"`        | Transcription language (null=auto)   |
| `keep_audio`     | bool   | `false`       | Keep WAV after transcription         |
| `poll_seconds`   | int    | `5`           | How often to check for active call   |
| `min_seconds`    | int    | `30`          | Discard recordings shorter than this |
| `output_dir`     | string | `"~/Recordings"` | Where to save recordings          |

Provide a `config.example.json` (committed) and `.gitignore` the real
`config.json`. If `config.json` is missing at startup, copy from example.

### FB2 — Core recording engine

Refactor the existing recording logic into clean, testable functions.

- Detect Teams calls via Windows audio sessions (pycaw)
- Record loopback (system audio) and mic as **separate streams**
- Keep streams separate through mixing — save as stereo WAV
  (left = mic, right = loopback) or two mono files, whichever makes
  diarization simpler in FB3
- Poll for call end, then stop recording
- Discard recordings under `min_seconds`
- Save to `output_dir/<YYYY-MM-DD_HH-MM>/`

### FB3 — Transcription with speaker labels and timestamps

Transcribe using local Whisper. Leverage the two separate audio streams
to identify speakers:

- Transcribe each stream independently (mic = "Me", loopback = "Others")
- Merge segments chronologically by timestamp
- Output format in `transcript.txt`:

```
[00:00:12] Others: Welcome everyone, let's get started.
[00:00:18] Me: Hi, thanks for setting this up.
[00:00:25] Others: So the first item on the agenda...
```

- Consecutive segments from the same speaker should be merged if the gap
  is small (< 2 seconds)
- Use Whisper's segment-level timestamps

### FB4 — System tray application

Wrap the recorder in a system tray app using `pystray`.

- Tray icon with status indicator:
  - Idle (grey) — monitoring for calls
  - Recording (red) — call in progress
  - Transcribing (blue) — processing after call
- Right-click menu:
  - "Open Recordings" — opens output folder in Explorer
  - "Status: Idle/Recording/Transcribing" — informational, disabled
  - "Settings..." — opens `config.json` in default editor
  - "Quit" — clean shutdown
- Startup behavior:
  - Load config
  - Load Whisper model (show "Loading model..." status)
  - Begin monitoring
- Notification (Windows toast) when transcription is complete:
  "Meeting recorded — transcript saved"

### FB5 — Launcher and packaging

- `run.bat` — one-click launcher: activates venv (if present) and runs
  the app
- Updated `requirements.txt` with all dependencies
- README with setup instructions

---

## Technical decisions

- **Speaker diarization approach:** Since we already capture mic and
  loopback separately, we get speaker identification for free —
  no need for pyannote or other diarization models. "Me" = mic stream,
  "Others" = loopback stream.
- **Whisper variant:** Use `openai-whisper` (local). User can pick model
  size via config. No `faster-whisper` for now (can revisit if perf is
  an issue).
- **System tray:** `pystray` + `Pillow` for icon generation. Lightweight,
  no heavy GUI framework.
- **Threading model:** Recording threads (existing pattern) + main thread
  for tray. Transcription runs in a background thread to keep tray
  responsive.

## Dependencies

Existing:
- `pyaudiowpatch` — WASAPI loopback recording
- `pycaw` — Windows audio session detection
- `numpy`, `scipy` — audio processing
- `openai-whisper` — transcription
- `ffmpeg` — required by Whisper (external)

New:
- `pystray` — system tray
- `Pillow` — icon rendering for tray

## File structure

```
meeting-recorder/
  recorder.py           # main entry point
  config.example.json   # committed example config
  config.json           # gitignored, user's real config
  requirements.txt
  run.bat
  README.md
  prd.md
```
