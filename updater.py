"""热更新：下载新版本 zip → 解压 → 生成 updater.bat → 覆盖重启（借鉴 GD）。"""
import os
import sys
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request

from app_info import APP_REPO

before_apply = None  # 应用更新前的回调（保存任务等），由 main 设置


def exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def download_update(version, progress_cb=None):
    """下载免安装 zip 到临时目录，返回 zip 路径。失败抛异常。"""
    url = (f"https://github.com/{APP_REPO}/releases/download/"
           f"v{version}/FFmpegGUI-Portable-Windows-x64.zip")
    tmpdir = tempfile.mkdtemp(prefix="ffmpegGUI_upd_")
    zippath = os.path.join(tmpdir, "update.zip")
    req = urllib.request.Request(url, headers={"User-Agent": "FFmpegGUI"})
    with urllib.request.urlopen(req, timeout=120) as r, \
            open(zippath, "wb") as f:
        total = int(r.headers.get("Content-Length", 0) or 0)
        done = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress_cb and total:
                progress_cb(done / total)
    return zippath


def apply_update(zippath):
    """解压 zip → 生成并启动 updater.bat（等主程序退出→覆盖→重启）。"""
    if before_apply:
        before_apply()
    base = os.path.dirname(zippath)
    extract_dir = os.path.join(base, "new")
    with zipfile.ZipFile(zippath) as zf:
        zf.extractall(extract_dir)
    # 免安装 zip 内是 FFmpegGUI/ 目录
    inner = os.path.join(extract_dir, "FFmpegGUI")
    if not os.path.isdir(inner):
        inner = extract_dir
    bat = os.path.join(base, "updater.bat")
    _write_bat(bat, os.getpid(), inner, exe_dir())
    subprocess.Popen(
        ["cmd", "/c", bat],
        creationflags=(subprocess.DETACHED_PROCESS
                       | subprocess.CREATE_NEW_PROCESS_GROUP),
        close_fds=True)
    return bat


def _write_bat(bat, pid, new_dir, target_dir, exe_name="ffmpegGUI.exe"):
    content = f'''@echo off
chcp 65001 >nul
set "PID={pid}"
set "NEW={new_dir}"
set "TARGET={target_dir}"
set "EXE={exe_name}"
:waitloop
tasklist /FI "PID eq %PID%" 2>nul | findstr /I "%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
robocopy "%NEW%" "%TARGET%" /E /IS /IT /NFL /NDL /NJH /NJS /NP >nul
start "" "%TARGET%\\%EXE%"
rmdir /S /Q "%NEW%" 2>nul
del "%~f0" 2>nul
'''
    with open(bat, "w", encoding="utf-8") as f:
        f.write(content)
