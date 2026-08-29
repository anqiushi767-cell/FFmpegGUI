"""FFmpeg 转码核心：任务模型 + 后台转码线程（支持 转码/截取片段/抽帧封面）。"""
import os
import re
import uuid
import time
import tempfile
import subprocess
from functools import lru_cache
from dataclasses import dataclass, field, asdict

from PySide6.QtCore import QThread, Signal

# GUI 程序（pythonw 无控制台）下防止 ffmpeg/ffprobe 弹出黑窗
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 画质档位 → (x264 preset, CRF)
QUALITY_PRESETS = {
    "fast":     ("ultrafast", 28),
    "balanced": ("veryfast", 23),
    "high":     ("medium", 18),
}
# WebM(VP9) 的 CRF 范围 0-63，单独映射
VP9_CRF = {"fast": 40, "balanced": 34, "high": 30}

# 任务类型
KIND_CONVERT = "convert"   # 整段转码
KIND_TRIM = "trim"         # 截取片段
KIND_FRAME = "frame"       # 抽帧封面
KIND_AUDIO = "audio"       # 提取音频（独立于转码格式设置）
KIND_MUTE = "mute"         # 提取无声视频（去音轨，视频流拷贝）
KIND_NORM = "normalize"    # 音量归一化（响度标准化到 -16 LUFS）
KIND_GIF = "gif"           # 转 GIF 动图
KIND_MERGE = "merge"       # 合并多个视频
KIND_SPEED = "speed"       # 变速
KIND_SHOT = "shot"         # 定点截图
KIND_STREAM = "stream"     # 流媒体下载（m3u8 等）
KIND_META = "meta"         # 元数据编辑（标题/封面嵌入）
KIND_SUBTITLE = "subtitle" # 字幕烧录（srt/ass 烧进画面）
KIND_RECORD = "record"     # 屏幕录制（gdigrab，手动停止）
KIND_DELOGO = "delogo"     # 去水印（delogo 滤镜选区域）


@lru_cache(maxsize=1)
def nvenc_available():
    """检测 ffmpeg 是否带 h264_nvenc（NVIDIA 硬件编码）。"""
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        return "h264_nvenc" in p.stdout
    except Exception:
        return False


@lru_cache(maxsize=1)
def ddagrab_available():
    """检测 ffmpeg 是否支持 ddagrab 滤镜（Desktop Duplication，抓屏不闪烁）。
    注意：ddagrab 是 libavfilter 的 source filter，不是 device，要查 -filters。"""
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        return "ddagrab" in p.stdout
    except Exception:
        return False


@lru_cache(maxsize=1)
def list_audio_devices():
    """列出 dshow 音频输入设备（麦克风/立体声混音等），失败返回空列表。"""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-list_devices", "true",
             "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
            creationflags=CREATE_NO_WINDOW)
        devs = []
        for line in p.stderr.splitlines():
            if "(audio)" in line:
                m = re.search(r'"([^"]+)"', line)
                if m:
                    devs.append(m.group(1))
        return devs
    except Exception:
        return []


@dataclass
class Task:
    path: str
    out_dir: str
    encode_mode: str          # "h264" | "copy"
    out_format: str = "mp4"   # mp4 | mkv | webm | mp3（copy 模式恒 mp4）
    quality: str = "balanced" # fast | balanced | high
    kind: str = KIND_CONVERT  # convert | trim | frame | audio | normalize | gif | merge | speed | shot
    trim_start: float = 0.0   # 截取起（秒）
    trim_end: float = 0.0     # 截止（秒，0=到结尾）
    gif_fps: int = 12         # GIF 帧率
    gif_width: int = 480      # GIF 宽度（高自动等比）
    audio_format: str = "mp3" # 提取音频格式 mp3|flac|wav|aac
    merge_paths: list = field(default_factory=list)  # 合并任务的输入列表
    speed_rate: float = 1.0   # 变速倍速（0.5~2.0）
    shot_time: float = 0.0    # 定点截图时间（秒）
    hw_accel: bool = False    # 硬件加速（NVENC）
    record_draw_mouse: bool = True  # 录屏绘制鼠标光标（False=不抽搐但画面无鼠标）
    record_fps: int = 30      # 录屏帧率
    record_audio: str = ""    # 录屏音源（dshow 设备名，空=无声）
    stream_url: str = ""      # 流媒体下载 URL（m3u8 等）
    metadata_title: str = ""  # 元数据标题
    cover_path: str = ""      # 封面图片路径（嵌入 mp4）
    subtitle_path: str = ""   # 字幕文件路径（烧录）
    delogo_region: str = ""   # 去水印区域 "x:y:w:h"（原始像素）
    name: str = ""
    size: int = 0
    duration: float = 0.0
    status: str = "pending"   # pending / running / done / error
    percent: int = 0
    speed: str = ""
    eta: str = ""             # 预计剩余时间（运行时字段）
    error: str = ""
    out_path: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __post_init__(self):
        if not self.name:
            self.name = os.path.basename(self.path)
        if os.path.isfile(self.path):
            self.size = os.path.getsize(self.path)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k) for k in (
            "path", "out_dir", "encode_mode", "out_format", "quality",
            "kind", "trim_start", "trim_end", "merge_paths", "speed_rate",
            "shot_time", "hw_accel", "record_draw_mouse", "record_fps",
            "record_audio", "stream_url", "audio_format",
            "metadata_title",
            "cover_path", "subtitle_path", "delogo_region",
            "name", "size", "duration", "status", "percent", "speed", "eta",
            "error", "out_path", "id")})


def fmt_size(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} B" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n} B"


def fmt_dur(sec):
    if not sec or sec <= 0:
        return "—"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def escape_subtitle_path(p):
    """Windows 路径转义给 ffmpeg subtitles 滤镜（反斜杠→正斜杠，冒号→\\:）。"""
    return p.replace("\\", "/").replace(":", "\\:")


def parse_time(text):
    """把 mm:ss / hh:mm:ss / 秒数 解析成秒，失败返回 -1。"""
    text = (text or "").strip()
    if not text:
        return -1
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if not all(p.strip().isdigit() for p in parts) or len(parts) > 3:
        return -1
    nums = [int(p) for p in parts]
    while len(nums) < 3:
        nums.insert(0, 0)
    h, m, s = nums
    return h * 3600 + m * 60 + s


def probe_duration(path):
    """用 ffprobe 探测视频时长（秒），失败返回 0。"""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=CREATE_NO_WINDOW,
        )
        return float(p.stdout.strip())
    except Exception:
        return 0.0


def ffmpeg_version():
    """解析当前 ffmpeg 版本号，失败返回 None。"""
    try:
        p = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=30, creationflags=CREATE_NO_WINDOW)
        m = re.search(r"ffmpeg version (\S+)", p.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


def latest_ffmpeg_version():
    """从 gyan.dev 获取最新 release 版本号，失败返回 None。"""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://www.gyan.dev/ffmpeg/builds/release-version",
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8").strip()
    except Exception:
        return None


def latest_app_version():
    """从 GitHub Releases API 获取最新版本号，失败返回 None。"""
    import urllib.request
    import json
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/anqiushi767-cell/FFmpegGUI"
            "/releases/latest",
            headers={"User-Agent": "FFmpegGUI"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get("tag_name", "").lstrip("vV")
    except Exception:
        return None


def version_tuple(v):
    """版本号字符串 → (major, minor, patch) 数字元组，用于比较。"""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", v or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def build_cmd(task, out_path):
    """按任务配置构建 ffmpeg 命令。"""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    # 屏幕录制：优先 ddagrab 滤镜（Desktop Duplication，GPU 抓屏不闪烁）
    if task.kind == KIND_RECORD:
        draw_mouse = "1" if task.record_draw_mouse else "0"
        fps = task.record_fps if task.record_fps > 0 else 30
        if ddagrab_available():
            cmd += ["-f", "lavfi", "-i",
                    f"ddagrab=framerate={fps}:draw_mouse={draw_mouse}"]
            # ddagrab 输出 d3d11 硬件帧(BGRA)，需 hwdownload 到 CPU 才能编码
            cmd += ["-vf", "hwdownload,format=bgra"]
        else:
            cmd += ["-f", "gdigrab", "-framerate", str(fps),
                    "-draw_mouse", draw_mouse, "-i", "desktop"]
        # 音频输入（dshow 麦克风/立体声混音，空=无声）
        if task.record_audio:
            cmd += ["-f", "dshow", "-i", f"audio={task.record_audio}"]
        if task.hw_accel and nvenc_available():
            # 显卡编码，大幅降低 CPU 占用（缓解抓屏卡顿/鼠标抽搐）
            cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-pix_fmt", "yuv420p"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                    "yuv420p"]
        if task.record_audio:
            # 双输入需显式 map：0=画面(ddagra/gdi) 1=音频(dshow)
            cmd += ["-c:a", "aac", "-b:a", "192k",
                    "-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-g", "30", "-movflags", "+frag_keyframe+empty_moov"]
        cmd += ["-progress", "pipe:1", "-nostats", out_path]
        return cmd

    # 字幕烧录：subtitles 滤镜 + 重编码（字幕烧进画面必须重编码）
    if task.kind == KIND_SUBTITLE:
        escaped = escape_subtitle_path(task.subtitle_path)
        cmd += ["-i", task.path, "-vf", f"subtitles='{escaped}'"]
        preset, crf = QUALITY_PRESETS.get(task.quality,
                                          QUALITY_PRESETS["balanced"])
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
        cmd += ["-progress", "pipe:1", "-nostats", out_path]
        return cmd

    # 去水印：delogo 滤镜（区域 x:y:w:h）+ 重编码
    if task.kind == KIND_DELOGO:
        cmd += ["-i", task.path, "-vf", f"delogo={task.delogo_region}"]
        preset, crf = QUALITY_PRESETS.get(task.quality,
                                          QUALITY_PRESETS["balanced"])
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
        cmd += ["-progress", "pipe:1", "-nostats", out_path]
        return cmd

    # 流媒体下载（m3u8 等）：copy 合并到本地 mp4
    if task.kind == KIND_STREAM:
        cmd += ["-i", task.stream_url, "-c", "copy",
                "-progress", "pipe:1", "-nostats", out_path]
        return cmd

    # 元数据编辑：标题 + 封面嵌入（copy 视频流，封面作 attached_pic）
    if task.kind == KIND_META:
        cmd += ["-i", task.path]
        has_cover = bool(task.cover_path and os.path.isfile(task.cover_path))
        if has_cover:
            cmd += ["-i", task.cover_path]
        cmd += ["-map", "0"]
        if has_cover:
            cmd += ["-map", "1", "-c:v:1", "mjpeg",
                    "-disposition:v:1", "attached_pic"]
        if task.metadata_title:
            cmd += ["-metadata", f"title={task.metadata_title}"]
        cmd += ["-c", "copy"]
        cmd += ["-progress", "pipe:1", "-nostats", out_path]
        return cmd

    # 合并视频：concat demuxer 读列表文件（同编码源可流拷贝，否则自动重编码）
    if task.kind == KIND_MERGE:
        lst = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                          delete=False, encoding="utf-8")
        for p in task.merge_paths or [task.path]:
            lst.write(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")
        lst.close()
        cmd += ["-f", "concat", "-safe", "0", "-i", lst.name]
        if task.encode_mode == "copy":
            cmd += ["-c", "copy"]
        else:
            preset, crf = QUALITY_PRESETS.get(task.quality,
                                              QUALITY_PRESETS["balanced"])
            cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                    "-c:a", "aac", "-b:a", "192k"]
            if task.out_format == "mp4":
                cmd += ["-movflags", "+faststart"]
        cmd += ["-progress", "pipe:1", "-nostats", out_path]
        return cmd

    # 定点截图：指定时间抽一帧 PNG
    if task.kind == KIND_SHOT:
        cmd += ["-ss", f"{task.shot_time:.3f}", "-i", task.path,
                "-frames:v", "1", "-q:v", "2", out_path]
        return cmd

    # 截取片段：-ss 放输入前（快速定位），-t 算时长
    if task.kind == KIND_TRIM:
        cmd += ["-ss", f"{task.trim_start:.3f}"]
        end = task.trim_end if task.trim_end > task.trim_start else 0
        if end:
            cmd += ["-t", f"{end - task.trim_start:.3f}"]
    cmd += ["-i", task.path]

    if task.kind == KIND_FRAME:
        # 抽帧封面：取视频 25% 处的一帧 PNG（避开黑屏开头）
        at = task.duration * 0.25 if task.duration > 0 else 0
        if at > 0:
            cmd += ["-ss", f"{at:.3f}"]
        cmd += ["-frames:v", "1", "-q:v", "2", out_path]
        return cmd

    if task.kind == KIND_GIF:
        # GIF 两段式调色板（质量最好）：全局调色板 + 缩放 + 帧率
        fps = max(5, min(24, task.gif_fps))
        w = max(120, task.gif_width)
        vf = (f"fps={fps},scale={w}:-1:flags=lanczos,"
              f"split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
              f"[s1][p]paletteuse=dither=bayer:bayer_scale=4")
        # GIF 复用 trim_start/trim_end 选段：自己补 -ss 起点和 -t 时长
        if task.trim_start > 0:
            cmd += ["-ss", f"{task.trim_start:.3f}"]
        end = task.trim_end if task.trim_end > task.trim_start else 0
        if end:
            cmd += ["-t", f"{end - task.trim_start:.3f}"]
        cmd += ["-vf", vf, "-loop", "0", out_path]
        return cmd

    if task.kind == KIND_MUTE:
        # 提取无声视频：去音轨，视频流拷贝（快、无损）
        cmd += ["-an", "-c:v", "copy"]
    elif task.kind == KIND_AUDIO:
        # 提取音频，格式可选 mp3/flac/wav/aac
        if task.audio_format == "flac":
            cmd += ["-vn", "-c:a", "flac"]
        elif task.audio_format == "wav":
            cmd += ["-vn", "-c:a", "pcm_s16le"]
        elif task.audio_format == "aac":
            cmd += ["-vn", "-c:a", "aac", "-b:a", "192k"]
        else:  # mp3 通用有损
            cmd += ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    elif task.kind == KIND_NORM:
        # 响度归一化：EBU R128 → -16 LUFS（流媒体标准响度）
        preset, crf = QUALITY_PRESETS.get(task.quality,
                                          QUALITY_PRESETS["balanced"])
        ext = os.path.splitext(out_path)[1].lower()
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-c:a", "aac", "-b:a", "192k"]
        if ext == ".mp4":
            cmd += ["-movflags", "+faststart"]
    elif task.encode_mode == "copy":
        cmd += ["-c:v", "copy", "-c:a", "copy"]
    elif task.out_format == "mp3":
        cmd += ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    elif task.out_format == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-crf", str(VP9_CRF.get(task.quality, 34)),
                "-b:v", "0", "-c:a", "libopus"]
    else:  # mp4 / mkv → x264（可用 NVENC 硬件加速）
        preset, crf = QUALITY_PRESETS.get(task.quality,
                                          QUALITY_PRESETS["balanced"])
        if task.hw_accel and nvenc_available():
            cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(crf + 2),
                    "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                    "-c:a", "aac", "-b:a", "192k"]
        if task.out_format == "mp4":
            cmd += ["-movflags", "+faststart"]

    # 变速：视频 PTS 缩放 + 音频 atempo（0.5~2.0）
    if task.kind == KIND_SPEED:
        rate = task.speed_rate if task.speed_rate > 0 else 1.0
        if rate != 1.0:
            cmd += ["-vf", f"setpts=PTS/{rate}", "-af", f"atempo={rate}"]

    cmd += ["-progress", "pipe:1", "-nostats", out_path]
    return cmd


class ConvertWorker(QThread):
    """后台转码线程，逐行解析 ffmpeg -progress 输出并发送信号。"""
    progress = Signal(str, int)      # task_id, percent
    speed = Signal(str, str)         # task_id, speed text
    status = Signal(str, str, str)   # task_id, status, extra

    def __init__(self, task, parent=None, all_tasks=None):
        super().__init__(parent)
        self.task = task
        self.all_tasks = all_tasks or {}  # TaskPage 的任务表，供同名输出去重
        self._proc = None
        self._cancel = False
        self._cur_us = 0  # 当前已转时长（微秒），供 ETA 计算

    def cancel(self):
        """终止当前 ffmpeg 进程（退出程序时用）。"""
        self._cancel = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def stop(self):
        """停止录制：向 ffmpeg 写 'q' 优雅退出（fragmented mp4 兜底）。"""
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write("q")
                self._proc.stdin.flush()
            except Exception:
                self.cancel()
        else:
            self.cancel()

    def run(self):
        task = self.task
        if task.duration <= 0:
            if task.kind == KIND_MERGE:
                task.duration = sum(probe_duration(p)
                                    for p in (task.merge_paths or [task.path]))
            elif task.kind == KIND_STREAM:
                pass  # 网络流时长未知，不探测（进度条用不确定模式）
            elif task.kind == KIND_RECORD:
                pass  # 录制时长未知，不探测
            else:
                task.duration = probe_duration(task.path)

        base = os.path.splitext(task.name)[0]
        if task.kind == KIND_FRAME:
            out_ext = ".png"
            out_path = os.path.join(task.out_dir, base + "_cover.png")
        elif task.kind == KIND_GIF:
            out_path = os.path.join(task.out_dir, base + ".gif")
        elif task.kind == KIND_AUDIO:
            ext = ".m4a" if task.audio_format == "aac" else "." + task.audio_format
            out_path = os.path.join(task.out_dir, base + ext)
        elif task.kind == KIND_MUTE:
            src_ext = os.path.splitext(task.path)[1] or ".mp4"
            out_path = os.path.join(task.out_dir, base + "_无声" + src_ext)
        elif task.kind == KIND_NORM:
            out_ext = ".mp4"
            out_path = os.path.join(task.out_dir, base + "_响度归一.mp4")
        elif task.kind == KIND_MERGE:
            out_ext = ".mp4" if task.encode_mode == "copy" else "." + task.out_format
            out_path = os.path.join(task.out_dir, base + "_合并" + out_ext)
        elif task.kind == KIND_SPEED:
            out_ext = ".mp4" if task.encode_mode == "copy" else "." + task.out_format
            out_path = os.path.join(task.out_dir,
                                    base + f"_变速{task.speed_rate}x" + out_ext)
        elif task.kind == KIND_SHOT:
            out_path = os.path.join(task.out_dir,
                                    base + f"_截图{int(task.shot_time)}s.png")
        elif task.kind == KIND_STREAM:
            out_path = os.path.join(task.out_dir, base + ".mp4")
        elif task.kind == KIND_META:
            out_path = os.path.join(task.out_dir, base + "_编辑.mp4")
        elif task.kind == KIND_SUBTITLE:
            out_path = os.path.join(task.out_dir, base + "_字幕.mp4")
        elif task.kind == KIND_DELOGO:
            out_path = os.path.join(task.out_dir, base + "_去水印.mp4")
        elif task.kind == KIND_RECORD:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(task.out_dir, f"录屏_{ts}.mp4")
        elif task.kind == KIND_TRIM:
            out_ext = ".mp4" if task.encode_mode == "copy" else "." + task.out_format
            out_path = os.path.join(task.out_dir,
                                    base + f"_片段{int(task.trim_start)}-{int(task.trim_end or 0)}.mp4")
            out_path = os.path.splitext(out_path)[0] + out_ext
        else:
            out_ext = ".mp4" if task.encode_mode == "copy" else "." + task.out_format
            out_path = os.path.join(task.out_dir, base + out_ext)
        if os.path.abspath(out_path).lower() == os.path.abspath(task.path).lower():
            out_path = os.path.join(task.out_dir, base + "_converted" + out_ext)
        # 同名输出去重：已存在（或正被其他任务写入）时追加序号 _2/_3…
        stem, ext = os.path.splitext(out_path)
        n = 2
        used = {os.path.abspath(t.out_path).lower()
                for tid, t in self.all_tasks.items()
                if tid != task.id and t.out_path}
        while os.path.exists(out_path) or os.path.abspath(out_path).lower() in used:
            out_path = f"{stem}_{n}{ext}"
            n += 1
        task.out_path = out_path

        cmd = build_cmd(task, out_path)

        self.status.emit(task.id, "running", "")
        task.status = "running"
        task.speed = ""

        # 抽帧很快，无 -progress 输出可解析时直接等待
        err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
        popen_kw = dict(stdout=subprocess.PIPE, stderr=err_file,
                        text=True, encoding="utf-8", errors="replace",
                        creationflags=CREATE_NO_WINDOW)
        if task.kind == KIND_RECORD:
            popen_kw["stdin"] = subprocess.PIPE  # 停止时写 'q' 优雅退出
        proc = subprocess.Popen(cmd, **popen_kw)
        self._proc = proc

        # 进度基准：截取按片段时长算百分比，变速按变速后时长，其他按全片
        span = task.duration
        if task.kind == KIND_TRIM:
            end = task.trim_end if task.trim_end > task.trim_start else 0
            if end:
                span = max(0.1, end - task.trim_start)
        elif task.kind == KIND_SPEED and task.speed_rate > 0:
            span = max(0.1, task.duration / task.speed_rate)

        for line in proc.stdout:
            if self._cancel:
                break
            line = line.strip()
            if line.startswith("out_time_us="):
                val = line.split("=", 1)[1].strip()
                if val == "N/A":
                    continue  # 录制初始阶段时间基准未定，ffmpeg 输出 N/A
                try:
                    us = int(val)
                except ValueError:
                    continue
                self._cur_us = us
                base_sec = 0  # -ss 在 -i 前：ffmpeg 输出时间戳从 0 重计
                if span > 0:
                    pct = min(100, int(max(0, us / 1e6 - base_sec) / span * 100))
                    # 只发变化过的进度（1% 粒度），避免无意义刷新
                    if pct != task.percent:
                        task.percent = pct
                        self.progress.emit(task.id, pct)
            elif line.startswith("speed="):
                task.speed = line.split("=", 1)[1]
                # 预计剩余时间：剩余时长 / 处理速度倍数
                try:
                    rate = float(task.speed.replace("x", "").strip())
                except ValueError:
                    rate = 0.0
                if rate > 0 and span > 0:
                    remain = max(0.0, span - self._cur_us / 1e6)
                    task.eta = fmt_dur(remain / rate + 1)
                else:
                    task.eta = ""
                self.speed.emit(task.id, task.speed)
        proc.wait()
        err_file.seek(0)
        err_tail = err_file.read()[-800:]
        err_file.close()

        if self._cancel:
            # 用户取消（退出程序）：恢复为 pending，下次可重试，不报错
            task.status = "pending"
            task.percent = 0
            task.speed = ""
            self.status.emit(task.id, "pending", "")
            return

        if task.kind == KIND_RECORD:
            # fragmented mp4 中断也能播放，只要非空即算成功
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                task.percent = 100
                task.status = "done"
                task.size = os.path.getsize(out_path)  # 录屏结果大小（无源文件）
                self.status.emit(task.id, "done", out_path)
            else:
                task.status = "error"
                if task.record_audio:
                    task.error = ("录制失败：音频设备不可用（可能被安全软件拦截，"
                                  "或设备被占用）——可去掉音源后无声录制")
                else:
                    task.error = "录制失败（无输出）"
                self.status.emit(task.id, "error", task.error)
            return

        if proc.returncode == 0 and os.path.exists(out_path):
            task.percent = 100
            task.status = "done"
            self.progress.emit(task.id, 100)
            self.status.emit(task.id, "done", out_path)
        else:
            task.status = "error"
            task.error = err_tail or f"ffmpeg 退出码 {proc.returncode}"
            self.status.emit(task.id, "error", task.error)
