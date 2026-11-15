@echo off
rem ============================================================================
rem  Тихий запуск neron_cat: БЕЗ окна консоли.
rem
rem  1) пересоздаёт output\ - свежий дамп оффсетов под текущую сборку CS2
rem     (cs2-dumper.exe кладёт туда offsets.json, client_dll.json и т.д.);
rem  2) запускает main.py через pythonw.exe - интерпретатор без окна консоли;
rem  3) весь вывод приложения (логи) уходит в cache\neron_cat.log.
rem
rem  Остановка: хоткей End. Консоль закрывать не нужно - её нет.
rem  Полностью скрытый запуск (без мигания окна .bat) - 
rem ============================================================================
setlocal
set PYTHONDONTWRITEBYTECODE=1
cd /d "%~dp0"

rem --- 1. Свежий дамп оффсетов (нужен под текущую сборку CS2) ---
rem Старый дамп удаляем, чтобы его случайно не подхватил загрузчик геометрии.
if exist "output" rmdir /s /q "output" >nul 2>&1
"%~dp0cs2-dumper.exe" -f json >nul 2>&1
if exist "cs2-dumper.log" del /f /q "cs2-dumper.log" >nul 2>&1

rem --- 2. Запуск БЕЗ консоли ---
rem pythonw.exe - тот же интерпретатор, но без окна консоли. Ищем его в PATH.
set PYW=
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set PYW=%%i
if not defined PYW (
  echo pythonw.exe не найден в PATH - запускаю обычный python ^(с консолью^)
  python main.py
  goto :eof
)
rem start - запуск отдельным процессом; окно cmd закрывается сразу.
start "" "%PYW%" "%~dp0main.py"
endlocal
