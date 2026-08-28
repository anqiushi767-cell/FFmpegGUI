"""字幕烧录测试：含中文+空格的路径，验证 subtitles 滤镜转义。"""
import os
import subprocess

from PySide6.QtCore import QCoreApplication, QTimer

from converter import Task, ConvertWorker, KIND_SUBTITLE, probe_duration

app = QCoreApplication([])
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testsub 字幕")
os.makedirs(tmp, exist_ok=True)

src = os.path.join(tmp, "测试视频.mp4")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=25",
                "-c:v", "libx264", "-preset", "ultrafast", src], check=True)

# 写一个字幕文件（含中文 + 空格路径）
sub_path = os.path.join(tmp, "我的 字幕.srt")
with open(sub_path, "w", encoding="utf-8") as f:
    f.write("1\n00:00:00,000 --> 00:00:04,000\n测试字幕烧录\n")

t = Task(path=src, out_dir=tmp, encode_mode="h264", out_format="mp4",
         quality="fast", kind=KIND_SUBTITLE, subtitle_path=sub_path)
w = ConvertWorker(t)


def finish():
    ok = t.status == "done" and os.path.exists(t.out_path)
    dur = probe_duration(t.out_path) if ok else 0
    print("字幕烧录:", "PASS" if ok else "FAIL",
          os.path.basename(t.out_path), f"时长={dur:.1f}s")
    if not ok:
        print("错误:", t.error[-300:])
    print("RESULT:", "PASS" if ok and 3.5 < dur < 4.5 else "FAIL")
    app.quit()


w.finished.connect(finish)
QTimer.singleShot(60000, lambda: (print("TIMEOUT"), app.quit()))
w.start()
app.exec()
