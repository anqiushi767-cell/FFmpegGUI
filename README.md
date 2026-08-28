# FFmpeg 转码器（FFmpegGUI）

GD（Ghost Downloader）风格的批量视频转码 GUI。把视频拖进来，自动开始转码——支持 **20 种音视频操作**，全部基于 FFmpeg。

## ✨ 功能一览

**基础转码**
- 批量转码：MP4 / MKV / WebM，三档画质（fast / balanced / high）
- 无损封装（copy，秒转不重编码）
- 硬件加速（NVIDIA NVENC 显卡编码）
- 并发转码数可配置（1~8）

**剪辑与提取**
- 截取片段（双滑块选范围，重编码 / copy 两种模式）
- 抽帧封面、定点截图
- 提取音频（MP3 / FLAC / WAV / AAC 四种格式）
- 提取无声视频（去音轨无损拷贝）
- 音量归一化（EBU R128 → -16 LUFS）
- 转 GIF 动图（可选片段范围 + 帧率 + 宽度）

**合成与特效**
- 合并多个视频
- 变速（0.5x ~ 2.0x）
- 字幕烧录（srt / ass，中文路径安全）
- 去水印（拖拽框选区域）
- 编辑元数据（标题 + 封面图）

**网络与录屏**
- 下载 M3U8 / 流媒体
- 屏幕录制（Desktop Duplication API，不闪屏；可选系统声音 / 麦克风 / 鼠标光标 / 帧率 / NVENC）

**体验**
- 拖入文件夹自动递归收集视频，拖入即自动转码
- GD 同款任务卡片：实时进度 + 转码速度 + 预计剩余时间（ETA）
- 失败任务一键重试、同名输出去重（自动 `_2` 后缀）
- 系统托盘（圆角菜单：开始转码 / 屏幕录制 / 快速操作）
- 深浅主题 + 主题色自定义
- 开机自启、完成后关机（60 秒倒计时可取消）、完成后托盘通知
- 任务持久化（重启恢复）、FFmpeg 版本检查更新

## 📦 安装

### 从安装包安装（推荐）
下载 `FFmpegGUI-Setup-1.0.0-Windows-x64.exe`，一路下一步即可（自动创建开始菜单 + 桌面快捷方式）。

**依赖**：需安装 [FFmpeg](https://ffmpeg.org/download.html) 并加入 PATH（程序调用系统 ffmpeg，不捆绑）。

### 从源码运行

**依赖**：Python 3.11 + [uv](https://docs.astral.sh/uv/)，ffmpeg 在 PATH

```bash
uv venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python.exe main.py
```

或 Windows 下直接：
```bat
install.bat   # 首次：装依赖
run.bat       # 启动
```

## 🛠 打包（exe + 安装包）

```bash
# 1. Nuitka 编译独立 exe（需 MSVC/VS2022，首次编译约 10~30 分钟）
uv pip install --python .venv/Scripts/python.exe nuitka
.venv/Scripts/python.exe -m nuitka --standalone --enable-plugin=pyside6 \
    --windows-icon-from-ico=app.ico --windows-console-mode=disable \
    --msvc=latest --include-package-data=qfluentwidgets \
    --assume-yes-for-downloads --output-dir=dist -o ffmpegGUI main.py

# 2. Inno Setup 制作安装包（需安装 Inno Setup 7）
"C:\Program Files\Inno Setup 7\ISCC.exe" installer.iss
```

## 🧪 测试

```bash
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe smoke_test.py   # 冒烟
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe batch1_test.py  # 转码/截取/抽帧
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe batch2_test.py  # 音频/归一化/GIF/合并
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe batch3_test.py  # 变速/截图/流媒体
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe batch4_meta_test.py    # 元数据
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe batch4_subtitle_test.py # 字幕
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe batch4_delogo_test.py   # 去水印
```

## 🧩 技术栈

- [PySide6](https://doc.qt.io/qtforpython/)（Qt for Python）
- [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PySide6-Fluent-Widgets)（qfluentwidgets，GD 同款 Fluent UI 库）
- [FFmpeg](https://ffmpeg.org/)（转码引擎，ddagrab 滤镜用于屏幕录制）

## 📄 许可证

[GPL-3.0](LICENSE)
