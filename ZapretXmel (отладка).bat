@echo off
:: Запуск с видимой консолью: сюда попадут ошибки, которых не видно
:: при обычном запуске через pythonw. Окно не закроется само.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto :no_venv

echo Запуск ZapretXmel с выводом в консоль...
echo.
".venv\Scripts\python.exe" -m app %*

echo.
echo Приложение завершилось с кодом %errorlevel%.
pause
exit /b 0

:no_venv
echo Не найдено окружение .venv
pause
exit /b 1
