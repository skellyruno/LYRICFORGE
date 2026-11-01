@echo off
setlocal
cd /d "%~dp0"
title LYRICFORGE Studio
where ffmpeg >nul 2>&1
if errorlevel 1 (
 echo.
 echo [ERROR] FFmpeg is not installed or is not in PATH.
 echo Download FFmpeg and add its bin folder to PATH, then run again.
 pause
 exit /b 1
)
where ffprobe >nul 2>&1
if errorlevel 1 (
 echo [ERROR] ffprobe is required with FFmpeg.
 pause
 exit /b 1
)
if not exist .venv\Scripts\python.exe (
 echo Creating Python virtual environment...
 py -3.12 -m venv .venv 2>nul
 if errorlevel 1 py -3.11 -m venv .venv 2>nul
 if errorlevel 1 python -m venv .venv
 if errorlevel 1 (
   echo [ERROR] Install Python 3.11 or 3.12 first.
   pause
   exit /b 1
 )
 echo Installing LyricForge dependencies (first launch only)...
 .venv\Scripts\python.exe -m pip install -r requirements.txt
 if errorlevel 1 (
   echo [ERROR] Python package installation failed.
   pause
   exit /b 1
 )
)
echo.
echo LYRICFORGE is starting at http://127.0.0.1:8000
echo Press Ctrl+C in this window to stop the studio.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000'"
.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
pause
