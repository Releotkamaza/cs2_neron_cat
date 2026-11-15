@echo off
set PYTHONDONTWRITEBYTECODE=1
rem Работаем всегда в папке чита, откуда бы батник ни запустили:
rem output/ и cs2-dumper.exe должны находиться рядом с main.py, а не в cwd.
cd /d "%~dp0"
if exist "output" (
    rmdir /s /q "output" >nul 2>&1
)
"%~dp0cs2-dumper.exe" -f json >nul 2>&1
if exist "cs2-dumper.log" del /f /q "cs2-dumper.log" >nul 2>&1
python main.py
pause
