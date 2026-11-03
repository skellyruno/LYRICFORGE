@echo off
setlocal
set "APP=%~dp0SkellyMotion.exe"
if not exist "%APP%" (
  echo SkellyMotion.exe is missing. Extract the full GitHub artifact into one folder.
  pause
  exit /b 2
)
start "" "%APP%" --safe-mode
exit /b 0
