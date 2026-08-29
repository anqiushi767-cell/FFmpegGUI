## FFmpegGUI v1.0.0

GD（Ghost Downloader）风格批量视频转码 GUI，20 种音视频操作，全部基于 FFmpeg。

### ✨ 功能亮点

- **批量转码**：MP4 / MKV / WebM，三档画质，NVIDIA NVENC 硬件加速，并发可配置（1~8）
- **剪辑提取**：截取片段 / 抽帧封面 / 定点截图 / 提取音频（MP3/FLAC/WAV/AAC）/ 提取无声视频 / 音量归一化
- **合成特效**：GIF 动图 / 合并视频 / 变速 / 字幕烧录 / 去水印（框选区域）/ 元数据编辑
- **录屏与网络**：屏幕录制（Desktop Duplication 不闪屏，可选系统声音/麦克风）/ M3U8 流媒体下载
- **GD 同款体验**：拖入即转码（支持文件夹递归）、任务卡片实时进度 + 速度 + ETA、失败一键重试、同名输出去重、系统托盘圆角菜单、深浅主题、任务持久化

### 📦 下载

| 文件 | 说明 |
|---|---|
| **FFmpegGUI-Setup-1.0.0-Windows-x64.exe** | 安装包（推荐）：自动创建开始菜单 + 桌面快捷方式，含卸载程序 |
| **FFmpegGUI-Portable-Windows-x64.zip** | 免安装版：解压即用，绿色便携 |

> **注意**：程序调用系统 FFmpeg（不捆绑），使用前需安装 [FFmpeg](https://ffmpeg.org/download.html) 并加入 PATH。

### 🧩 技术栈

PySide6 · PySide6-Fluent-Widgets（qfluentwidgets）· FFmpeg · Nuitka 打包 · Inno Setup 安装器

### 📄 许可证

[GPL-3.0](https://github.com/anqiushi767-cell/FFmpegGUI/blob/master/LICENSE)
