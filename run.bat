@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 未找到虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
