"""任务卡片：60px 信息密度 + 状态色 + 进度条（GD 风，性能优化版）。"""
import os
from functools import lru_cache
from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from qfluentwidgets import (CardWidget, ProgressBar, IndeterminateProgressBar,
                            StrongBodyLabel, CaptionLabel, TransparentToolButton,
                            FluentIcon, IconWidget, qconfig, Theme)

from converter import fmt_size, fmt_dur


# 状态色深浅成对（GD 笔记第 4 节原表）
STATUS_COLOR_DARK = {
    "pending": "#8A8A8A",
    "running": "#FCE100",   # 橙黄（深色主题亮版）
    "done":    "#6CCB5F",   # 绿（深色主题亮版）
    "error":   "#FF99A4",   # 红（深色主题亮版）
}
STATUS_COLOR_LIGHT = {
    "pending": "#8A8A8A",
    "running": "#9D5D00",   # 橙黄（浅色主题暗版）
    "done":    "#0F7B0F",   # 绿（浅色主题暗版）
    "error":   "#C42B1C",   # 红（浅色主题暗版）
}
STATUS_TEXT = {
    "pending": "等待中",
    "running": "转码中",
    "done":    "已完成",
    "error":   "失败",
}


def status_color(status):
    table = STATUS_COLOR_LIGHT if qconfig.theme == Theme.LIGHT else STATUS_COLOR_DARK
    return table[status]


@lru_cache(maxsize=16)
def status_dot(color):
    """状态圆点 pixmap 缓存——避免每帧 setStyleSheet 触发全表样式重算。"""
    pm = QPixmap(10, 10)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, 10, 10)
    p.end()
    return pm


class TaskCard(CardWidget):
    def __init__(self, task, on_open_file=None, on_open_folder=None,
                 on_delete=None, on_trim=None, on_retry=None, parent=None):
        super().__init__(parent)
        self.task = task
        self.on_open_file = on_open_file
        self.on_open_folder = on_open_folder
        self.on_delete = on_delete
        self.on_trim = on_trim
        self.on_retry = on_retry
        self._bar_color = ""
        self.setFixedHeight(78)
        # 1.11 的 CardWidget 默认无静态阴影（悬停才渐入），无需处理

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 9, 14, 11)
        v.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(12)

        self.icon = IconWidget(FluentIcon.PLAY, self)
        self.icon.setFixedSize(40, 40)
        top.addWidget(self.icon)

        mid = QVBoxLayout()
        mid.setSpacing(3)
        self.nameLabel = StrongBodyLabel(task.name)
        self.nameLabel.setToolTip(task.path)
        mid.addWidget(self.nameLabel)
        self.infoLabel = CaptionLabel("")
        mid.addWidget(self.infoLabel)
        top.addLayout(mid, 1)

        self.statusDot = QLabel()
        self.statusDot.setFixedSize(10, 10)
        top.addWidget(self.statusDot, 0, Qt.AlignVCenter)

        self.openBtn = TransparentToolButton(FluentIcon.PLAY, self)
        self.openBtn.setFixedSize(30, 30)
        self.openBtn.setToolTip("打开文件")
        self.openBtn.clicked.connect(self._open_file)
        self.openBtn.hide()
        top.addWidget(self.openBtn, 0, Qt.AlignVCenter)

        self.folderBtn = TransparentToolButton(FluentIcon.FOLDER, self)
        self.folderBtn.setFixedSize(30, 30)
        self.folderBtn.setToolTip("在文件夹中定位")
        self.folderBtn.clicked.connect(self._open_folder)
        self.folderBtn.hide()
        top.addWidget(self.folderBtn, 0, Qt.AlignVCenter)

        self.trimBtn = TransparentToolButton(FluentIcon.CUT, self)
        self.trimBtn.setFixedSize(30, 30)
        self.trimBtn.setToolTip("截取片段")
        self.trimBtn.clicked.connect(self._trim)
        # 抽帧封面任务本身不需要再截取
        self.trimBtn.setVisible(self.task.kind != "frame")
        top.addWidget(self.trimBtn, 0, Qt.AlignVCenter)

        self.retryBtn = TransparentToolButton(FluentIcon.SYNC, self)
        self.retryBtn.setFixedSize(30, 30)
        self.retryBtn.setToolTip("重试")
        self.retryBtn.clicked.connect(self._retry)
        top.addWidget(self.retryBtn, 0, Qt.AlignVCenter)

        self.delBtn = TransparentToolButton(FluentIcon.DELETE, self)
        self.delBtn.setFixedSize(30, 30)
        self.delBtn.clicked.connect(self._delete)
        top.addWidget(self.delBtn, 0, Qt.AlignVCenter)

        v.addLayout(top)

        self.bar = ProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)

        self.indBar = IndeterminateProgressBar(self)
        self.indBar.setFixedHeight(4)
        self.indBar.setVisible(False)

        v.addWidget(self.bar)
        v.addWidget(self.indBar)

        self.refresh()

    def _open_file(self):
        if self.on_open_file:
            self.on_open_file(self.task.id)
        elif self.task.out_path and os.path.exists(self.task.out_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.task.out_path))

    def _open_folder(self):
        if self.on_open_folder:
            self.on_open_folder(self.task.id)

    def _trim(self):
        if self.on_trim:
            self.on_trim(self.task.id)

    def _retry(self):
        if self.on_retry:
            self.on_retry(self.task.id)

    def _delete(self):
        if self.on_delete:
            self.on_delete(self.task.id)

    def refresh(self):
        t = self.task
        color = status_color(t.status)
        self.statusDot.setPixmap(status_dot(color))

        is_recording = t.kind == "record" and t.status == "running"
        parts = []
        if not is_recording:  # 录制中无源文件，不显示 0 B 误导
            parts.append(fmt_size(t.size))
        if t.duration > 0:
            parts.append(fmt_dur(t.duration))
        if t.status == "running" and not is_recording:
            if t.speed:
                parts.append(t.speed)
            if t.eta:
                parts.append(f"剩{t.eta}")
            parts.append(f"{t.percent}%")
        parts.append("录制中" if is_recording else STATUS_TEXT[t.status])
        self.infoLabel.setText("   ·   ".join(parts))

        if t.status == "running":
            if t.duration > 0:
                self.bar.setVisible(True)
                self.indBar.setVisible(False)
                self.bar.setValue(t.percent)
            else:
                self.bar.setVisible(False)
                self.indBar.setVisible(True)
        else:
            self.bar.setVisible(True)
            self.indBar.setVisible(False)
            self.bar.setValue(100 if t.status == "done" else
                              (0 if t.status == "pending" else 100))
        # 进度条颜色只在状态变化时设置一次，避免重复 repaint
        if color != self._bar_color:
            self._bar_color = color
            self.bar.setCustomBarColor(QColor(color), QColor(0, 0, 0, 0))
        self.openBtn.setVisible(t.status == "done")
        self.folderBtn.setVisible(t.status == "done")
        self.retryBtn.setVisible(t.status == "error")
