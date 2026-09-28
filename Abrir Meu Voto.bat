@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python app\server.py
pause
