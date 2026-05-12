@echo off
cd /d "%~dp0"

uv run .\jira_integration\main.py

if %ERRORLEVEL% neq 0 (
    echo Script failed with exit code %ERRORLEVEL%
    pause
)
