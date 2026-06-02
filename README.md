# Meeting Recorder

**Version:** 1.3.0
**Author:** Jan Soja
**Created:** 2026-03-26

Records meetings via manual start/stop, transcribes using berget.ai's
kb-whisper-large (Swedish-optimized), and produces structured meeting
notes with summary, decisions, and action items via LLM post-processing.
Runs as a Windows system tray application. No GPU required.

---

## Quick Start

1. Install Python 3.10+
2. Create a virtual environment and install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your berget.ai API keys:
   ```
   BERGET_API_KEY=your-whisper-api-key
   BERGET_API_KEY2=your-llm-api-key
   ```
   If you use the same key for both, just set `BERGET_API_KEY`.
4. Double-click `Recorder.bat` (or run `python tray.py`)
5. Right-click the tray icon and click **Start Recording** when your
   meeting begins
6. Click **Stop Recording** when it ends
7. Meeting notes are saved to `~/Recordings/<timestamp>_<topic>.md`

## How It Works

1. **Start** — Right-click the tray icon and click "Start Recording".
2. **Recording** — Captures two separate audio streams:
   - **Microphone** (your voice)
   - **System loopback** (other participants via WASAPI)
3. **Stop** — Click "Stop Recording" when the meeting ends.
4. **Transcription** — Each stream is sent to berget.ai's API
   (kb-whisper-large) for transcription. Mic audio is labeled with
   your name (configurable), loopback is labeled "Others".
5. **LLM Summary** — The raw transcript is processed by Mistral to
   produce structured meeting notes.
6. **Output** — A descriptively named markdown file (e.g.
   `2026-04-01_14-31_budgetplanering-q3.md`) with:

   ```markdown
   # Mötesprotokoll 2026-03-26 14:30

   ## Sammanfattning
   Brief meeting summary...

   ## Beslut
   - Key decisions made

   ## Åtgärdspunkter
   - Action items with owners

   ## Mötesanteckningar
   Cleaned-up prose version of the conversation...

   ---

   ## Rå transkribering
   Jan: original transcribed text...
   Others: original transcribed text...
   ```

### System Tray

| Icon Color | Meaning        |
| ---------- | -------------- |
| Grey       | Ready          |
| Red        | Recording      |
| Blue       | Transcribing   |

Right-click the tray icon for:
- **Start Recording** / **Stop Recording** — manual control
- **Cancel Transcription** — abort an in-progress transcription
- **Open Recordings** — opens the output folder
- **Settings...** — opens `config.json` in your default editor
- **Quit** — clean shutdown

A floating VU meter window shows real-time mic and loopback levels
during recording. A Windows notification appears when transcription
is complete.

### Configuration

Edit `config.json` (created automatically on first run):

| Key              | Default                      | Description                          |
| ---------------- | ---------------------------- | ------------------------------------ |
| `whisper_model`  | `"KBLab/kb-whisper-large"`   | Whisper model on berget.ai           |
| `llm_model`      | `"mistralai/Mistral-Small-3.2-24B-Instruct-2506"` | LLM for summary |
| `my_name`        | `"Me"`                       | Your name in the transcript          |
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
"prompt": "Power BI, SQL Server, SSIS, SSRS, SSAS, Azure DevOps, DAX, T-SQL, ETL..."
```

Add or remove terms as needed. The Whisper prompt field is capped at
224 tokens — the default list uses 213. No restart required — the
config is read fresh each recording.

## Technical Notes

- **Speaker identification** uses the two-stream approach (mic vs.
  loopback) rather than a diarization model. This means it distinguishes
  you from "Others" but does not identify individual remote participants.
- **WASAPI loopback** captures all system audio, not just the meeting
  app. If other apps play audio during a call, it will be included in
  the "Others" stream.
- **Chunked transcription** — audio files are split into 2-minute
  chunks, converted to mp3, and sent individually with automatic retry.
  This avoids API timeouts on long recordings.
- **VU meter** — a floating tkinter window displays real-time audio
  levels for mic and loopback during recording.
- **API cost** — transcription is ~0.00005 EUR/second (~0.09 EUR for
  a 30 min meeting). LLM summary costs fractions of a cent per meeting.
- Recordings under `min_seconds` are automatically discarded.
- Two API keys are supported: `BERGET_API_KEY` for whisper,
  `BERGET_API_KEY2` for the LLM (falls back to `BERGET_API_KEY` if
  not set).

---

## Changelog

### v1.3.0 (2026-06-02)
- Floating VU meter window shows real-time mic and loopback levels during recording
- Auto-start on Windows login via startup shortcut
- Chunked mp3 transcription with retry for API reliability (large files split into 2-min chunks)
- Cancel support for in-progress recording and transcription
- Descriptive transcript filenames derived from LLM-generated meeting title
- Graceful fallback to raw transcript if LLM summarization fails
- Fix: handle empty audio frames without crashing
- Fix: VU meter threading and cleanup on stop

### v1.2.0 (2026-03-26)
- LLM post-processing: structured markdown output with summary,
  decisions, action items, and cleaned-up meeting notes
- Configurable speaker name (`my_name` in config)
- Separate API key support for LLM endpoint (`BERGET_API_KEY2`)
- Expanded domain vocabulary (213/224 Whisper tokens)
- Renamed launcher to `Recorder.bat`

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
