@echo off
setlocal
cd /d "%~dp0"
title FinCom Books
if exist "%~dp0FinComBooks.exe" (
    start "" "%~dp0FinComBooks.exe"
) else (
    powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0Launch.ps1"
)
