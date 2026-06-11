#!/usr/bin/env python3
"""
System tray wrapper for Meeting Recorder.
Manual start/stop recording via tray menu.
"""

import logging
import os
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from openai import OpenAI

from recorder import (
    RecorderState,
    find_pending,
    load_config,
    record_meeting,
    transcribe_folder,
)
from vu_meter import AudioLevels, VuMeterWindow

log = logging.getLogger("tray")

# ── Icon drawing ──────────────────────────────────────────────

COLORS = {
    RecorderState.IDLE: "#888888",
    RecorderState.RECORDING: "#e53935",
    RecorderState.TRANSCRIBING: "#1e88e5",
    RecorderState.WAITING: "#fb8c00",
}

STATUS_LABELS = {
    RecorderState.IDLE: "Ready",
    RecorderState.RECORDING: "Recording...",
    RecorderState.TRANSCRIBING: "Transcribing...",
    RecorderState.WAITING: "Waiting for connection...",
}


def create_icon_image(color: str) -> Image.Image:
    """Draw a simple filled circle icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=color,
        outline="#ffffff",
        width=2,
    )
    return img

# ── Toast notification ────────────────────────────────────────


def notify(title: str, message: str):
    """Show a Windows toast notification."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="Meeting Recorder",
            timeout=5,
        )
    except Exception:
        log.debug("Toast notification failed", exc_info=True)


def show_error(title: str, message: str):
    """Show a blocking error dialog. The app runs under pythonw (no console),
    so a silent log would leave a first-time user with no feedback at all."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        log.error("%s: %s", title, message)

# ── Tray app ──────────────────────────────────────────────────


class TrayApp:
    def __init__(self):
        self.cfg = load_config()
        self.state = RecorderState()
        self.icon = None
        self.client = None
        self.p = None
        self.stop_recording = None
        self.recording_thread = None
        self.audio_levels = AudioLevels()
        self.vu_window = None
        self.vu_thread = None
        self.resume_thread = None
        self.pending_count = 0

        self.state.on_change(self._on_state_change)

    def _on_state_change(self, status: str):
        if self.icon:
            label = STATUS_LABELS[status]
            if self.pending_count > 1 and status in (
                    RecorderState.TRANSCRIBING, RecorderState.WAITING):
                label += f" ({self.pending_count} queued)"
            self.icon.icon = create_icon_image(COLORS[status])
            self.icon.title = f"Meeting Recorder - {label}"
            self.icon.update_menu()
        if self.vu_window:
            if status == RecorderState.RECORDING:
                self.vu_window.show()
            else:
                self.vu_window.hide()

    def _open_recordings(self):
        folder = self.cfg["output_dir"]
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _open_settings(self):
        from recorder import CONFIG_PATH
        os.startfile(str(CONFIG_PATH))

    def _start_recording(self):
        if self.state.status != RecorderState.IDLE:
            return
        # The resume batch owns self.stop_recording; replacing it mid-batch
        # would detach its cancel handling. Block new recordings until done.
        if self.resume_thread and self.resume_thread.is_alive():
            return

        self.stop_recording = threading.Event()
        self.recording_thread = threading.Thread(
            target=record_meeting,
            args=(self.p, self.client, self.cfg, self.state,
                  self.stop_recording, self._on_transcript),
            kwargs={"audio_levels": self.audio_levels,
                    "on_error": self._on_transcription_failed,
                    "on_offline": self._on_offline,
                    "on_online": self._on_online},
            daemon=True,
        )
        self.recording_thread.start()

    def _stop_recording(self):
        if self.state.status not in (RecorderState.RECORDING,
                                     RecorderState.TRANSCRIBING,
                                     RecorderState.WAITING):
            return
        if self.stop_recording:
            self.stop_recording.set()

    def _quit(self):
        # Signal stop only while recording (gives the save a chance). While
        # transcribing, stop means "cancel" and would remove the pending
        # marker — quit must leave the marker so the work resumes at next
        # start; the daemon thread dies with the process either way.
        if self.stop_recording and self.state.status == RecorderState.RECORDING:
            self.stop_recording.set()
        if self.vu_window:
            self.vu_window.stop()
        if self.icon:
            self.icon.stop()

    def _on_transcript(self, path: str):
        notify("Meeting recorded", f"Transcript saved:\n{Path(path).name}")

    def _on_transcription_failed(self, folder: str):
        notify(
            "Transcription failed — audio saved",
            f"Your recording is kept in {Path(folder).name}.\n"
            "It will be retried next time the app starts.",
        )

    def _on_offline(self, folder: str):
        notify(
            "You're offline — recording saved",
            "Transcription starts automatically\n"
            "when you're back online.",
        )

    def _on_online(self):
        notify("Back online", "Transcribing your meeting now...")

    def _resume_pending(self, folders):
        try:
            for i, folder in enumerate(folders):
                if self.stop_recording.is_set():
                    # Cancel stops the batch; untouched folders keep their
                    # pending marker and are picked up at the next app start.
                    log.info("Resume cancelled - remaining folders left for next start")
                    break
                self.pending_count = len(folders) - i
                self.state.set(RecorderState.TRANSCRIBING)
                try:
                    transcribe_folder(folder, self.client, self.cfg, self.state,
                                      self.stop_recording,
                                      on_transcript=self._on_transcript,
                                      on_error=self._on_transcription_failed,
                                      on_offline=self._on_offline,
                                      on_online=self._on_online)
                except Exception:
                    # Marker stays; this folder is retried at next start.
                    log.exception("Resume of %s crashed", folder)
        finally:
            self.pending_count = 0
            self.state.set(RecorderState.IDLE)

    def _is_idle(self, item):
        return self.state.status == RecorderState.IDLE

    def _is_recording(self, item):
        return self.state.status == RecorderState.RECORDING

    def _is_transcribing(self, item):
        # WAITING counts too: Cancel Transcription must stay available while
        # the app waits for connectivity.
        return self.state.status in (RecorderState.TRANSCRIBING,
                                     RecorderState.WAITING)

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: STATUS_LABELS.get(self.state.status, "Unknown"),
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start Recording",
                lambda item: self._start_recording(),
                visible=self._is_idle,
            ),
            pystray.MenuItem(
                "Stop Recording",
                lambda item: self._stop_recording(),
                visible=self._is_recording,
            ),
            pystray.MenuItem(
                "Cancel Transcription",
                lambda item: self._stop_recording(),
                visible=self._is_transcribing,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Recordings", lambda item: self._open_recordings()),
            pystray.MenuItem("Settings...", lambda item: self._open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda item: self._quit()),
        )

    def run(self):
        log_file = Path(__file__).parent / "recorder.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(message)s",
            datefmt="%H:%M:%S",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(log_file, encoding="utf-8"),
            ],
        )

        import pyaudiowpatch as pyaudio

        api_key = os.environ.get("BERGET_API_KEY", "")
        if not api_key:
            show_error(
                "Meeting Recorder — setup needed",
                "No berget.ai API key was found.\n\n"
                "Please run setup.bat to enter your API key, then start "
                "Meeting Recorder again.\n\n"
                "You can get a key at https://berget.ai",
            )
            return

        self.client = OpenAI(
            api_key=api_key,
            base_url=self.cfg["api_base_url"],
        )
        self.p = pyaudio.PyAudio()

        log.info("Ready. Using %s via berget.ai", self.cfg["whisper_model"])

        self.icon = pystray.Icon(
            name="meeting-recorder",
            icon=create_icon_image(COLORS[RecorderState.IDLE]),
            title=f"Meeting Recorder - {STATUS_LABELS[RecorderState.IDLE]}",
            menu=self._build_menu(),
        )

        # Run pystray in a background thread so tkinter can have the main thread
        tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        tray_thread.start()

        # Resume transcriptions that never finished (e.g. the app was closed
        # while offline). Started after the tray icon so state changes show.
        pending = find_pending(self.cfg)
        if pending:
            log.info("Resuming %d pending transcription(s)", len(pending))
            notify(
                "Unfinished recordings found",
                f"{len(pending)} recording(s) from earlier will be transcribed.",
            )
            # Enter TRANSCRIBING before the thread spawns so a Start Recording
            # click can never slip in between.
            self.pending_count = len(pending)
            self.state.set(RecorderState.TRANSCRIBING)
            self.stop_recording = threading.Event()
            self.resume_thread = threading.Thread(
                target=self._resume_pending, args=(pending,), daemon=True)
            self.resume_thread.start()

        # Tkinter requires the main thread on Windows
        self.vu_window = VuMeterWindow(self.audio_levels)
        self.vu_window.run()  # blocks until stop() is called


if __name__ == "__main__":
    app = TrayApp()
    app.run()
