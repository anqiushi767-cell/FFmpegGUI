"""关于页：关于 / 了解作者 / 提供反馈 + 第三方开源组件声明。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame
from qfluentwidgets import (CardWidget, SubtitleLabel, TitleLabel, BodyLabel,
                            CaptionLabel, HyperlinkButton, ScrollArea,
                            SmoothMode)

from app_info import VERSION, AUTHOR_BILIBILI, FEEDBACK_URL, APP_REPO

THIRD_PARTY = [
    ("qfluentwidgets", "Fluent Design UI 组件库", "MIT"),
    ("PySide6 (Qt for Python)", "GUI 框架", "LGPLv3"),
    ("FFmpeg / ffprobe", "音视频转码引擎（命令行调用）", "LGPL/GPL"),
    ("PySideSix-Frameless-Window", "无边框窗口", "MIT"),
    ("darkdetect", "系统深浅色检测", "BSD-3-Clause"),
    ("pywin32", "Windows API 支持", "PSF"),
]


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSmoothMode(SmoothMode.COSINE, Qt.Vertical)
        outer.addWidget(scroll)

        host = QWidget()
        scroll.setWidget(host)
        scroll.enableTransparentBackground()

        root = QVBoxLayout(host)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)
        root.setAlignment(Qt.AlignTop)

        root.addWidget(TitleLabel("FFmpeg 转码器"))
        root.addWidget(CaptionLabel(f"批量音视频处理工具 · v{VERSION}"))

        # 关于
        about = CardWidget(self)
        la = QVBoxLayout(about)
        la.setContentsMargins(16, 14, 16, 14)
        la.setSpacing(8)
        la.addWidget(SubtitleLabel("关于"))
        la.addWidget(BodyLabel(
            "基于 FFmpeg 的批量音视频处理 GUI，支持 20 种操作：转码、"
            "剪辑、提取、GIF、录屏、字幕、去水印、流媒体下载等。"))
        root.addWidget(about)

        # 了解作者 / 提供反馈
        contact = CardWidget(self)
        lc = QVBoxLayout(contact)
        lc.setContentsMargins(16, 14, 16, 14)
        lc.setSpacing(8)
        lc.addWidget(SubtitleLabel("联系与反馈"))
        lc.addWidget(HyperlinkButton(AUTHOR_BILIBILI, "了解作者（B 站空间）",
                                     contact))
        lc.addWidget(HyperlinkButton(FEEDBACK_URL, "提供反馈（GitHub Issues）",
                                     contact))
        lc.addWidget(HyperlinkButton(
            f"https://github.com/{APP_REPO}", "项目仓库", contact))
        root.addWidget(contact)

        # 第三方库
        libs = CardWidget(self)
        ll = QVBoxLayout(libs)
        ll.setContentsMargins(16, 14, 16, 14)
        ll.setSpacing(10)
        ll.addWidget(SubtitleLabel("第三方开源组件"))
        for name, desc, lic in THIRD_PARTY:
            row = QVBoxLayout()
            row.setSpacing(2)
            row.addWidget(BodyLabel(f"{name}   ·   {lic}"))
            row.addWidget(CaptionLabel(desc))
            ll.addLayout(row)
        root.addWidget(libs)

        # 许可证说明
        note = CardWidget(self)
        ln = QVBoxLayout(note)
        ln.setContentsMargins(16, 14, 16, 14)
        ln.setSpacing(8)
        ln.addWidget(BodyLabel("许可证说明"))
        ln.addWidget(CaptionLabel(
            "本程序以 GPL-3.0 协议开源。"
            "以上组件均为宽松开源协议（MIT / BSD / PSF）或 LGPL。"
            "LGPL 要求用户可替换库版本（Python 虚拟环境天然满足）。"
            "FFmpeg 以独立进程命令行方式调用，不构成衍生作品。"
            "各组件许可证全文见其官方仓库。"))
        root.addWidget(note)
