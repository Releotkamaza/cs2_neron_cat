@echo off
if exist "output" (
    rmdir /s /q "output" >nul 2>&1
)
cs2-dumper.exe -f json >nul 2>&1
if exist "cs2-dumper.log" del /f /q "cs2-dumper.log" >nul 2>&1
cd /d "%~dp0"
python main.py
pause