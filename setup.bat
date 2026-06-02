@echo off
setlocal
title Meeting Recorder - Setup
cd /d "%~dp0"

echo ==================================================
echo    Meeting Recorder - Setup
echo ==================================================
echo.
echo This will install everything Meeting Recorder needs
echo and ask for your berget.ai API key. It is safe to
echo run again at any time.
echo.

REM --- Step 1: check Python -----------------------------------------
echo [1/4] Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo    Python was not found on this computer.
    echo.
    echo    Please install Python 3.10 or newer from:
    echo        https://www.python.org/downloads/
    echo.
    echo    IMPORTANT: on the first install screen, tick the box
    echo    "Add python.exe to PATH". Then run this setup again.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo    Found %%v

REM --- Step 2: create virtual environment ---------------------------
echo.
echo [2/4] Creating a private environment for the app (.venv)...
if exist ".venv\Scripts\python.exe" (
    echo    Already set up - skipping.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo    Could not create the environment. Setup stopped.
        pause
        exit /b 1
    )
    echo    Done.
)

REM --- Step 3: install dependencies ---------------------------------
echo.
echo [3/4] Installing components (this can take a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo    Installation failed. Check your internet connection
    echo    and run this setup again.
    pause
    exit /b 1
)
echo    Done.

REM --- Step 4: API key ----------------------------------------------
echo.
echo [4/4] Setting up your berget.ai API key...
if exist ".env" (
    echo    A key file (.env) already exists - leaving it unchanged.
    echo    To change your key, edit .env or delete it and run setup again.
    goto :finish
)
echo.
echo    You need a free berget.ai account and an API key.
echo    Get one here: https://berget.ai
echo.
set "APIKEY="
set /p "APIKEY=   Paste your API key here and press Enter: "
if not defined APIKEY (
    echo.
    echo    No key entered. The app will remind you to run setup
    echo    again the first time you start it.
    goto :finish
)
> .env echo # Meeting Recorder - API keys
>> .env echo BERGET_API_KEY=%APIKEY%
>> .env echo BERGET_API_KEY2=
echo    Saved.

:finish
echo.
echo ==================================================
echo    Setup complete!
echo    Double-click Recorder.bat to start the app.
echo    Look for the round icon in your system tray.
echo ==================================================
echo.
pause
