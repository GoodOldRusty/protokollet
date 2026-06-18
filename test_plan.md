# Test Plan — v1.7.1 Readiness

Manual verification for the public-launch changes. The ideal test is on a
**clean Windows machine** (or a fresh user account) that has never run the
app, to confirm the zero-to-recording experience.

Automated checks already passing: `recorder.py`, `retranscribe.py`,
`tray.py` compile; bundled ffmpeg resolves and converts a WAV to mp3;
`config.example.json` is valid JSON; the `.env` written by `setup.bat`
parses correctly with `load_env()`.

---

## A. First-time setup (clean machine)

| # | Step | Expected |
|---|------|----------|
| A1 | Without Python installed, double-click `setup.bat` | Clear message: Python not found, with the python.org link and the "Add to PATH" instruction. Window pauses, does not crash. |
| A2 | Install Python 3.10+ (tick "Add python.exe to PATH"), run `setup.bat` again | Step [1/4] shows the found version; [2/4] creates `.venv`; [3/4] installs dependencies without error; [4/4] prompts for the API key. |
| A3 | Paste a valid berget.ai key at the prompt | Prints "Saved." A `.env` file appears with `BERGET_API_KEY=<your key>` and an empty `BERGET_API_KEY2=`. |
| A4 | Run `setup.bat` a second time | [2/4] says "Already set up - skipping"; [4/4] says the `.env` already exists and is left unchanged. No errors. |

## B. First run / missing key

| # | Step | Expected |
|---|------|----------|
| B1 | Temporarily rename `.env`, then double-click `Recorder.bat` | A message box appears: "setup needed / No berget.ai API key was found / run setup.bat". No tray icon is left running. |
| B2 | Restore `.env`, double-click `Recorder.bat` | Round grey icon appears in the system tray. No console window flashes. |

## C. Recording → transcription (the main flow)

| # | Step | Expected |
|---|------|----------|
| C1 | Right-click tray → Start Recording | Icon turns red; the recording pill appears — a frameless dark pill docked above the tray corner with a pulsing REC dot, an elapsed timer, and live MIC/OTHERS level bars reacting to mic + system audio. |
| C2 | Speak, and play some audio through the speakers, for >30s | Both the MIC and OTHERS bars on the pill move. |
| C3 | Right-click tray → Stop Recording | Icon turns blue (transcribing). **No PowerShell/CMD windows flash** during this step (the ffmpeg fix). |
| C4 | Wait for completion | Toast notification appears; icon returns to grey. |
| C5 | Right-click tray → Open Recordings | The output folder contains TWO files: `transkript.md` (raw speaker-labeled transcript, written before the summary) and the protokoll `YYYY-MM-DD_HH-MM_<topic>.md` with Sammanfattning / Beslut / Åtgärdspunkter / Mötesanteckningar plus a link back to the transcript (`*Rå transkribering: [transkript.md](transkript.md)*`) — not an embedded "Rå transkribering" section. |

## D. ffmpeg bundling (the LR1 goal)

| # | Step | Expected |
|---|------|----------|
| D1 | Confirm ffmpeg is NOT installed system-wide (`where ffmpeg` in a normal terminal returns nothing) | Transcription in section C still succeeds — proving the bundled `imageio-ffmpeg` binary is used. |

## E. Edge cases

| # | Step | Expected |
|---|------|----------|
| E1 | Record for less than `min_seconds` (default 30s) and stop | Recording is discarded; no transcript file is produced. |
| E2 | Cancel during transcription (Cancel Transcription menu item) | Transcription aborts cleanly; icon returns to grey. |
| E3 | Open `recorder.log` after a session | Contains run info; contains **no** API key value. |

## F. Repo hygiene

| # | Step | Expected |
|---|------|----------|
| F1 | `git status` after a full session | `.env`, `config.json`, `recorder.log`, recordings are all untracked/ignored — never staged. |
| F2 | Inspect committed files | `.env.example` contains only a placeholder key; `config.example.json` prompt is the generic placeholder; `LICENSE` present. |

## G. Offline resilience & resume

| # | Step | Expected |
|---|------|----------|
| G1 | Disconnect from the network, then Stop Recording | Tray icon turns **orange** (Waiting for connection — transcription queued); a toast says the recording is saved and will transcribe once back online; the recording pill closes. |
| G2 | Reconnect to the network (connectivity is rechecked ~every 15 s) | Transcription resumes automatically; the tray goes blue (transcribing) then back to grey, and the protokoll appears in the folder. |
| G3 | While orange (waiting), Quit the app, then relaunch `Recorder.bat` | The `.pending` marker survived, so the recording is picked up and transcribed on the next start; during a resume batch the tray tooltip shows `(N queued)`. |
| G4 | While orange (waiting), choose Cancel Transcription | The `.pending` marker is removed; the recording is **never** auto-resumed later, but the audio is kept so it can be finished manually with `retranscribe.py`. |
| G5 | Resume a folder that already has `transkript.md` (summary-only retry) | Only the LLM summary is redone — no audio is needed and no transcription is re-paid; the protokoll is produced. |

## H. Long-meeting summary (no hang)

| # | Step | Expected |
|---|------|----------|
| H1 | Record or resume a meeting whose transcript is long enough that the LLM summary takes more than ~2 minutes | The summary completes (300 s timeout, single retry) and the protokoll is written — no multi-minute hang or repeated-timeout failure like the old 120 s limit produced. |

---

## Known limitations (by design)

- `setup.bat` writes the pasted key verbatim. A key containing cmd special
  characters (`& | < > ^ %`) could be corrupted — berget.ai keys are
  alphanumeric/dash so this is not expected in practice.
- `api_base_url` from `config.json` is used without validation (local-trust
  model; changing it requires write access to the user's own config).
