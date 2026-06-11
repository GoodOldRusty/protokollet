# protokollet

*Swedish-first meeting recorder for Windows — records, transcribes, and writes the minutes.*

*Läs detta på [svenska](README.md).*

**Version:** 1.6.1
**Author:** Jan Soja
**Created:** 2026-03-26

protokollet is a small Windows app that lives in your system tray.
You click **Start** when a meeting begins and **Stop** when it ends — it
records both your microphone and the other participants, transcribes the
conversation, and saves tidy meeting notes (summary, decisions, and action
items) as a text file you can read in any editor.

It is built for Swedish meetings (using a Swedish-optimised speech model)
but works for other languages too. No GPU or special hardware is needed.

> **Privacy note:** Your audio is sent to the [berget.ai](https://berget.ai)
> service for transcription and summarisation. Nothing is uploaded anywhere
> else, and recordings stay on your computer. Only use this for meetings you
> are allowed to record — check local rules and tell participants.

---

## Quick Start

You only do steps 1–3 once. After that, recording is just step 4.

### 1. Install Python (one time)

Download and install Python 3.10 or newer from
**[python.org/downloads](https://www.python.org/downloads/)**.

> ⚠️ On the first installer screen, tick the box
> **"Add python.exe to PATH"** before clicking Install. This one checkbox
> is what lets the rest of the setup work automatically.

### 2. Download protokollet

On the GitHub page, click the green **Code** button → **Download ZIP**.
Then right-click the downloaded file → **Extract All** to a folder you'll
remember (e.g. `Documents\protokollet`).

*(If you know Git, you can `git clone` instead — same result.)*

### 3. Run the setup

Double-click **`setup.bat`** in the folder. A window opens and walks you
through everything:

- checks that Python is installed
- installs the components the app needs
- asks you to paste your **berget.ai API key**

You get a free API key by signing up at **[berget.ai](https://berget.ai)**.
Copy the key, paste it into the setup window when asked, and press Enter.

When it says *"Setup complete!"* you're done.

### 4. Record a meeting

1. Double-click **`Recorder.bat`**. A round icon appears in your system
   tray (bottom-right of the screen, near the clock).
2. **Right-click the icon → Start Recording** when your meeting begins.
3. **Right-click the icon → Stop Recording** when it ends.
4. After a short transcription, a notification appears and your notes are
   saved to `Documents\Recordings` (your user folder) as a `.md` file —
   for example `2026-04-01_14-31_budgetplanering-q3.md`.

---

## Screenshots

> 📷 _These are placeholders. Capture the images on your own machine, save
> them in a `docs/` folder, and uncomment the matching line below._

<!-- ![The tray icon and right-click menu](docs/tray-menu.png) -->
<!-- ![The recording pill during recording](docs/recording-pill.png) -->
<!-- ![Example meeting notes output](docs/example-notes.png) -->

Suggested captures: (1) the tray menu open, (2) the recording pill while
recording, (3) an example output `.md` file opened in an editor.

---

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

| Icon Color | Meaning                                          |
| ---------- | ------------------------------------------------ |
| Grey       | Ready                                            |
| Red        | Recording                                        |
| Blue       | Transcribing                                     |
| Orange     | Waiting for connection (transcription queued)    |

Right-click the tray icon for:
- **Start Recording** / **Stop Recording** — manual control
- **Cancel Transcription** — abort an in-progress transcription
- **Open Recordings** — opens the output folder
- **Settings...** — opens `config.json` in your default editor
- **Quit** — clean shutdown

While recording, a small always-on-top pill docked above the tray corner
shows a pulsing **REC** indicator, the elapsed time, and live audio levels
for your mic and the other participants — drag it anywhere you like. A
Windows notification appears when transcription is complete.

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

---

## Troubleshooting

**Nothing happens when I double-click `setup.bat`, or it says Python was
not found.**
Python isn't installed, or the "Add python.exe to PATH" box wasn't ticked
during install. Re-install Python from
[python.org](https://www.python.org/downloads/), making sure to tick that
box, then run `setup.bat` again.

**I started the app but no tray icon appears.**
If you haven't entered an API key yet, a message box will tell you to run
`setup.bat`. The icon may also be hidden — click the small upward arrow
(^) in the system tray to show hidden icons.

**Transcription fails or the icon stays blue.**
Check your internet connection and that your berget.ai key is valid and
has credit. Use **Cancel Transcription** from the menu, then try again.
Technical details are written to `recorder.log` in the app folder.

**The "Others" track includes music or other app sounds.**
Loopback captures *all* system audio. Mute other apps (browser, music)
during meetings.

---

## FAQ

**Do I need a powerful computer?**
No. All the heavy processing happens on berget.ai's servers. Any modern
Windows PC works.

**Does it cost money?**
The app is free. berget.ai charges a small amount per minute of audio
(see API cost in Technical Notes — roughly 0.09 EUR for a 30-minute
meeting). You need a berget.ai account.

**Where are my recordings saved?**
In a `Recordings` folder inside your user folder by default. Use
**Open Recordings** from the tray menu to jump straight there.

**Can it record without me clicking Start?**
No — recording is always manual, by design. You decide when it captures.

**Does my audio leave my computer?**
Only the audio is sent to berget.ai for transcription. See the privacy
note at the top.

**What happens if I'm offline when the meeting ends?**
A notification tells you the recording is saved and that transcription
starts automatically as soon as you're back online (checked every
15 seconds) — the tray icon shows orange while waiting. This survives restarts: if you close the app or shut the
computer down first, the recording is picked up and transcribed the next
time the app starts. **Cancel Transcription** cancels the wait — a
cancelled recording is never transcribed automatically, but the audio is
kept so you can run `retranscribe.py` manually.

---

## Technical Notes

- **No manual ffmpeg install** — audio chunk conversion uses the ffmpeg
  binary bundled by the `imageio-ffmpeg` package, installed automatically
  during setup.
- **Speaker identification** uses the two-stream approach (mic vs.
  loopback) rather than a diarization model. This means it distinguishes
  you from "Others" but does not identify individual remote participants.
- **WASAPI loopback** captures all system audio, not just the meeting
  app. If other apps play audio during a call, it will be included in
  the "Others" stream.
- **Offline detection** — when you stop a recording, a quick TCP check
  against the API host decides whether to transcribe immediately or wait.
  While waiting, connectivity is re-checked every 15 seconds and
  transcription resumes automatically. New recordings can't start until
  the wait finishes or is cancelled.
- **Pending marker** — a `.pending` file in the recording folder marks a
  transcription that is owed. It is removed on success or cancel and kept
  on failure or shutdown, so the app resumes unfinished transcriptions at
  the next start. `retranscribe.py` clears it too.
- **Chunked transcription** — audio files are split into 2-minute
  chunks, converted to mp3, and sent individually with automatic retry.
  This avoids API timeouts on long recordings.
- **Recording pill** — a frameless always-on-top tkinter window (rounded
  corners via a transparent color key) with a pulsing REC dot, elapsed
  timer, and live level bars for mic and loopback; docked to the
  bottom-right corner of the work area, draggable.
- **API cost** — transcription is ~0.00005 EUR/second (~0.09 EUR for
  a 30 min meeting). LLM summary costs fractions of a cent per meeting.
- Recordings under `min_seconds` are automatically discarded.
- If transcription is cancelled or fails, the raw audio (`mic.wav`,
  `loopback.wav`) is kept in the recording folder — even when `keep_audio`
  is false — so you can finish it later with
  `python retranscribe.py "<recording folder>"`.
- Two API keys are supported: `BERGET_API_KEY` for whisper,
  `BERGET_API_KEY2` for the LLM (falls back to `BERGET_API_KEY` if
  not set).

---

## Changelog

### v1.6.1 (2026-06-11)
- Fix: **Cancel Transcription** could appear stuck for up to 10 minutes
  when the transcription service stopped answering mid-request. API calls
  now time out after 60 seconds and retrying is handled entirely by the
  app's own cancellable retry loop
- Fix: a folder that already contains a transcript is never re-transcribed
  at startup, even if its pending marker was left behind

### v1.6.0 (2026-06-11)
- New: the audio-levels window is now a recording pill — frameless and
  dark, docked above the tray corner, with a pulsing REC dot, elapsed
  recording time, and slim live level bars for mic and participants.
  Still draggable

### v1.5.2 (2026-06-11)
- New: a distinct orange tray state shows when the app is waiting for
  connectivity (previously indistinguishable from transcribing), and the
  tray tooltip shows how many recordings are queued during a startup
  resume. **Cancel Transcription** is available in the orange state too

### v1.5.1 (2026-06-11)
- New: unfinished transcriptions now survive restarts. Recordings awaiting
  transcription are marked on disk (`.pending`) and resume automatically
  the next time the app starts — e.g. if you shut the laptop while
  offline. Cancel removes the mark (a cancelled recording is never
  auto-transcribed); `retranscribe.py` clears it after manual recovery
- The offline and failure notifications no longer ask you to keep the app
  running or run `retranscribe.py` — recovery is automatic

### v1.5.0 (2026-06-11)
- New: stopping a recording while offline now shows an immediate
  notification that transcription is postponed, and it starts
  automatically as soon as you're back online (connectivity is checked
  every 15 seconds; **Cancel Transcription** works while waiting and the
  audio is always kept)

### v1.4.2 (2026-06-11)
- Fix: a failed transcription (for example when offline) now shows a
  notification saying the audio is saved and how to recover it with
  `retranscribe.py` — previously the app silently returned to idle with
  no feedback
- Fix: leftover chunk WAV files are now cleaned up when transcription
  fails mid-way (previously only on cancel)

### v1.4.1 (2026-06-04)
- Fix: a long recording's save could take minutes while the icon still showed
  red ("Recording"); clicking Stop again during that window cancelled
  transcription and discarded the audio. The icon now shows "processing"
  as soon as Stop is pressed, stray clicks during saving are ignored, and
  cancelled transcriptions now **keep** the audio for recovery via
  `retranscribe.py` instead of deleting it
- Fix: leftover chunk WAV files are now cleaned up when transcription is cancelled

### v1.4.0 (2026-06-02)
- One-step guided setup via `setup.bat`: checks Python, creates the
  environment, installs dependencies, and saves your API key
- ffmpeg is now bundled automatically (`imageio-ffmpeg`) — no manual install
- Friendly first-run dialog when the API key is missing (previously the
  app exited silently with no feedback)
- Suppressed the console windows that flashed during transcription
- Added `.env.example`, an MIT `LICENSE`, and a public-facing README with
  troubleshooting and FAQ
- Runtime log files are no longer committed

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
