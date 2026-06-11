#!/usr/bin/env python3
"""Floating recording pill: pulsing REC dot, elapsed time, live audio levels."""

import ctypes
import time
import tkinter as tk
from ctypes import wintypes


class AudioLevels:
    """Thread-safe shared state for audio levels (0.0 to 1.0)."""

    def __init__(self):
        self.mic_level = 0.0
        self.loopback_level = 0.0

    def update_mic(self, level: float):
        self.mic_level = level

    def update_loopback(self, level: float):
        self.loopback_level = level


# ── Look ──────────────────────────────────────────────────────

TRANSPARENT = "#010203"  # color key punched out of the window (rounded corners)
PILL_BG = "#1e1e1e"
PILL_BORDER = "#3a3a3a"
LABEL_FG = "#9e9e9e"
TEXT_FG = "#e0e0e0"
BAR_BG = "#383838"
GREEN = "#4caf50"
YELLOW = "#ffeb3b"
RED = "#f44336"
RED_DIM = "#6e2a26"

WIDTH = 240
HEIGHT = 66
RADIUS = 14
MARGIN = 16          # gap to the work-area corner
BAR_X = 64
BAR_WIDTH = WIDTH - BAR_X - 16
BAR_HEIGHT = 5
MIC_BAR_Y = 38
LB_BAR_Y = 51
POLL_MS = 50
PULSE_POLLS = 12     # REC dot toggles every 12 polls (~0.6 s)


def _level_color(level: float) -> str:
    if level > 0.8:
        return RED
    if level > 0.5:
        return YELLOW
    return GREEN


def _work_area() -> tuple[int, int, int, int]:
    """Desktop rectangle minus the taskbar: (left, top, right, bottom)."""
    rect = wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, 1920, 1040


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """Draw a rounded rectangle as a smoothed polygon. Returns the item id."""
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class VuMeterWindow:
    """Frameless always-on-top recording pill docked above the tray corner.

    Shows a pulsing REC dot, elapsed recording time, and live level bars for
    the microphone and the other participants. Draggable with the mouse.

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
        self._rec_start = 0.0
        self._pulse_count = 0
        self._pulse_on = True

    def _build(self):
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.overrideredirect(True)   # no title bar, no taskbar button
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.95)
        # Everything painted in the key color becomes a hole in the window,
        # which is what gives the pill its rounded corners.
        self._root.configure(bg=TRANSPARENT)
        self._root.attributes("-transparentcolor", TRANSPARENT)

        left, top, right, bottom = _work_area()
        x = right - WIDTH - MARGIN
        y = bottom - HEIGHT - MARGIN
        self._root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

        c = tk.Canvas(self._root, width=WIDTH, height=HEIGHT,
                      bg=TRANSPARENT, highlightthickness=0)
        c.pack()
        self._canvas = c

        _rounded_rect(c, 1, 1, WIDTH - 1, HEIGHT - 1, RADIUS,
                      fill=PILL_BG, outline=PILL_BORDER)

        # Header row: pulsing dot, REC label, elapsed timer
        self._dot = c.create_oval(14, 12, 26, 24, fill=RED, outline="")
        c.create_text(33, 18, text="REC", fill=TEXT_FG, anchor="w",
                      font=("Segoe UI", 10, "bold"))
        self._timer = c.create_text(WIDTH - 16, 18, text="00:00",
                                    fill=TEXT_FG, anchor="e",
                                    font=("Consolas", 11))

        # Level rows
        c.create_text(14, MIC_BAR_Y + 3, text="MIC", fill=LABEL_FG, anchor="w",
                      font=("Segoe UI", 8))
        c.create_rectangle(BAR_X, MIC_BAR_Y, BAR_X + BAR_WIDTH,
                           MIC_BAR_Y + BAR_HEIGHT, fill=BAR_BG, outline="")
        self._mic_bar = c.create_rectangle(BAR_X, MIC_BAR_Y, BAR_X,
                                           MIC_BAR_Y + BAR_HEIGHT,
                                           fill=GREEN, outline="")

        c.create_text(14, LB_BAR_Y + 3, text="OTHERS", fill=LABEL_FG, anchor="w",
                      font=("Segoe UI", 8))
        c.create_rectangle(BAR_X, LB_BAR_Y, BAR_X + BAR_WIDTH,
                           LB_BAR_Y + BAR_HEIGHT, fill=BAR_BG, outline="")
        self._lb_bar = c.create_rectangle(BAR_X, LB_BAR_Y, BAR_X,
                                          LB_BAR_Y + BAR_HEIGHT,
                                          fill=GREEN, outline="")

        # Drag support
        self._drag_x = 0
        self._drag_y = 0
        c.bind("<Button-1>", self._on_drag_start)
        c.bind("<B1-Motion>", self._on_drag_motion)

    def _on_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_motion(self, event):
        x = self._root.winfo_x() + event.x - self._drag_x
        y = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _update_bar(self, bar_id, y1, level: float):
        w = int(level * BAR_WIDTH)
        self._canvas.coords(bar_id, BAR_X, y1, BAR_X + w, y1 + BAR_HEIGHT)
        self._canvas.itemconfig(bar_id, fill=_level_color(level))

    def _poll(self):
        if not self._polling:
            return
        self._update_bar(self._mic_bar, MIC_BAR_Y, self._levels.mic_level)
        self._update_bar(self._lb_bar, LB_BAR_Y, self._levels.loopback_level)

        elapsed = int(time.monotonic() - self._rec_start)
        self._canvas.itemconfig(
            self._timer, text=f"{elapsed // 60:02d}:{elapsed % 60:02d}")

        self._pulse_count += 1
        if self._pulse_count >= PULSE_POLLS:
            self._pulse_count = 0
            self._pulse_on = not self._pulse_on
            self._canvas.itemconfig(
                self._dot, fill=RED if self._pulse_on else RED_DIM)

        self._root.after(POLL_MS, self._poll)

    def _tick(self):
        """Periodic check for visibility and stop flags."""
        if self._stopped:
            self._root.quit()
            return
        if self._visible and not self._polling:
            self._polling = True
            self._rec_start = time.monotonic()
            self._pulse_count = 0
            self._pulse_on = True
            self._canvas.itemconfig(self._dot, fill=RED)
            # Re-apply: some Tk builds drop overrideredirect after withdraw
            self._root.overrideredirect(True)
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
