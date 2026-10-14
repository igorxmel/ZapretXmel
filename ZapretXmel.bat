@echo off
:: Запуск приложения. Права администратора приложение запросит само.
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" goto :no_venv

start "" ".venv\Scripts\pythonw.exe" -m app %*
exit /b 0

:no_venv
echo Не найдено окружение .venv
echo Создайте его командой:
echo     python -m venv .venv
echo     .venv\Scripts\pip install -e ".[dev]"
pause
exit /b 1
