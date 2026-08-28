@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "wheels" (
    echo 没找到 wheels 文件夹！
    echo 请把 whl 文件下载到本目录下的 wheels 文件夹里。
    pause
    exit /b 1
)
echo 正在安装（无需联网，本地安装）...
uv pip install --python .venv\Scripts\python.exe --no-index --find-links .\wheels PySide6 PySide6-Fluent-Widgets
echo.
if errorlevel 1 (
    echo 安装失败，请截图发我。
) else (
    echo 安装完成！双击 run.bat 启动。
)
pause
