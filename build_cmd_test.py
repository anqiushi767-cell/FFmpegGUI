"""命令构建单测：cover 16 种操作的 ffmpeg 命令与输出命名。

纯函数级验证，不依赖 ffmpeg/显卡（探测函数打桩），秒级跑完。
预期值按操作描述表重构前的行为逐条推导（build_cmd_test.py 即行为 oracle）。
"""
import os
import re
import sys
import tempfile

import converter
from converter import (Task, build_cmd, resolve_out_path, operation,
                       KIND_CONVERT, KIND_TRIM, KIND_FRAME, KIND_AUDIO,
                       KIND_MUTE, KIND_NORM, KIND_GIF, KIND_MERGE, KIND_SPEED,
                       KIND_SHOT, KIND_STREAM, KIND_META, KIND_SUBTITLE,
                       KIND_RECORD, KIND_DELOGO)

# 打桩探测，命令可预期（真 ffmpeg/显卡路径由 batch1~4 集成测试覆盖）
converter.ddagrab_available = lambda: True
converter.nvenc_available = lambda: False

TMP = tempfile.mkdtemp(prefix="ffgui_ut_")
SRC = os.path.join(TMP, "源.mp4")  # 故意与下面的输出名 cl.* 不同，避免撞上同源保护
COVER = os.path.join(TMP, "cover.png")
with open(COVER, "wb") as f:
    f.write(b"fake png")  # meta 的封面分支只判断 os.path.isfile
OUT = os.path.join(TMP, "o.mp4")

P = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
S = ["-progress", "pipe:1", "-nostats", OUT]
NO = [OUT]  # 无 -progress 的操作（截帧/GIF/截图很快，不需要进度解析）
H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k"]
H264_MP4 = H264 + ["-movflags", "+faststart"]
NVENC_MP4 = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "25",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
GIF_VF = ("fps=12,scale=480:-1:flags=lanczos,"
          "split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
          "[s1][p]paletteuse=dither=bayer:bayer_scale=4")

fails = []


def check(name, got, want):
    if got == want:
        print(f"PASS  {name}")
    else:
        fails.append(name)
        print(f"FAIL  {name}\n    期望: {want}\n    实际: {got}")


def mk(**kw):
    """建任务：默认整段转码，参数按需覆盖；固定 name=cl.mp4 便于断言命名。"""
    args = dict(path=SRC, out_dir=TMP, name="cl.mp4",
                encode_mode="h264", out_format="mp4")
    args.update(kw)
    return Task(**args)


def cmd(t):
    got = build_cmd(t, OUT)
    # 合并任务的列表文件是临时名，掩码后再比
    got = ["<LIST>" if x.endswith(".txt") else x for x in got]
    return got


# ---------- 命令构建 ----------
check("转码 h264/mp4", cmd(mk()),
      P + ["-i", SRC] + H264_MP4 + S)
check("转码 h264/mkv（无 faststart）", cmd(mk(out_format="mkv")),
      P + ["-i", SRC] + H264 + S)
check("转码 webm（VP9 crf 30）", cmd(mk(out_format="webm", quality="high")),
      P + ["-i", SRC, "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
           "-c:a", "libopus"] + S)
check("转码 copy（恒 mp4）", cmd(mk(encode_mode="copy")),
      P + ["-i", SRC, "-c:v", "copy", "-c:a", "copy"] + S)
check("转码 mp3", cmd(mk(out_format="mp3")),
      P + ["-i", SRC, "-vn", "-c:a", "libmp3lame", "-q:a", "2"] + S)

check("截取片段（-ss 在 -i 前，-t 算时长）",
      cmd(mk(kind=KIND_TRIM, trim_start=5, trim_end=15)),
      P + ["-ss", "5.000", "-t", "10.000", "-i", SRC] + H264_MP4 + S)
check("截取片段 copy",
      cmd(mk(kind=KIND_TRIM, trim_start=5, trim_end=15, encode_mode="copy")),
      P + ["-ss", "5.000", "-t", "10.000", "-i", SRC,
           "-c:v", "copy", "-c:a", "copy"] + S)
check("截取片段（end=0 不加 -t）",
      cmd(mk(kind=KIND_TRIM, trim_start=2.5)),
      P + ["-ss", "2.500", "-i", SRC] + H264_MP4 + S)

check("抽帧封面（25% 处）", cmd(mk(kind=KIND_FRAME, duration=40)),
      P + ["-i", SRC, "-ss", "10.000", "-frames:v", "1", "-q:v", "2"] + NO)
check("抽帧封面（时长未知不加 -ss）", cmd(mk(kind=KIND_FRAME)),
      P + ["-i", SRC, "-frames:v", "1", "-q:v", "2"] + NO)

check("提取音频 mp3", cmd(mk(kind=KIND_AUDIO, audio_format="mp3")),
      P + ["-i", SRC, "-vn", "-c:a", "libmp3lame", "-q:a", "2"] + S)
check("提取音频 flac", cmd(mk(kind=KIND_AUDIO, audio_format="flac")),
      P + ["-i", SRC, "-vn", "-c:a", "flac"] + S)
check("提取音频 wav", cmd(mk(kind=KIND_AUDIO, audio_format="wav")),
      P + ["-i", SRC, "-vn", "-c:a", "pcm_s16le"] + S)
check("提取音频 aac", cmd(mk(kind=KIND_AUDIO, audio_format="aac")),
      P + ["-i", SRC, "-vn", "-c:a", "aac", "-b:a", "192k"] + S)

check("提取无声视频", cmd(mk(kind=KIND_MUTE)),
      P + ["-i", SRC, "-an", "-c:v", "copy"] + S)
check("响度归一化", cmd(mk(kind=KIND_NORM)),
      P + ["-i", SRC, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
      + H264_MP4 + S)

check("GIF（fps/宽度钳制 + 调色板）", cmd(mk(kind=KIND_GIF)),
      P + ["-i", SRC, "-vf", GIF_VF, "-loop", "0"] + NO)
check("GIF 带选段",
      cmd(mk(kind=KIND_GIF, trim_start=1, trim_end=3)),
      P + ["-i", SRC, "-ss", "1.000", "-t", "2.000",
           "-vf", GIF_VF, "-loop", "0"] + NO)

check("合并 copy", cmd(mk(kind=KIND_MERGE, encode_mode="copy",
                          merge_paths=[SRC, SRC])),
      P + ["-f", "concat", "-safe", "0", "-i", "<LIST>",
           "-c", "copy"] + S)
check("合并重编码", cmd(mk(kind=KIND_MERGE, merge_paths=[SRC, SRC])),
      P + ["-f", "concat", "-safe", "0", "-i", "<LIST>"] + H264_MP4 + S)

check("变速 1.5x", cmd(mk(kind=KIND_SPEED, speed_rate=1.5)),
      P + ["-i", SRC] + H264_MP4
      + ["-vf", "setpts=PTS/1.5", "-af", "atempo=1.5"] + S)
check("变速 1.0x 不挂滤镜", cmd(mk(kind=KIND_SPEED, speed_rate=1.0)),
      P + ["-i", SRC] + H264_MP4 + S)
check("变速 mp3 不挂 setpts", cmd(mk(kind=KIND_SPEED, out_format="mp3",
                                     speed_rate=1.25)),
      P + ["-i", SRC, "-vn", "-c:a", "libmp3lame", "-q:a", "2",
           "-af", "atempo=1.25"] + S)

check("定点截图", cmd(mk(kind=KIND_SHOT, shot_time=90)),
      P + ["-ss", "90.000", "-i", SRC, "-frames:v", "1", "-q:v", "2"] + NO)
check("流媒体下载", cmd(mk(kind=KIND_STREAM,
                           stream_url="https://x/y.m3u8")),
      P + ["-i", "https://x/y.m3u8", "-c", "copy"] + S)

check("元数据（标题+封面）",
      cmd(mk(kind=KIND_META, metadata_title="标题", cover_path=COVER)),
      P + ["-i", SRC, "-i", COVER, "-map", "0", "-map", "1",
           "-c:v:1", "mjpeg", "-disposition:v:1", "attached_pic",
           "-metadata", "title=标题", "-c", "copy"] + S)
check("元数据（无封面无标题）", cmd(mk(kind=KIND_META)),
      P + ["-i", SRC, "-map", "0", "-c", "copy"] + S)

check("字幕烧录（路径转义）",
      cmd(mk(kind=KIND_SUBTITLE, subtitle_path=r"D:\videos\字幕.srt")),
      P + ["-i", SRC, "-vf", "subtitles='D\\:/videos/字幕.srt'"]
      + H264_MP4 + S)
check("去水印", cmd(mk(kind=KIND_DELOGO, delogo_region="10:10:60:30")),
      P + ["-i", SRC, "-vf", "delogo=10:10:60:30"] + H264_MP4 + S)

REC = ["-f", "lavfi", "-i", "ddagrab=framerate=30:draw_mouse=1",
       "-vf", "hwdownload,format=bgra",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
       "-g", "30", "-movflags", "+frag_keyframe+empty_moov"]
check("录制（ddagrab 无音频）", cmd(mk(kind=KIND_RECORD)),
      P + REC + S)
converter.ddagrab_available = lambda: False
check("录制（无 ddagrab 回退 gdigrab）", cmd(mk(kind=KIND_RECORD)),
      P + ["-f", "gdigrab", "-framerate", "30", "-draw_mouse", "1",
           "-i", "desktop", "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-g", "30",
           "-movflags", "+frag_keyframe+empty_moov"] + S)
converter.ddagrab_available = lambda: True

check("未知 kind 回退整段转码", cmd(mk(kind="weird")),
      P + ["-i", SRC] + H264_MP4 + S)

# ---------- 硬件加速（打桩 NVENC 可用）----------
converter.nvenc_available = lambda: True
check("转码 hw_accel 走 NVENC", cmd(mk(hw_accel=True)),
      P + ["-i", SRC] + NVENC_MP4 + S)
check("录制 hw_accel + 音源",
      cmd(mk(kind=KIND_RECORD, hw_accel=True, record_fps=60,
             record_draw_mouse=False, record_audio="麦克风")),
      P + ["-f", "lavfi", "-i", "ddagrab=framerate=60:draw_mouse=0",
           "-vf", "hwdownload,format=bgra", "-f", "dshow", "-i",
           "audio=麦克风", "-c:v", "h264_nvenc", "-preset", "p5",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-map", "0:v:0", "-map", "1:a:0", "-g", "30",
           "-movflags", "+frag_keyframe+empty_moov"] + S)
converter.nvenc_available = lambda: False

# ---------- 输出命名 ----------
def name(t, tasks=None):
    return os.path.basename(resolve_out_path(t, tasks))


check("命名 转码 h264/mp4", name(mk()), "cl.mp4")
check("命名 copy 恒 mp4（哪怕 out_format=mkv）",
      name(mk(encode_mode="copy", out_format="mkv")), "cl.mp4")
check("命名 片段", name(mk(kind=KIND_TRIM, trim_start=5, trim_end=15)),
      "cl_片段5-15.mp4")
check("命名 封面", name(mk(kind=KIND_FRAME)), "cl_cover.png")
check("命名 音频 aac→m4a", name(mk(kind=KIND_AUDIO, audio_format="aac")),
      "cl.m4a")
check("命名 音频 flac", name(mk(kind=KIND_AUDIO, audio_format="flac")),
      "cl.flac")
check("命名 无声（保留源扩展名）",
      name(mk(path=os.path.join(TMP, "v.mov"), name="", kind=KIND_MUTE)),
      "v_无声.mov")
check("命名 响度归一", name(mk(kind=KIND_NORM)), "cl_响度归一.mp4")
check("命名 GIF", name(mk(kind=KIND_GIF)), "cl.gif")
check("命名 合并 copy", name(mk(kind=KIND_MERGE, encode_mode="copy")),
      "cl_合并.mp4")
check("命名 合并 mkv", name(mk(kind=KIND_MERGE, out_format="mkv")),
      "cl_合并.mkv")
check("命名 变速", name(mk(kind=KIND_SPEED, speed_rate=1.5)),
      "cl_变速1.5x.mp4")
check("命名 截图", name(mk(kind=KIND_SHOT, shot_time=90)), "cl_截图90s.png")
check("命名 流媒体", name(mk(kind=KIND_STREAM, stream_url="u")), "cl.mp4")
check("命名 元数据", name(mk(kind=KIND_META)), "cl_编辑.mp4")
check("命名 字幕", name(mk(kind=KIND_SUBTITLE)), "cl_字幕.mp4")
check("命名 去水印", name(mk(kind=KIND_DELOGO)), "cl_去水印.mp4")
check("命名 录制（时间戳）",
      re.sub(r"\d{8}_\d{6}", "TS", name(mk(kind=KIND_RECORD))),
      "录屏_TS.mp4")

# 输出与源同名：加 _converted，不能自己覆盖自己
# （旧代码里 GIF 分支没定义 out_ext，走到这里会 NameError——本次重构修复）
same = mk(path=os.path.join(TMP, "x.gif"), name="", kind=KIND_GIF)
check("命名 同源保护", name(same), "x_converted.gif")

# 同名去重：磁盘上已有 → _2；其它任务已占用 → _2
with open(os.path.join(TMP, "cl.mp4"), "wb") as f:
    f.write(b"x")
check("命名 去重（磁盘已存在）", name(mk()), "cl_2.mp4")
os.remove(os.path.join(TMP, "cl.mp4"))
other = mk()
other.out_path = os.path.join(TMP, "cl.mp4")
check("命名 去重（其它任务已占用）", name(mk(), {other.id: other}), "cl_2.mp4")

# ---------- 描述表完整性 ----------
missing = [k for k in (KIND_CONVERT, KIND_TRIM, KIND_FRAME, KIND_AUDIO,
                       KIND_MUTE, KIND_NORM, KIND_GIF, KIND_MERGE, KIND_SPEED,
                       KIND_SHOT, KIND_STREAM, KIND_META, KIND_SUBTITLE,
                       KIND_RECORD, KIND_DELOGO)
           if k not in converter.OPERATIONS]
check("16 种操作全部注册", missing, [])
check("未知 kind 回退整段转码", operation("weird") is
      converter.OPERATIONS[KIND_CONVERT], True)
check("record 标记为 record_like",
      operation(KIND_RECORD).record_like, True)

print(f"\n{len(fails)} 个失败" if fails else "\n全部通过")
sys.exit(1 if fails else 0)
