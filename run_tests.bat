@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m unittest discover -s tests -t . -v > test_log.txt 2>&1
echo Exit code %errorlevel% >> test_log.txt
