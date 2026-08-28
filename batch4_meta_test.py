"""元数据编辑测试：标题 + 封面嵌入。"""
import os
import subprocess

from PySide6.QtCore import QCoreApplication, QTimer

from converter import Task, ConvertWorker, KIND_META, CREATE_NO_WINDOW

app = QCoreApplication([])
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testmeta")
os.makedirs(tmp, exist_ok=True)

# 测试视频 + 封面图
src = os.path.join(tmp, "测试.mp4")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
                "-c:v", "libx264", "-preset", "ultrafast", src], check=True)
cover = os.path.join(tmp, "cover.png")
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:size=200x200",
                "-frames:v", "1", cover], check=True)

t = Task(path=src, out_dir=tmp, encode_mode="copy", kind=KIND_META,
         metadata_title="测试标题", cover_path=cover)
w = ConvertWorker(t)


def finish():
    ok = t.status == "done" and os.path.exists(t.out_path)
    print("转码:", "PASS" if ok else "FAIL", os.path.basename(t.out_path))
    if ok:
        # 验证标题
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format_tags=title", "-of",
                            "default=noprint_wrappers=1:nokey=1", t.out_path],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
        title = p.stdout.strip()
        print("标题:", repr(title), "(期望 测试标题)")
        # 验证 attached_pic
        p2 = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "stream_disposition=attached_pic", "-of",
                             "default=noprint_wrappers=1:nokey=1", t.out_path],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=CREATE_NO_WINDOW)
        has_pic = "1" in p2.stdout
        print("封面嵌入:", has_pic)
        ok = ok and title == "测试标题" and has_pic
    print("RESULT:", "PASS" if ok else "FAIL")
    app.quit()


w.finished.connect(finish)
QTimer.singleShot(30000, lambda: (print("TIMEOUT"), app.quit()))
w.start()
app.exec()
