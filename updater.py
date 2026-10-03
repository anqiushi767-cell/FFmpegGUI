"""热更新：下载新版本 zip → 解压 → 生成 updater.bat → 覆盖重启（借鉴 GD）。"""
import os
import sys
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
import urllib.error

from app_info import APP_REPO

before_apply = None  # 应用更新前的回调（保存任务等），由 main 设置


class UpdateError(Exception):
    """更新失败（错误信息可以直接展示给用户）。"""


def exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def download_update(version, progress_cb=None):
    """下载免安装 zip 到临时目录，返回 zip 路径。失败抛 UpdateError。"""
    url = (f"https://github.com/{APP_REPO}/releases/download/"
           f"v{version}/FFmpegGUI-Portable-Windows-x64.zip")
    tmpdir = tempfile.mkdtemp(prefix="ffmpegGUI_upd_")
    zippath = os.path.join(tmpdir, "update.zip")
    req = urllib.request.Request(url, headers={"User-Agent": "FFmpegGUI"})
    total = 0
    done = 0
    try:
        with urllib.request.urlopen(req, timeout=120) as r, \
                open(zippath, "wb") as f:
            total = int(r.headers.get("Content-Length", 0) or 0)
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(done / total)
    except urllib.error.HTTPError as e:
        raise UpdateError(
            f"HTTP {e.code}（该版本可能还没上传免安装包，"
            f"可到 Releases 页手动下载）") from e
    except urllib.error.URLError as e:
        raise UpdateError(f"网络不可达（{getattr(e, 'reason', e)}）") from e
    # 断网/超时中断时 urlopen 不报错但内容少一截，这里补一道校验
    if total and done != total:
        raise UpdateError(f"下载不完整（{done}/{total} 字节），请重试")
    verify_update_package(zippath)
    return zippath


def verify_update_package(zippath):
    """校验下载到的更新包：能打开、非空、含主程序、CRC 完好。"""
    try:
        with zipfile.ZipFile(zippath) as zf:
            names = zf.namelist()
            if not names:
                raise UpdateError("更新包是空的")
            if not any(n.lower().endswith("ffmpeggui.exe") for n in names):
                raise UpdateError("更新包里没有 ffmpegGUI.exe，已中止更新")
            broken = zf.testzip()
            if broken:
                raise UpdateError(f"更新包已损坏（{broken}），请重试")
    except zipfile.BadZipFile as e:
        raise UpdateError("更新包已损坏，请重试或到 Releases 页手动下载") from e


def apply_update(zippath):
    """解压 zip → 生成并启动 updater.bat（等主程序退出→覆盖→重启）。"""
    verify_update_package(zippath)  # 覆盖安装目录前再确认一次，别把程序覆盖坏
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
    if not os.path.isfile(os.path.join(inner, "ffmpegGUI.exe")):
        raise UpdateError("解压后没找到 ffmpegGUI.exe，已中止更新（原程序未改动）")
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
