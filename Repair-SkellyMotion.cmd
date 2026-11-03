@echo off
setlocal
title SkellyMotion - Repair Windows runtime DLL
echo.
echo   SKELLYMOTION - WINDOWS RUNTIME REPAIR
echo   ------------------------------------
echo   Only use this on a copy you downloaded from your own trusted
echo   SkellyMotion GitHub build.
echo.
set "SKELLY_RUNTIME_DLL=%~dp0_internal\pythonnet\runtime\Python.Runtime.dll"
if not exist "%SKELLY_RUNTIME_DLL%" (
  echo [ERROR] Python.Runtime.dll was not found.
  echo The application folder may be incomplete.
  echo Download the complete Windows artifact and extract it ONCE.
  echo Keep SkellyMotion.exe and _internal in the same folder.
  echo.
  pause
  exit /b 2
)
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $dll=$env:SKELLY_RUNTIME_DLL; try { $blocked = Get-Item -LiteralPath $dll -Stream Zone.Identifier -ErrorAction SilentlyContinue; if ($null -eq $blocked) { Write-Host '[INFO] No downloaded-file block was detected on Python.Runtime.dll.' -ForegroundColor Yellow; Write-Host 'If SkellyMotion still fails, inspect the desktop.log and ensure .NET Framework 4.6.2+ is installed.'; exit 0 }; Write-Host '[FOUND] Windows downloaded-file security marker on:' -ForegroundColor Yellow; Write-Host $dll; $answer = Read-Host 'Remove the download block from THIS DLL only? [Y/N]'; if ($answer -notmatch '^[Yy]$') { Write-Host 'No files were changed.'; exit 1 }; Unblock-File -LiteralPath $dll -ErrorAction Stop; Write-Host '[OK] The trusted bundled Python.Runtime.dll was unblocked.' -ForegroundColor Green; Write-Host 'Close and relaunch SkellyMotion.exe.'; exit 0 } catch { Write-Host ('Repair failed: ' + $_.Exception.Message) -ForegroundColor Red; exit 3 }"
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%
