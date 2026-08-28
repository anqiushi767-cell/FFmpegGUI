"""集成测试：生成 3 秒测试视频 → 真实转码 → 验证输出 mp4 与信号流。"""
import os
import subprocess
import tempfile

from PySide6.QtCore import QCoreApplication, QTimer

from converter import Task, ConvertWorker, probe_duration

app = QCoreApplication([])
tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "测试视频.flv")

# 生成测试视频（FLV 封装，模拟用户真实场景）
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-c:v", "flv", "-c:a", "aac", "-shortest", src],
               check=True)
print(f"测试视频已生成: {src} ({os.path.getsize(src)} bytes)")

task = Task(path=src, out_dir=tmp, encode_mode="h264")
events = []
w = ConvertWorker(task)
w.progress.connect(lambda tid, pct: events.append(("progress", pct)))
w.speed.connect(lambda tid, spd: events.append(("speed", spd)))
w.status.connect(lambda tid, st, extra: events.append(("status", st)))
w.finished.connect(lambda: (
    print(f"探测时长: {task.duration:.2f}s"),
    print(f"输出文件: {os.path.exists(task.out_path)} → {task.out_path}"),
    print(f"输出大小: {os.path.getsize(task.out_path) if os.path.exists(task.out_path) else 0} bytes"),
    print(f"状态事件: {[e[1] for e in events if e[0]=='status']}"),
    print(f"进度点数量: {sum(1 for e in events if e[0]=='progress')}"),
    print(f"最大进度: {max([e[1] for e in events if e[0]=='progress'], default=-1)}"),
    print("RESULT:", "PASS" if task.status == "done" else f"FAIL ({task.error})"),
    app.quit(),
))
QTimer.singleShot(60000, lambda: (print("RESULT: TIMEOUT"), app.quit()))
w.start()
app.exec()
