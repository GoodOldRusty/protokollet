# Meeting Recorder

**Version:** 1.1.0
**Author:** Jan Soja
**Created:** 2026-03-26

Records meetings via manual start/stop and transcribes using
berget.ai's kb-whisper-large (Swedish-optimized). Runs as a Windows
system tray application. No GPU required.

---

## Quick Start

1. Install Python 3.10+
2. Create a virtual environment and install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your berget.ai API key:
   ```
   BERGET_API_KEY=your-api-key-here
   ```
4. Double-click `run.bat` (or run `python tray.py`)
5. Right-click the tray icon and click **Start Recording** when your
   meeting begins
6. Click **Stop Recording** when it ends
7. Transcripts are saved to `~/Recordings/<timestamp>/transcript.txt`

## How It Works

1. **Start** — Right-click the tray icon and click "Start Recording".
2. **Recording** — Captures two separate audio streams:
   - **Microphone** (your voice)
   - **System loopback** (other participants via WASAPI)
3. **Stop** — Click "Stop Recording" when the meeting ends.
4. **Transcription** — Each stream is sent to berget.ai's API
   (kb-whisper-large) for transcription. Mic audio is labeled "Me",
   loopback is labeled "Others".
5. **Output** — A speaker-labeled transcript:
   ```
   Others: Welcome everyone, let's get started.
   Me: Hi, thanks for setting this up.
   ```

### System Tray

| Icon Color | Meaning        |
| ---------- | -------------- |
| Grey       | Ready          |
| Red        | Recording      |
| Blue       | Transcribing   |

Right-click the tray icon for:
- **Start Recording** / **Stop Recording** — manual control
- **Open Recordings** — opens the output folder
- **Settings...** — opens `config.json` in your default editor
- **Quit** — clean shutdown

A Windows notification appears when transcription is complete.

### Configuration

Edit `config.json` (created automatically on first run):

| Key              | Default                      | Description                          |
| ---------------- | ---------------------------- | ------------------------------------ |
| `whisper_model`  | `"KBLab/kb-whisper-large"`   | Whisper model on berget.ai           |
| `language`       | `"sv"`                       | Transcription language               |
| `keep_audio`     | `false`                      | Keep WAV files after transcription   |
| `min_seconds`    | `30`                         | Discard recordings shorter than this |
| `output_dir`     | `"~/Recordings"`             | Where to save recordings             |
| `api_base_url`   | `"https://api.berget.ai/v1"` | API endpoint                         |
| `prompt`         | *(domain terms)*             | Vocabulary hints for better accuracy |

### Domain Vocabulary

The `prompt` field in `config.json` helps the model recognize
domain-specific terms. Edit it to match your work context:

```json
"prompt": "Power BI, SQL Server, SSIS, SSRS, SSAS, Git, Azure DevOps, DAX, T-SQL, ETL, Data Warehouse"
```

Add or remove terms as needed. No restart required — the config is
read fresh each recording.

## Technical Notes

- **Speaker identification** uses the two-stream approach (mic vs.
  loopback) rather than a diarization model. This means it distinguishes
  "Me" from "Others" but does not identify individual remote
  participants.
- **WASAPI loopback** captures all system audio, not just Teams. If
  other apps play audio during a call, it will be included in the
  "Others" stream.
- **API cost** is approximately 0.00005 EUR/second (~0.09 EUR for a
  30 min meeting).
- Recordings under `min_seconds` are automatically discarded.

---

## Changelog

### v1.1.0 (2026-03-26)
- Switch from local Whisper to berget.ai API (kb-whisper-large)
- Manual start/stop recording via tray menu
- Domain vocabulary hints via `prompt` config
- Fix loopback audio distortion (stereo downmix)
- Remove ffmpeg dependency
- Remove timestamps from transcript output

### v1.0.0 (2026-03-26)
- Initial release
- Dual-stream recording (mic + loopback)
- Speaker-labeled transcripts
- System tray application with status indicators
- Windows toast notifications on completion
- Configurable via `config.json`
