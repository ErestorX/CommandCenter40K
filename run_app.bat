@echo off
cd /d "%~dp0"
echo Started %date% %time% > run_log.txt
".venv\Scripts\python.exe" -X faulthandler main.py >> run_log.txt 2>&1
echo Exit code %errorlevel% >> run_log.txt
