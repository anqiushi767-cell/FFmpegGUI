"""去水印测试：delogo 滤镜转码链路。"""
import os
import subprocess

from PySide6.QtCore import QCoreApplication, QTimer

from converter import Task, ConvertWorker, KIND_DELOGO, probe_duration

app = QCoreApplication([])
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testdelogo")
os.makedirs(tmp, exist_ok=True)

src = os.path.join(tmp, "测试.mp4")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
                "-c:v", "libx264", "-preset", "ultrafast", src], check=True)

t = Task(path=src, out_dir=tmp, encode_mode="h264", out_format="mp4",
         quality="fast", kind=KIND_DELOGO, delogo_region="20:20:60:40")
w = ConvertWorker(t)


def finish():
    ok = t.status == "done" and os.path.exists(t.out_path)
    dur = probe_duration(t.out_path) if ok else 0
    print("去水印:", "PASS" if ok else "FAIL",
          os.path.basename(t.out_path), f"时长={dur:.1f}s")
    if not ok:
        print("错误:", t.error[-300:])
    print("RESULT:", "PASS" if ok and 2.5 < dur < 3.5 else "FAIL")
    app.quit()


w.finished.connect(finish)
QTimer.singleShot(60000, lambda: (print("TIMEOUT"), app.quit()))
w.start()
app.exec()
