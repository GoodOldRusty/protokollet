#!/usr/bin/env python3
"""Floating VU meter window for real-time audio level monitoring."""

import tkinter as tk


class AudioLevels:
    """Thread-safe shared state for audio levels (0.0 to 1.0)."""

    def __init__(self):
        self.mic_level = 0.0
        self.loopback_level = 0.0

    def update_mic(self, level: float):
        self.mic_level = level

    def update_loopback(self, level: float):
        self.loopback_level = level


# ── Colors ────────────────────────────────────────────────────

BG = "#2b2b2b"
LABEL_FG = "#cccccc"
BAR_BG = "#444444"
GREEN = "#4caf50"
YELLOW = "#ffeb3b"
RED = "#f44336"

BAR_WIDTH = 200
BAR_HEIGHT = 18
POLL_MS = 50


def _level_color(level: float) -> str:
    if level > 0.8:
        return RED
    if level > 0.5:
        return YELLOW
    return GREEN


class VuMeterWindow:
    """Small floating always-on-top window with two VU meter bars.

    All tkinter objects are created in run() which must be called from
    the thread that will own the mainloop. show()/hide()/stop() are
    safe to call from any thread — they only set flags that the tkinter
    thread polls.
    """

    def __init__(self, levels: AudioLevels):
        self._levels = levels
        self._root = None
        self._visible = False
        self._stopped = False
        self._polling = False

    def _build(self):
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("Audio Levels")
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.85)
        self._root.configure(bg=BG)
        self._root.resizable(False, False)
        self._root.geometry("270x60+20+20")
        # Minimal window: disable close button, no min/max
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = tk.Frame(self._root, bg=BG, padx=8, pady=6)
        frame.pack(fill="both", expand=True)

        # Mic row
        tk.Label(frame, text="MIC", fg=LABEL_FG, bg=BG,
                 font=("Consolas", 9), width=3, anchor="w").grid(row=0, column=0)
        self._mic_canvas = tk.Canvas(frame, width=BAR_WIDTH, height=BAR_HEIGHT,
                                     bg=BAR_BG, highlightthickness=0)
        self._mic_canvas.grid(row=0, column=1, padx=(4, 0))
        self._mic_bar = self._mic_canvas.create_rectangle(0, 0, 0, BAR_HEIGHT, fill=GREEN)

        # Loopback row
        tk.Label(frame, text="LB", fg=LABEL_FG, bg=BG,
                 font=("Consolas", 9), width=3, anchor="w").grid(row=1, column=0, pady=(4, 0))
        self._lb_canvas = tk.Canvas(frame, width=BAR_WIDTH, height=BAR_HEIGHT,
                                    bg=BAR_BG, highlightthickness=0)
        self._lb_canvas.grid(row=1, column=1, padx=(4, 0), pady=(4, 0))
        self._lb_bar = self._lb_canvas.create_rectangle(0, 0, 0, BAR_HEIGHT, fill=GREEN)

        # Drag support
        self._drag_x = 0
        self._drag_y = 0
        self._root.bind("<Button-1>", self._on_drag_start)
        self._root.bind("<B1-Motion>", self._on_drag_motion)

    def _on_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_motion(self, event):
        x = self._root.winfo_x() + event.x - self._drag_x
        y = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _update_bar(self, canvas, bar_id, level: float):
        w = int(level * BAR_WIDTH)
        color = _level_color(level)
        canvas.coords(bar_id, 0, 0, w, BAR_HEIGHT)
        canvas.itemconfig(bar_id, fill=color)

    def _poll(self):
        if not self._polling:
            return
        self._update_bar(self._mic_canvas, self._mic_bar, self._levels.mic_level)
        self._update_bar(self._lb_canvas, self._lb_bar, self._levels.loopback_level)
        self._root.after(POLL_MS, self._poll)

    def _tick(self):
        """Periodic check for visibility and stop flags."""
        if self._stopped:
            self._root.quit()
            return
        if self._visible and not self._polling:
            self._polling = True
            self._root.deiconify()
            self._poll()
        elif not self._visible and self._polling:
            self._polling = False
            self._root.withdraw()
        self._root.after(200, self._tick)

    def show(self):
        self._visible = True

    def hide(self):
        self._visible = False

    def run(self):
        """Create the window and enter mainloop. Call from a dedicated thread."""
        self._build()
        self._root.after(200, self._tick)
        self._root.mainloop()

    def stop(self):
        self._stopped = True
