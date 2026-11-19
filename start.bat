@echo off
rem Launch the current sources without leaving a console window open.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto setup
".venv\Scripts\python.exe" -c "import PyQt6.QtWidgets, PyQt6.QtNetwork" >nul 2>&1
if errorlevel 1 goto setup
start "" ".venv\Scripts\pythonw.exe" "%~dp0src\mnemo\launcher.py"
exit /b
:setup
call run.bat
