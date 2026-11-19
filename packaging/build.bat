@echo off
rem Build Mnemo from the project root inside an activated venv.
pip install -q pyinstaller PyQt6
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean Mnemo.spec
if errorlevel 1 exit /b 1
echo.
echo Done: dist\Mnemo\Mnemo.exe
