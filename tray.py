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
    load_config,
    record_meeting,
)
from vu_meter import AudioLevels, VuMeterWindow

log = logging.getLogger("tray")

# ── Icon drawing ──────────────────────────────────────────────

COLORS = {
    RecorderState.IDLE: "#888888",
    RecorderState.RECORDING: "#e53935",
    RecorderState.TRANSCRIBING: "#1e88e5",
}

STATUS_LABELS = {
    RecorderState.IDLE: "Ready",
    RecorderState.RECORDING: "Recording...",
    RecorderState.TRANSCRIBING: "Transcribing...",
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

        self.state.on_change(self._on_state_change)

    def _on_state_change(self, status: str):
        if self.icon:
            self.icon.icon = create_icon_image(COLORS[status])
            self.icon.title = f"Meeting Recorder - {STATUS_LABELS[status]}"
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

        self.stop_recording = threading.Event()
        self.recording_thread = threading.Thread(
            target=record_meeting,
            args=(self.p, self.client, self.cfg, self.state,
                  self.stop_recording, self._on_transcript),
            kwargs={"audio_levels": self.audio_levels},
            daemon=True,
        )
        self.recording_thread.start()

    def _stop_recording(self):
        if self.state.status not in (RecorderState.RECORDING, RecorderState.TRANSCRIBING):
            return
        if self.stop_recording:
            self.stop_recording.set()

    def _quit(self):
        if self.stop_recording:
            self.stop_recording.set()
        if self.vu_window:
            self.vu_window.stop()
        if self.icon:
            self.icon.stop()

    def _on_transcript(self, path: str):
        notify("Meeting recorded", f"Transcript saved:\n{Path(path).name}")

    def _is_idle(self, item):
        return self.state.status == RecorderState.IDLE

    def _is_recording(self, item):
        return self.state.status == RecorderState.RECORDING

    def _is_transcribing(self, item):
        return self.state.status == RecorderState.TRANSCRIBING

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

        # Tkinter requires the main thread on Windows
        self.vu_window = VuMeterWindow(self.audio_levels)
        self.vu_window.run()  # blocks until stop() is called


if __name__ == "__main__":
    app = TrayApp()
    app.run()
