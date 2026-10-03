"""FFmpeg 转码核心：任务模型 + 操作描述表 + 后台转码线程。"""
import os
import re
import sys
import uuid
import time
import tempfile
import subprocess
from functools import lru_cache
from collections.abc import Callable
from dataclasses import dataclass, field, asdict, fields, MISSING

from PySide6.QtCore import QThread, Signal

# GUI 程序（pythonw 无控制台）下防止 ffmpeg/ffprobe 弹出黑窗
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------- FFmpeg 可执行文件定位 ----------
# 程序调用系统 ffmpeg（不捆绑）。PATH 里找不到时，再探测常见安装位置并补进 PATH，
# 避免"明明装了 FFmpeg，程序却说未检测到 / 一开转就失败"。
_ffmpeg_path_checked = False


def _ffmpeg_candidate_dirs():
    """常见 FFmpeg 安装目录（按优先级）。"""
    import glob
    local = os.environ.get("LOCALAPPDATA") or ""
    home = os.path.expanduser("~")
    dirs = [
        os.path.join(local, "Microsoft", "WinGet", "Links"),   # winget 便携包软链
        os.path.join(home, "scoop", "shims"),                  # scoop
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",                      # choco 免安装 shim
        os.path.join(home, "ffmpeg", "bin"),
        os.path.join(local, "Programs", "ffmpeg", "bin"),
    ]
    # 打包版：exe 同级目录下放 ffmpeg\bin 也能被找到
    dirs.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                             "ffmpeg", "bin"))
    # winget 包目录（Gyan.FFmpeg 等）按通配展开一层
    pkg_root = os.path.join(local, "Microsoft", "WinGet", "Packages")
    for pat in ("Gyan.FFmpeg*", "*FFmpeg*"):
        dirs += glob.glob(os.path.join(pkg_root, pat, "*", "bin"))
    return dirs


def ensure_ffmpeg_path(force=False):
    """确保 ffmpeg 可被调用：PATH 里没有就探测常见目录并补进 PATH。

    默认只探测一次；force=True 允许再探测（用户刚装好 FFmpeg 的场景）。
    """
    global _ffmpeg_path_checked
    if _ffmpeg_path_checked and not force:
        return
    _ffmpeg_path_checked = True
    import shutil
    if shutil.which("ffmpeg"):
        return
    for d in _ffmpeg_candidate_dirs():
        try:
            if os.path.isfile(os.path.join(d, "ffmpeg.exe")):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                return
        except OSError:
            continue


# 导入即探测一次：让所有 subprocess 调用（ffmpeg/ffprobe）都能直接按名字找到
ensure_ffmpeg_path()


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
    """检测本机能否真正用 NVENC 编码：真编一帧 320x240 测试（结果缓存）。

    只查 `ffmpeg -encoders` 不够：gyan.dev 全功能构建在任何机器上都列出
    h264_nvenc，没有 N 卡/驱动时"检测通过、一开转就失败"（Cannot load
    nvcuda.dll）——设置页会误导用户打开硬件加速，然后所有任务全挂。

    探测命令刻意不带 -preset：老版本 ffmpeg 只认 hq/llhq 那套预设名，
    带上 p5 会把"其实能用"的机器误判成不能用。
    """
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=black:s=320x240",
             "-frames:v", "1", "-pix_fmt", "yuv420p",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, creationflags=CREATE_NO_WINDOW)
        if p.returncode == 0:
            return True
        err = (p.stderr or "").lower()
        # 明确是"编码器没有 / 显卡或驱动不可用" → 判定不支持
        for key in ("unknown encoder", "nvcuda", "nvencodeapi",
                    "no capable device", "cannot load", "no nvenc"):
            if key in err:
                return False
        # 其它原因（例如精简版 ffmpeg 没编 lavfi/color 滤镜）不能证明
        # NVENC 不可用，退回"编码器是否存在"的粗判，别把能用的机器判死
        return _nvenc_encoder_present()
    except Exception:
        return False


@lru_cache(maxsize=1)
def _nvenc_encoder_present():
    """`ffmpeg -encoders` 里是否带 h264_nvenc（粗判，不能证明真能跑）。"""
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

    # 会写进 tasks.json 的字段，也是恢复时接受的键白名单
    PERSIST_FIELDS = (
        "path", "out_dir", "encode_mode", "out_format", "quality", "kind",
        "trim_start", "trim_end", "gif_fps", "gif_width", "audio_format",
        "merge_paths", "speed_rate", "shot_time", "hw_accel",
        "record_draw_mouse", "record_fps", "record_audio", "stream_url",
        "metadata_title", "cover_path", "subtitle_path", "delogo_region",
        "name", "size", "duration", "status", "percent", "speed", "eta",
        "error", "out_path", "id",
    )

    @classmethod
    def from_dict(cls, d):
        """从 tasks.json 的字典恢复任务（缺字段/None 一律退回字段默认值）。

        老版本写下的 tasks.json 会缺新版本才加的字段。原来直接 d.get(k) 会把
        缺失字段变成 None：轻则拼出 `delogo=None` 的非法命令、gif 参数被重置，
        重则 trim_start=None 在算数时直接抛异常——而 load_tasks 没有兜底，
        会在主窗口构造时崩掉、程序起不来。
        """
        kw = {}
        for f in fields(cls):
            if f.name not in cls.PERSIST_FIELDS:
                continue
            val = d.get(f.name)
            if val is None:
                if f.default_factory is not MISSING:
                    val = f.default_factory()
                elif f.default is not MISSING:
                    val = f.default
                else:
                    continue  # 无默认值的必填字段，交给调用方兜底
            kw[f.name] = val
        return cls(**kw)


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


_ffmpeg_version_cache = None  # 成功才缓存（失败不缓存，下次重试）


def ffmpeg_version():
    """解析当前 ffmpeg 版本号，失败返回 None。成功结果缓存避免重复 subprocess。"""
    global _ffmpeg_version_cache
    if _ffmpeg_version_cache:
        return _ffmpeg_version_cache
    import shutil
    if not shutil.which("ffmpeg"):
        ensure_ffmpeg_path(force=True)  # 用户可能刚装好 FFmpeg，允许再探测一次
    if not shutil.which("ffmpeg"):
        return None
    try:
        p = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=30, creationflags=CREATE_NO_WINDOW)
        m = re.search(r"ffmpeg version (\S+)", p.stdout)
        v = m.group(1) if m else None
        if v:
            _ffmpeg_version_cache = v
        return v
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
    """从 GitHub raw 的 versions.json 获取最新版本（快、无 API 限流），失败返回 None。"""
    import urllib.request
    import json
    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/anqiushi767-cell/FFmpegGUI"
            "/master/versions.json",
            headers={"User-Agent": "FFmpegGUI"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("version", "").lstrip("vV")
    except Exception:
        return None


def version_tuple(v):
    """版本号字符串 → (major, minor, patch) 数字元组，用于比较。"""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", v or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def video_codec_args(task, preset, crf):
    """视频编码参数：硬件加速开启且 NVENC 可用时走显卡，否则 libx264。

    字幕烧录/去水印这类软件滤镜同样适用：滤镜在 CPU 上跑，
    编码器会自动上传帧，不需要额外 hwupload。
    """
    if task.hw_accel and nvenc_available():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(crf + 2)]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]


# ---------- 操作描述表 ----------
# 每种操作一条自描述记录：输出命名 + 命令构建 + 时长探测 + 进度基准。
# 原来这四件事散在 build_cmd / ConvertWorker._run 的多个 if 链里：新增一种
# 操作要改 5~7 个地方，还出现过"部分分支没给 out_ext 赋值"的潜在 NameError。
# 现在新增操作 = 加一个 KIND_ 常量 + 这里注册一项（build/out_name 是纯函数，
# 不依赖 ffmpeg 就能单测，见 build_cmd_test.py）。
#
# build(task, out_path) 只产出参数部分（可执行名与 -progress 尾巴由
# build_cmd 统一拼）；out_name(task) 只产出文件名（目录与去重由
# resolve_out_path 处理）。

@dataclass(frozen=True)
class Operation:
    out_name: Callable[[Task], str]               # 输出文件名
    build: Callable[[Task, str], list]            # ffmpeg 参数
    probe: Callable[[Task], float] | None = None  # 时长探测；None=ffprobe 源文件
    span: Callable[[Task], float] | None = None   # 进度基准；None=task.duration
    progress: bool = True   # 是否要 -progress 输出（截帧/GIF/截图很快，不需要）
    record_like: bool = False  # 录制类：需要 stdin 写 q 停止，允许半截输出


def _quality(task):
    """画质档位 → (x264 preset, CRF)，未知档位按平衡档。"""
    return QUALITY_PRESETS.get(task.quality, QUALITY_PRESETS["balanced"])


def _stem(task):
    return os.path.splitext(task.name)[0]


def _out_ext(task):
    """copy 模式恒 mp4，否则按输出格式。"""
    return ".mp4" if task.encode_mode == "copy" else "." + task.out_format


def _codec_args(task):
    """共享的编解码选择（整段转码 / 截取片段 / 变速的尾部）。"""
    if task.encode_mode == "copy":
        return ["-c:v", "copy", "-c:a", "copy"]
    if task.out_format == "mp3":
        return ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    if task.out_format == "webm":
        return ["-c:v", "libvpx-vp9",
                "-crf", str(VP9_CRF.get(task.quality, 34)),
                "-b:v", "0", "-c:a", "libopus"]
    preset, crf = _quality(task)
    args = video_codec_args(task, preset, crf) + ["-c:a", "aac", "-b:a", "192k"]
    if task.out_format == "mp4":
        args += ["-movflags", "+faststart"]
    return args


# ---- 命令构建 ----

def _build_convert(task, out_path):
    return ["-i", task.path] + _codec_args(task)


def _build_trim(task, out_path):
    """截取片段：-ss 放输入前（快速定位），-t 算时长。"""
    args = ["-ss", f"{task.trim_start:.3f}"]
    end = task.trim_end if task.trim_end > task.trim_start else 0
    if end:
        args += ["-t", f"{end - task.trim_start:.3f}"]
    args += ["-i", task.path]
    return args + _codec_args(task)


def _build_frame(task, out_path):
    """抽帧封面：取视频 25% 处的一帧 PNG（避开黑屏开头）。"""
    args = ["-i", task.path]
    at = task.duration * 0.25 if task.duration > 0 else 0
    if at > 0:
        args += ["-ss", f"{at:.3f}"]
    return args + ["-frames:v", "1", "-q:v", "2"]


def _build_audio(task, out_path):
    """提取音频，格式可选 mp3/flac/wav/aac。"""
    fmt = task.audio_format
    if fmt == "flac":
        audio = ["-vn", "-c:a", "flac"]
    elif fmt == "wav":
        audio = ["-vn", "-c:a", "pcm_s16le"]
    elif fmt == "aac":
        audio = ["-vn", "-c:a", "aac", "-b:a", "192k"]
    else:  # mp3 通用有损
        audio = ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    return ["-i", task.path] + audio


def _build_mute(task, out_path):
    """提取无声视频：去音轨，视频流拷贝（快、无损）。"""
    return ["-i", task.path, "-an", "-c:v", "copy"]


def _build_norm(task, out_path):
    """响度归一化：EBU R128 → -16 LUFS（流媒体标准响度）。"""
    preset, crf = _quality(task)
    args = ["-i", task.path, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    args += video_codec_args(task, preset, crf) + ["-c:a", "aac", "-b:a", "192k"]
    if os.path.splitext(out_path)[1].lower() == ".mp4":
        args += ["-movflags", "+faststart"]
    return args


def _build_gif(task, out_path):
    """GIF 两段式调色板（质量最好）+ 复用 trim 选段。"""
    fps = max(5, min(24, task.gif_fps))
    w = max(120, task.gif_width)
    vf = (f"fps={fps},scale={w}:-1:flags=lanczos,"
          f"split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
          f"[s1][p]paletteuse=dither=bayer:bayer_scale=4")
    args = ["-i", task.path]
    if task.trim_start > 0:
        args += ["-ss", f"{task.trim_start:.3f}"]
    end = task.trim_end if task.trim_end > task.trim_start else 0
    if end:
        args += ["-t", f"{end - task.trim_start:.3f}"]
    return args + ["-vf", vf, "-loop", "0"]


def _build_merge(task, out_path):
    """合并视频：concat demuxer 读列表文件（同编码源可流拷贝）。"""
    lst = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                      delete=False, encoding="utf-8")
    for p in task.merge_paths or [task.path]:
        lst.write(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")
    lst.close()
    args = ["-f", "concat", "-safe", "0", "-i", lst.name]
    if task.encode_mode == "copy":
        return args + ["-c", "copy"]
    preset, crf = _quality(task)
    args += video_codec_args(task, preset, crf) + ["-c:a", "aac", "-b:a", "192k"]
    if task.out_format == "mp4":
        args += ["-movflags", "+faststart"]
    return args


def _build_speed(task, out_path):
    """变速：视频 PTS 缩放 + 音频 atempo（0.5~2.0）。"""
    rate = task.speed_rate if task.speed_rate > 0 else 1.0
    args = ["-i", task.path] + _codec_args(task)
    if rate != 1.0:
        if task.out_format != "mp3":
            # MP3（仅提取音频）输出没有视频流，挂 setpts 只会被 ffmpeg
            # 忽略（不同版本还可能报错）；只做音频 atempo，产出变速后的 mp3
            args += ["-vf", f"setpts=PTS/{rate}"]
        args += ["-af", f"atempo={rate}"]
    return args


def _build_shot(task, out_path):
    """定点截图：指定时间抽一帧 PNG。"""
    return ["-ss", f"{task.shot_time:.3f}", "-i", task.path,
            "-frames:v", "1", "-q:v", "2"]


def _build_stream(task, out_path):
    """流媒体下载（m3u8 等）：copy 合并到本地 mp4。"""
    return ["-i", task.stream_url, "-c", "copy"]


def _build_meta(task, out_path):
    """元数据编辑：标题 + 封面嵌入（copy 视频流，封面作 attached_pic）。"""
    args = ["-i", task.path]
    has_cover = bool(task.cover_path and os.path.isfile(task.cover_path))
    if has_cover:
        args += ["-i", task.cover_path]
    args += ["-map", "0"]
    if has_cover:
        args += ["-map", "1", "-c:v:1", "mjpeg",
                 "-disposition:v:1", "attached_pic"]
    if task.metadata_title:
        args += ["-metadata", f"title={task.metadata_title}"]
    return args + ["-c", "copy"]


def _build_subtitle(task, out_path):
    """字幕烧录：subtitles 滤镜 + 重编码（字幕烧进画面必须重编码）。"""
    escaped = escape_subtitle_path(task.subtitle_path)
    preset, crf = _quality(task)
    return (["-i", task.path, "-vf", f"subtitles='{escaped}'"]
            + video_codec_args(task, preset, crf)
            + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"])


def _build_delogo(task, out_path):
    """去水印：delogo 滤镜（区域 x:y:w:h）+ 重编码。"""
    preset, crf = _quality(task)
    return (["-i", task.path, "-vf", f"delogo={task.delogo_region}"]
            + video_codec_args(task, preset, crf)
            + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"])


def _build_record(task, out_path):
    """屏幕录制：优先 ddagrab 滤镜（Desktop Duplication，GPU 抓屏不闪烁）。"""
    draw_mouse = "1" if task.record_draw_mouse else "0"
    fps = task.record_fps if task.record_fps > 0 else 30
    if ddagrab_available():
        args = ["-f", "lavfi", "-i",
                f"ddagrab=framerate={fps}:draw_mouse={draw_mouse}"]
        # ddagrab 输出 d3d11 硬件帧(BGRA)，需 hwdownload 到 CPU 才能编码
        args += ["-vf", "hwdownload,format=bgra"]
    else:
        args = ["-f", "gdigrab", "-framerate", str(fps),
                "-draw_mouse", draw_mouse, "-i", "desktop"]
    # 音频输入（dshow 麦克风/立体声混音，空=无声）
    if task.record_audio:
        args += ["-f", "dshow", "-i", f"audio={task.record_audio}"]
    if task.hw_accel and nvenc_available():
        # 显卡编码，大幅降低 CPU 占用（缓解抓屏卡顿/鼠标抽搐）
        args += ["-c:v", "h264_nvenc", "-preset", "p5", "-pix_fmt", "yuv420p"]
    else:
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                 "yuv420p"]
    if task.record_audio:
        # 双输入需显式 map：0=画面(ddagra/gdi) 1=音频(dshow)
        args += ["-c:a", "aac", "-b:a", "192k",
                 "-map", "0:v:0", "-map", "1:a:0"]
    return args + ["-g", "30", "-movflags", "+frag_keyframe+empty_moov"]


# ---- 输出命名 ----

def _out_convert(t):
    return _stem(t) + _out_ext(t)


def _out_trim(t):
    return (_stem(t)
            + f"_片段{int(t.trim_start)}-{int(t.trim_end or 0)}" + _out_ext(t))


def _out_frame(t):
    return _stem(t) + "_cover.png"


def _out_audio(t):
    ext = ".m4a" if t.audio_format == "aac" else "." + t.audio_format
    return _stem(t) + ext


def _out_mute(t):
    src_ext = os.path.splitext(t.path)[1] or ".mp4"
    return _stem(t) + "_无声" + src_ext


def _out_norm(t):
    return _stem(t) + "_响度归一.mp4"


def _out_gif(t):
    return _stem(t) + ".gif"


def _out_merge(t):
    return _stem(t) + "_合并" + _out_ext(t)


def _out_speed(t):
    return _stem(t) + f"_变速{t.speed_rate}x" + _out_ext(t)


def _out_shot(t):
    return _stem(t) + f"_截图{int(t.shot_time)}s.png"


def _out_stream(t):
    return _stem(t) + ".mp4"


def _out_meta(t):
    return _stem(t) + "_编辑.mp4"


def _out_subtitle(t):
    return _stem(t) + "_字幕.mp4"


def _out_delogo(t):
    return _stem(t) + "_去水印.mp4"


def _out_record(t):
    return f"录屏_{time.strftime('%Y%m%d_%H%M%S')}.mp4"


# ---- 时长探测 / 进度基准 ----

def _probe_merge(t):
    return sum(probe_duration(p) for p in (t.merge_paths or [t.path]))


def _probe_skip(t):
    return 0.0  # 网络流/录制时长未知，不探测（进度条用不确定模式）


def _span_trim(t):
    end = t.trim_end if t.trim_end > t.trim_start else 0
    return end - t.trim_start if end else 0


def _span_speed(t):
    return t.duration / t.speed_rate if t.speed_rate > 0 else 0


OPERATIONS = {
    KIND_CONVERT: Operation(_out_convert, _build_convert),
    KIND_TRIM: Operation(_out_trim, _build_trim, span=_span_trim),
    KIND_FRAME: Operation(_out_frame, _build_frame, progress=False),
    KIND_AUDIO: Operation(_out_audio, _build_audio),
    KIND_MUTE: Operation(_out_mute, _build_mute),
    KIND_NORM: Operation(_out_norm, _build_norm),
    KIND_GIF: Operation(_out_gif, _build_gif, progress=False),
    KIND_MERGE: Operation(_out_merge, _build_merge, probe=_probe_merge),
    KIND_SPEED: Operation(_out_speed, _build_speed, span=_span_speed),
    KIND_SHOT: Operation(_out_shot, _build_shot, progress=False),
    KIND_STREAM: Operation(_out_stream, _build_stream, probe=_probe_skip),
    KIND_META: Operation(_out_meta, _build_meta),
    KIND_SUBTITLE: Operation(_out_subtitle, _build_subtitle),
    KIND_RECORD: Operation(_out_record, _build_record, probe=_probe_skip,
                           record_like=True),
    KIND_DELOGO: Operation(_out_delogo, _build_delogo),
}


def operation(kind):
    """取 kind 对应的操作描述；未知 kind 按整段转码处理（兼容旧 tasks.json）。"""
    return OPERATIONS.get(kind, OPERATIONS[KIND_CONVERT])


def resolve_out_path(task, all_tasks=None):
    """输出路径：操作自带的命名 + 同源保护 + 同名去重（_2/_3…）。

    all_tasks 是 TaskPage 的任务表，用于避开正被其它任务写入的文件名。
    """
    out_path = os.path.join(task.out_dir, operation(task.kind).out_name(task))
    if os.path.abspath(out_path).lower() == os.path.abspath(task.path).lower():
        # 输出与源同名：加后缀防止自己覆盖自己（旧实现只在部分分支定义了
        # out_ext，其余分支走到这里是 NameError——统一从 out_path 现取）
        ext = os.path.splitext(out_path)[1]
        out_path = os.path.join(task.out_dir,
                                os.path.splitext(task.name)[0]
                                + "_converted" + ext)
    stem, ext = os.path.splitext(out_path)
    n = 2
    used = {os.path.abspath(t.out_path).lower()
            for tid, t in (all_tasks or {}).items()
            if tid != task.id and t.out_path}
    while os.path.exists(out_path) or os.path.abspath(out_path).lower() in used:
        out_path = f"{stem}_{n}{ext}"
        n += 1
    return out_path


def build_cmd(task, out_path):
    """按任务配置构建 ffmpeg 命令（参数来自操作描述表）。"""
    op = operation(task.kind)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    cmd += op.build(task, out_path)
    if op.progress:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += [out_path]
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
        """线程入口：任何未预期异常都必须转成 error 状态。

        否则任务会永远停在"转码中"（卡片不刷新、重试也没用）——例如
        ffmpeg 不在 PATH、临时文件建不出来、命令拼接出错等。
        """
        try:
            self._run()
        except Exception as e:
            task = self.task
            task.status = "error"
            task.error = f"任务异常：{type(e).__name__}: {e}"
            self.status.emit(task.id, "error", task.error)

    def _run(self):
        task = self.task
        op = operation(task.kind)
        if task.duration <= 0:
            task.duration = (op.probe(task) if op.probe
                             else probe_duration(task.path))

        out_path = resolve_out_path(task, self.all_tasks)
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
        if op.record_like:
            popen_kw["stdin"] = subprocess.PIPE  # 停止时写 'q' 优雅退出
        try:
            proc = subprocess.Popen(cmd, **popen_kw)
        except FileNotFoundError:
            # ffmpeg/ffprobe 不在 PATH：给出可操作的提示，别让它卡在"转码中"
            err_file.close()
            task.status = "error"
            task.error = ("未找到 FFmpeg：请先安装 FFmpeg 并加入 PATH"
                          "（「设置」页有「下载 FFmpeg」按钮），装完重启程序即可")
            self.status.emit(task.id, "error", task.error)
            return
        except OSError as e:
            err_file.close()
            task.status = "error"
            task.error = f"启动 FFmpeg 失败：{e}"
            self.status.emit(task.id, "error", task.error)
            return
        self._proc = proc
        if self._cancel:
            # cancel() 在 Popen 之前到达（探测时长/建输出路径期间 _proc 还是
            # None，terminate 打空）：这里补一刀，否则 ffmpeg 会跑到自然结束
            try:
                proc.terminate()
            except Exception:
                pass

        # 进度基准：截取按片段时长算百分比，变速按变速后时长，其他按全片
        span = task.duration
        if op.span:
            v = op.span(task)
            if v > 0:
                span = max(0.1, v)

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

        if op.record_like:
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
