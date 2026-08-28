"""去水印选区弹窗：预览视频帧 + 鼠标拖拽框选矩形区域。"""
import os
import subprocess
import tempfile
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QPixmap, QPen, QColor
from PySide6.QtWidgets import QWidget
from qfluentwidgets import Dialog, CaptionLabel, BodyLabel

from converter import CREATE_NO_WINDOW


def probe_size(path):
    """ffprobe 读视频宽高，失败返回 (0, 0)。"""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height",
                            "-of", "csv=s=x:p=0", path],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60,
                           creationflags=CREATE_NO_WINDOW)
        w, h = p.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


class SelectLabel(QWidget):
    """预览图 + 拖拽画选区矩形，坐标换算回原始分辨率。"""

    def __init__(self, src_path, on_region=None, parent=None):
        super().__init__(parent)
        self._on_region = on_region
        self._orig_w, self._orig_h = probe_size(src_path)
        self._pixmap = self._extract_frame(src_path)
        self._scale = 1.0
        self._start = None
        self._end = None
        self._region = None

        if not self._pixmap.isNull():
            max_w = 460
            if self._pixmap.width() > max_w:
                self._scale = max_w / self._pixmap.width()
            self._disp = self._pixmap.scaled(
                int(self._pixmap.width() * self._scale),
                int(self._pixmap.height() * self._scale),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setFixedSize(self._disp.width(), self._disp.height())
        else:
            self._disp = QPixmap()
            self.setFixedSize(460, 260)
        self.setCursor(Qt.CrossCursor)

    def _extract_frame(self, path):
        """抽 30% 处一帧为 QPixmap。"""
        try:
            p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of",
                                "default=noprint_wrappers=1:nokey=1", path],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60,
                               creationflags=CREATE_NO_WINDOW)
            dur = float(p.stdout.strip() or 0)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel",
                            "error", "-ss", f"{dur * 0.3:.2f}", "-i", path,
                            "-frames:v", "1", tmp],
                           creationflags=CREATE_NO_WINDOW, timeout=60)
            pm = QPixmap(tmp)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return pm
        except Exception:
            return QPixmap()

    def _to_orig(self, pt):
        return int(pt.x() / self._scale), int(pt.y() / self._scale)

    def get_region_str(self):
        if not self._region:
            return ""
        x, y, w, h = self._region
        return f"{x}:{y}:{w}:{h}"

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self._disp.isNull():
            painter.drawPixmap(0, 0, self._disp)
        if self._start and self._end:
            rect = QRect(self._start, self._end).normalized()
            pen = QPen(QColor("#39C5BB"), 2)
            painter.setPen(pen)
            painter.setBrush(QColor(57, 197, 187, 60))
            painter.drawRect(rect)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = e.pos()
            self._end = e.pos()
            self.update()

    def mouseMoveEvent(self, e):
        if self._start:
            self._end = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._start:
            self._end = e.pos()
            rect = QRect(self._start, self._end).normalized()
            if rect.width() >= 5 and rect.height() >= 5:
                ox1, oy1 = self._to_orig(rect.topLeft())
                ox2, oy2 = self._to_orig(rect.bottomRight())
                self._region = (ox1, oy1, ox2 - ox1, oy2 - oy1)
                if self._on_region:
                    self._on_region(self._region)
            self.update()


class DelogoDialog(Dialog):
    """去水印弹窗：拖拽框选区域，返回 'x:y:w:h'。"""

    def __init__(self, task_name, src_path, parent=None):
        super().__init__("去水印", task_name, parent)
        self.region_str = ""
        self._build(src_path)

    def _build(self, src_path):
        self.selectLabel = SelectLabel(src_path, on_region=self._on_region)
        self.textLayout.addWidget(self.selectLabel, 0, Qt.AlignHCenter)
        self.hintLabel = CaptionLabel("按住鼠标左键在画面上拖拽框选水印区域")
        self.textLayout.addWidget(self.hintLabel)
        self.coordLabel = BodyLabel("未选择区域")
        self.textLayout.addWidget(self.coordLabel)
        self.yesButton.setText("生成任务")
        self.yesButton.setEnabled(False)
        self.yesButton.clicked.connect(self._ok)

    def _on_region(self, region):
        x, y, w, h = region
        self.region_str = f"{x}:{y}:{w}:{h}"
        self.coordLabel.setText(f"区域：x={x} y={y} 宽={w} 高={h}")
        self.yesButton.setEnabled(True)

    def _ok(self):
        if self.region_str:
            self.accept()
