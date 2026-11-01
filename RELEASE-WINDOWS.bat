@echo off
setlocal
cd /d "%~dp0"
title Release SkellyMotion Windows
where git >nul 2>&1
if errorlevel 1 (
 echo Install Git for Windows first.
 pause
 exit /b 1
)
set /p VERSION=Enter NEW version tag (example v1.0.0): 
if "%VERSION%"=="" exit /b 1
if not "%VERSION:~0,1%"=="v" (
 echo Version must start with v.
 pause
 exit /b 1
)
git tag %VERSION%
if errorlevel 1 goto :fail
git push origin %VERSION%
if errorlevel 1 goto :fail
echo.
echo GitHub Actions is building your Windows release.
echo Check: https://github.com/skellyruno/LYRICFORGE/actions
pause
exit /b 0
:fail
echo Git failed. Check the version tag is new and the repo is pushed.
pause
exit /b 1
