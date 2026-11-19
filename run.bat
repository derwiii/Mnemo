@echo off
rem Run Mnemo from sources (creates .venv on first run).
cd /d %~dp0
if not exist .venv\Scripts\python.exe python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q PyQt6
set PYTHONPATH=src
python -m mnemo
