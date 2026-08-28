"""新功能集成测试：截取片段（copy + 重编码）+ 抽帧封面。"""
import os
import subprocess
import tempfile

from PySide6.QtCore import QCoreApplication, QTimer

from converter import Task, ConvertWorker, probe_duration, parse_time

app = QCoreApplication([])
tmp = tempfile.mkdtemp()

# 生成 10 秒测试视频
src = os.path.join(tmp, "测试.mp4")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-shortest", src], check=True)
print("源时长:", probe_duration(src))

results = []


def make(task, label):
    w = ConvertWorker(task)
    w.status.connect(lambda tid, st, extra: results.append((label, st))
                     if st != "running" else None)
    w.finished.connect(lambda: check_done(label))
    workers.append(w)
    w.start()


pending = {"trim_copy": False, "trim_enc": False, "frame": False}
workers = []


def check_done(label):
    pending[label] = True
    if all(pending.values()):
        for l, t in tasks_by_label:
            print(f"--- {l}: status={t.status} out={os.path.basename(t.out_path or '')}"
                  f" 存在={os.path.exists(t.out_path) if t.out_path else False}")
        ok = all(t.status == "done" for _, t in tasks_by_label)
        print("RESULT:", "PASS" if ok else "FAIL")
        app.quit()


tasks_by_label = []

# 1) 截取片段 copy 模式（2s~5s）
t1 = Task(path=src, out_dir=tmp, encode_mode="copy", kind="trim",
          trim_start=2, trim_end=5)
tasks_by_label.append(("trim_copy", t1))
make(t1, "trim_copy")

# 2) 截取片段 重编码 mp4（0~3s）
t2 = Task(path=src, out_dir=tmp, encode_mode="h264", out_format="mp4",
          kind="trim", trim_start=0, trim_end=3, quality="fast")
tasks_by_label.append(("trim_enc", t2))
make(t2, "trim_enc")

# 3) 抽帧封面
t3 = Task(path=src, out_dir=tmp, encode_mode="copy", kind="frame")
tasks_by_label.append(("frame", t3))
make(t3, "frame")

QTimer.singleShot(60000, lambda: (print("TIMEOUT"), app.quit()))
app.exec()
