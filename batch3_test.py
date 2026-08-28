"""第三批测试：流媒体下载（本地 HLS 分片模拟 m3u8）。"""
import os
import subprocess

from PySide6.QtCore import QCoreApplication, QTimer

from converter import Task, ConvertWorker, probe_duration, KIND_STREAM

app = QCoreApplication([])
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testtmp3")
os.makedirs(tmp, exist_ok=True)

# 生成 6 秒视频
src = os.path.join(tmp, "src.mp4")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-shortest", src], check=True)

# 切成 HLS（m3u8 + ts 分片）
hls_dir = os.path.join(tmp, "hls")
os.makedirs(hls_dir, exist_ok=True)
m3u8 = os.path.join(hls_dir, "index.m3u8")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", src, "-c", "copy", "-f", "hls", "-hls_time", "2",
                "-hls_list_size", "0", m3u8], check=True)
print("HLS 生成:", os.path.exists(m3u8), "分片数:",
      len([f for f in os.listdir(hls_dir) if f.endswith(".ts")]))

# 流媒体任务下载（本地 m3u8 路径当 URL 测链路）
t = Task(path=m3u8, out_dir=tmp, encode_mode="copy",
         kind=KIND_STREAM, stream_url=m3u8)
t.name = "流媒体测试"
w = ConvertWorker(t)
w.status.connect(lambda tid, st, extra: print("STATUS:", st))
w.finished.connect(lambda: _finish(t))


def _finish(t):
    ok = t.status == "done" and os.path.exists(t.out_path)
    dur = probe_duration(t.out_path) if ok else 0
    print(f"下载: {'PASS' if ok else 'FAIL'} 文件={os.path.basename(t.out_path)} "
          f"时长={dur:.1f}s (期望≈6)")
    print("RESULT:", "PASS" if ok and 5.5 < dur < 6.5 else "FAIL")
    app.quit()


QTimer.singleShot(60000, lambda: (print("TIMEOUT"), app.quit()))
w.start()
app.exec()
