@echo off
setlocal
title SkellyMotion - Windows native UI repair
echo.
echo  SKELLYMOTION - REPAIR BLOCKED WINDOWS UI DLLs
echo  ---------------------------------------------
echo  Run this only on SkellyMotion downloaded from
echo  YOUR trusted GitHub repository.
echo.
set "APP=%~dp0SkellyMotion.exe"
if not exist "%APP%" (
  echo [ERROR] SkellyMotion.exe was not found beside this file.
  echo Extract the complete Windows download into one folder.
  pause
  exit /b 2
)
if not exist "%~dp0_internal\pythonnet\runtime\Python.Runtime.dll" (
  echo [ERROR] The _internal Python.NET runtime is missing.
  echo Download a new complete artifact and extract it ONCE.
  pause
  exit /b 2
)
echo The app will list any download-blocked managed UI libraries
echo and ask permission before repairing those specific files.
echo No projects, downloaded AI models, or Windows security settings
echo will be deleted or disabled.
echo.
start "" /wait "%APP%" --repair-runtime
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Repair cancelled or incomplete. Exit code: %RESULT%
  echo Review %%LOCALAPPDATA%%\LyricForge\logs\desktop.log
) else (
  echo.
  echo Runtime repair check completed.
  echo Try opening SkellyMotion.exe again.
)
echo.
pause
exit /b %RESULT%
