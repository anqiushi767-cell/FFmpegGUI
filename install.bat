@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo   FFmpeg 转码器 - 依赖安装
echo ==========================================
echo.
echo 需要下载两个包：PySide6 + PySide6-Fluent-Widgets
echo 共约 200-400MB，视网络而定
echo.
echo [1] 官方源 PyPI（默认）
echo [2] 清华镜像（国内更快）
echo.
set /p choice=选 1 或 2，直接回车默认 1：

if "%choice%"=="2" goto mirror
goto official

:official
echo.
echo 正在创建虚拟环境...
uv venv --python 3.11
echo 正在从官方源安装...
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
goto done

:mirror
echo.
echo 正在创建虚拟环境...
uv venv --python 3.11
echo 正在从清华镜像安装...
uv pip install --python .venv\Scripts\python.exe -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
goto done

:done
echo.
if exist ".venv\Scripts\python.exe" (
    echo 安装完成！双击 run.bat 启动。
) else (
    echo 安装失败，请截图发我。
)
pause
