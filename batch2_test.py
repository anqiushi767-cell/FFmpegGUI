"""第二批新功能测试：合并视频 / 变速 / 定点截图。"""
import os
import subprocess

from PySide6.QtCore import QCoreApplication, QTimer

from converter import (Task, ConvertWorker, probe_duration,
                       KIND_MERGE, KIND_SPEED, KIND_SHOT)

app = QCoreApplication([])
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testtmp2")
os.makedirs(tmp, exist_ok=True)

# 两个 4 秒测试视频（同编码，可流拷贝合并）
srcs = []
for i, dur in enumerate((4, 4)):
    p = os.path.join(tmp, f"seg{i}.mp4")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc=duration={dur}:size=320x240:rate=25",
                    "-f", "lavfi", "-i", f"sine=frequency={440+i*100}:duration={dur}",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", p], check=True)
    srcs.append(p)
print("段时长:", [round(probe_duration(p), 2) for p in srcs])

done = {"merge": False, "speed": False, "shot": False}


def check_done():
    if len(tasks) == 3 and all(t.status == "done" for t in tasks.values()):
        results = []
        for name, t in tasks.items():
            ok = t.status == "done" and os.path.exists(t.out_path)
            results.append(f"{name}: {'PASS' if ok else 'FAIL'} "
                           f"({os.path.basename(t.out_path)})")
        # 合并时长 ≈ 8s（4+4），变速 1.5x ≈ 2.67s（4/1.5）
        m = probe_duration(tasks["merge"].out_path)
        s = probe_duration(tasks["speed"].out_path)
        results.append(f"merge 时长={m:.1f}s (期望≈8)")
        results.append(f"speed 时长={s:.1f}s (期望≈2.67)")
        all_ok = (all(t.status == "done" and os.path.exists(t.out_path)
                      for t in tasks.values())
                  and 7.5 < m < 8.5 and 2.3 < s < 3.0)
        print("\n".join(results))
        print("RESULT:", "PASS" if all_ok else "FAIL")
        app.quit()


tasks = {}
workers = []


def launch(t, key):
    tasks[key] = t
    w = ConvertWorker(t)
    w.status.connect(lambda tid, st, extra: check_done() if st != "running" else None)
    workers.append(w)
    w.start()


# 合并（copy 模式）
launch(Task(path=srcs[0], out_dir=tmp, encode_mode="copy",
            kind=KIND_MERGE, merge_paths=srcs), "merge")
# 变速 1.5x
launch(Task(path=srcs[0], out_dir=tmp, encode_mode="h264", out_format="mp4",
            kind=KIND_SPEED, speed_rate=1.5, quality="fast"), "speed")
# 定点截图 t=2s
launch(Task(path=srcs[0], out_dir=tmp, encode_mode="copy",
            kind=KIND_SHOT, shot_time=2), "shot")

QTimer.singleShot(90000, lambda: (print("TIMEOUT"), app.quit()))
app.exec()
