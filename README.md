# FFmpegGUI

基于 FFmpeg 的批量音视频处理 GUI，把视频拖进来自动处理，支持 20 种操作。

## 功能

- **转码**：MP4 / MKV / WebM，三档画质，NVENC 硬件加速，并发可配置（1~8）
- **剪辑提取**：截取片段、抽帧封面、定点截图、提取音频（MP3/FLAC/WAV/AAC）、提取无声视频、音量归一化
- **合成特效**：GIF 动图、合并视频、变速、字幕烧录、去水印、元数据编辑
- **录屏与网络**：屏幕录制（可选音源/帧率/光标）、M3U8 流媒体下载
- **体验**：拖入即转码（支持文件夹递归）、实时进度 + ETA、失败重试、同名去重、系统托盘、深浅主题、任务持久化

## 项目结构

| 文件 | 用途 |
|---|---|
| `main.py` | 程序入口：主窗口 + 系统托盘 + 单实例保护 |
| `converter.py` | 核心引擎：FFmpeg 命令构建、任务调度、进度/速度/ETA 解析 |
| `task_page.py` | 任务页：拖放、任务卡片列表、各类操作入口 |
| `task_card.py` | 任务卡片：进度条 + 状态色 + 操作按钮 |
| `settings_page.py` | 设置页：输出目录 / 编码 / 主题 / 并发 / FFmpeg 引擎 |
| `about_page.py` | 关于页 |
| `config.py` | 配置管理（config.json 持久化） |
| `record_dialog.py` | 录屏设置弹窗 |
| `delogo_dialog.py` | 去水印选区弹窗 |
| `trim_dialog.py` | 片段选择弹窗（双滑块） |
| `logging_setup.py` | 崩溃日志 + 全局异常捕获 |
| `icon_gen.py` | 生成程序图标 app.ico |
| `installer.iss` | Inno Setup 安装脚本 |
| `requirements.txt` | Python 依赖 |
| `install.bat` / `run.bat` | 安装依赖 / 启动脚本 |
| `*_test.py` | 各功能测试套件（batch1~4 / smoke / integration 等） |

## 安装

### 安装包（推荐）

下载 Release 中的 `FFmpegGUI-Setup-*-Windows-x64.exe`，一路下一步。

**依赖**：需安装 [FFmpeg](https://ffmpeg.org/download.html) 并加入 PATH（程序调用系统 ffmpeg，不捆绑；设置页内置「下载 FFmpeg」按钮）。

### 从源码运行

需要 Python 3.11 + [uv](https://docs.astral.sh/uv/)，ffmpeg 在 PATH：

```bash
uv venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python.exe main.py
```

## 打包

```bash
# 独立 exe（Nuitka + MSVC）
.venv/Scripts/python.exe -m nuitka --standalone --enable-plugin=pyside6 \
    --windows-icon-from-ico=app.ico --windows-console-mode=disable \
    --msvc=latest --include-package-data=qfluentwidgets \
    --assume-yes-for-downloads --output-dir=dist -o ffmpegGUI main.py

# 安装包（Inno Setup）
"C:\Program Files\Inno Setup 7\ISCC.exe" installer.iss
```

## 测试

```bash
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe smoke_test.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe batch1_test.py
# ...（batch2~4 覆盖音频/合并/变速/元数据/字幕/去水印）
```

## 许可证

[GPL-3.0](LICENSE)
