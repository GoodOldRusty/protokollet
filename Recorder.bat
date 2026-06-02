@echo off
title Meeting Recorder

:: Activate venv if present
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: Copy example config if no config exists
if not exist "config.json" (
    if exist "config.example.json" (
        copy config.example.json config.json
        echo Created config.json from example. Edit it if needed.
    )
)

:: Launch the app windowless. Prefer the venv interpreter explicitly so the
:: bundled dependencies (incl. ffmpeg) are always used, regardless of PATH.
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" tray.py
) else (
    start "" pythonw tray.py
)
