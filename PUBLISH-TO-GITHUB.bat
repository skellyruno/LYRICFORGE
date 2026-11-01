@echo off
setlocal
cd /d "%~dp0"
title Publish SkellyMotion to GitHub
where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Install Git for Windows from https://git-scm.com/download/win first.
  pause
  exit /b 1
)
echo Before continuing, create an EMPTY repository named LYRICFORGE at:
echo   https://github.com/new
set /p ANSWER=Have you created the empty repository under skellyruno? [Y/N]: 
if /I not "%ANSWER%"=="Y" exit /b 1
if not exist .git git init
if errorlevel 1 goto :fail
git branch -M main
if errorlevel 1 goto :fail
git add .
if errorlevel 1 goto :fail
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Set up SkellyMotion web and Windows releases"
  if errorlevel 1 goto :fail
)
git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin https://github.com/skellyruno/LYRICFORGE.git
  if errorlevel 1 goto :fail
)
git push -u origin main
if errorlevel 1 goto :fail
echo.
echo SUCCESS: Code pushed to GitHub.
echo See: https://github.com/skellyruno/LYRICFORGE/actions
pause
exit /b 0
:fail
echo.
echo [ERROR] Git failed. Check that the repository exists,
echo your Git username/email are configured, and GitHub sign-in succeeded.
pause
exit /b 1
