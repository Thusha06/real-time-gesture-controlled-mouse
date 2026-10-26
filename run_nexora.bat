@echo off
cd /d "%~dp0"
start "" "http://localhost:8765"
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" -m http.server 8765 --bind 127.0.0.1
) else (
  py -m http.server 8765 --bind 127.0.0.1
)
