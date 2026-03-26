# Meeting Recorder

**Version:** 1.0.0
**Author:** Jan Soja
**Created:** 2026-03-26

Automatically records Microsoft Teams calls and produces timestamped,
speaker-labeled transcripts using local Whisper inference. Runs as a
Windows system tray application.

---

## Quick Start

1. Install Python 3.10+
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Double-click `run.bat` (or run `python tray.py`)
4. The app appears in the system tray — that's it. It monitors for
   Teams calls automatically.
5. Transcripts are saved to `~/Recordings/<timestamp>/transcript.txt`

## How It Works

1. **Monitoring** — Polls Windows audio sessions every few seconds to
   detect when Teams starts using audio (i.e., a call begins).
2. **Recording** — Captures two separate audio streams:
   - **Microphone** (your voice)
   - **System loopback** (other participants via WASAPI)
3. **Transcription** — After the call ends, each stream is transcribed
   independently using OpenAI Whisper (runs locally, no API calls).
   Mic audio is labeled "Me", loopback is labeled "Others".
4. **Output** — Segments are merged chronologically into a timestamped
   transcript:
   ```
   [00:00:12] Others: Welcome everyone, let's get started.
   [00:00:18] Me: Hi, thanks for setting this up.
   ```

### System Tray

| Icon Color | Meaning               |
| ---------- | --------------------- |
| Orange     | Loading Whisper model  |
| Grey       | Idle — monitoring      |
| Red        | Recording a call       |
| Blue       | Transcribing           |

Right-click the tray icon for:
- **Open Recordings** — opens the output folder
- **Settings...** — opens `config.json` in your default editor
- **Quit** — clean shutdown

A Windows notification appears when transcription is complete.

### Configuration

Edit `config.json` (created automatically on first run):

| Key              | Default       | Description                          |
| ---------------- | ------------- | ------------------------------------ |
| `whisper_model`  | `"large-v3"`  | Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `language`       | `"sv"`        | Transcription language (`null` = auto-detect) |
| `keep_audio`     | `false`       | Keep WAV files after transcription   |
| `poll_seconds`   | `5`           | Seconds between call detection polls |
| `min_seconds`    | `30`          | Discard recordings shorter than this |
| `output_dir`     | `"~/Recordings"` | Where to save recordings          |

## Technical Notes

- **Speaker identification** uses the two-stream approach (mic vs.
  loopback) rather than a diarization model. This means it distinguishes
  "Me" from "Others" but does not identify individual remote
  participants.
- **Whisper model** `large-v3` requires ~10 GB VRAM. Use `medium` or
  `small` for less capable GPUs. CPU inference works but is slow.
- **WASAPI loopback** captures all system audio, not just Teams. If
  other apps play audio during a call, it will be included in the
  "Others" stream.
- Recordings under `min_seconds` are automatically discarded (handles
  accidental short calls).

---

## Changelog

### v1.0.0 (2026-03-26)
- Initial release
- Auto-detect Teams calls via Windows audio sessions
- Dual-stream recording (mic + loopback)
- Timestamped, speaker-labeled transcripts
- System tray application with status indicators
- Windows toast notifications on completion
- Configurable via `config.json`
