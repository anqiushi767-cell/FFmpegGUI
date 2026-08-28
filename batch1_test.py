"""第一批新功能测试：提取音频 / 响度归一化 / GIF。"""
import os
import subprocess

from PySide6.QtCore import QCoreApplication, QTimer

from converter import Task, ConvertWorker, probe_duration

app = QCoreApplication([])
tmp = os.path.dirname(os.path.abspath(__file__)) + "\\_testtmp"
os.makedirs(tmp, exist_ok=True)

src = os.path.join(tmp, "测试.mp4")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-shortest", src], check=True)
print("源时长:", probe_duration(src))

tasks_by_label = [
    ("audio", Task(path=src, out_dir=tmp, encode_mode="copy", kind="audio")),
    ("norm", Task(path=src, out_dir=tmp, encode_mode="h264",
                  out_format="mp4", kind="normalize", quality="fast")),
    ("gif", Task(path=src, out_dir=tmp, encode_mode="copy", kind="gif",
                 trim_start=1, trim_end=3)),
]

workers = [ConvertWorker(t) for _, t in tasks_by_label]
done = {l: False for l, _ in tasks_by_label}


def check(label):
    done[label] = True
    if all(done.values()):
        ok = True
        for l, t in tasks_by_label:
            exists = os.path.exists(t.out_path) if t.out_path else False
            size = os.path.getsize(t.out_path) if exists else 0
            print(f"--- {l}: status={t.status} 存在={exists} "
                  f"大小={size} 文件={os.path.basename(t.out_path or '')}")
            ok = ok and t.status == "done" and exists
        # GIF 时长验证（2 秒片段）
        gif = tasks_by_label[2][1].out_path
        if os.path.exists(gif):
            p = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of",
                 "default=noprint_wrappers=1:nokey=1", gif],
                capture_output=True, text=True)
            try:
                d = float(p.stdout.strip())
                print(f"GIF 时长: {d:.2f}s (期望约 2s)")
            except ValueError:
                pass
        print("RESULT:", "PASS" if ok else "FAIL")
        app.quit()


for (label, _), w in zip(tasks_by_label, workers):
    w.status.connect(lambda tid, st, extra, l=label:
                     check(l) if st != "running" else None)
    w.start()

QTimer.singleShot(120000, lambda: (print("TIMEOUT"), app.quit()))
app.exec()
