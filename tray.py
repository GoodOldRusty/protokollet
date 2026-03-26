#!/usr/bin/env python3
"""
System tray wrapper for Meeting Recorder.
Runs the recorder in the background with a tray icon.
"""

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from recorder import (
    RecorderState,
    load_config,
    monitor_loop,
)

log = logging.getLogger("tray")

# ── Icon drawing ──────────────────────────────────────────────

COLORS = {
    RecorderState.IDLE: "#888888",
    RecorderState.RECORDING: "#e53935",
    RecorderState.TRANSCRIBING: "#1e88e5",
    RecorderState.LOADING: "#ffa726",
}

STATUS_LABELS = {
    RecorderState.IDLE: "Idle - monitoring",
    RecorderState.RECORDING: "Recording...",
    RecorderState.TRANSCRIBING: "Transcribing...",
    RecorderState.LOADING: "Loading model...",
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
        # plyer not installed or notification failed — not critical
        log.debug("Toast notification failed", exc_info=True)

# ── Tray app ──────────────────────────────────────────────────


class TrayApp:
    def __init__(self):
        self.cfg = load_config()
        self.state = RecorderState()
        self.stop_event = threading.Event()
        self.icon = None
        self.model = None
        self.p = None

        self.state.on_change(self._on_state_change)

    def _on_state_change(self, status: str):
        if self.icon:
            self.icon.icon = create_icon_image(COLORS[status])
            self.icon.title = f"Meeting Recorder - {STATUS_LABELS[status]}"

    def _open_recordings(self):
        folder = self.cfg["output_dir"]
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _open_settings(self):
        from recorder import CONFIG_PATH
        os.startfile(str(CONFIG_PATH))

    def _quit(self):
        self.stop_event.set()
        if self.icon:
            self.icon.stop()

    def _on_transcript(self, path: str):
        notify("Meeting recorded", f"Transcript saved:\n{Path(path).name}")

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: STATUS_LABELS.get(self.state.status, "Unknown"),
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Recordings", lambda item: self._open_recordings()),
            pystray.MenuItem("Settings...", lambda item: self._open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda item: self._quit()),
        )

    def _worker(self):
        """Background thread: load model, then monitor."""
        import pyaudiowpatch as pyaudio
        import whisper

        log.info("Loading Whisper (%s)...", self.cfg["whisper_model"])
        self.model = whisper.load_model(self.cfg["whisper_model"])
        log.info("Model ready.")

        self.state.set(RecorderState.IDLE)

        self.p = pyaudio.PyAudio()
        try:
            monitor_loop(
                self.p, self.model, self.cfg, self.state,
                self.stop_event, self._on_transcript,
            )
        finally:
            self.p.terminate()

    def run(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(message)s",
            datefmt="%H:%M:%S",
        )

        self.icon = pystray.Icon(
            name="meeting-recorder",
            icon=create_icon_image(COLORS[RecorderState.LOADING]),
            title=f"Meeting Recorder - {STATUS_LABELS[RecorderState.LOADING]}",
            menu=self._build_menu(),
        )

        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()

        self.icon.run()


if __name__ == "__main__":
    app = TrayApp()
    app.run()
