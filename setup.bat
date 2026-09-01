@echo off
cd /d "%~dp0"
python -m venv .venv
pip install -r requirements.txt
certutil -urlcache -split -f https://github.com/a2x/cs2-dumper/releases/latest/download/cs2-dumper.exe cs2-dumper.exe >nul 2>&1
pause