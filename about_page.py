"""关于页：程序信息 + 第三方开源组件声明。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame
from qfluentwidgets import (CardWidget, SubtitleLabel, TitleLabel, BodyLabel,
                            CaptionLabel, ScrollArea, SmoothMode)

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

        # 内容多，套滚动区避免卡片被布局压扁
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
        root.addWidget(CaptionLabel("GD 风格批量视频转码工具 · v1.0"))

        # 程序信息
        info = CardWidget(self)
        li = QVBoxLayout(info)
        li.setContentsMargins(16, 14, 16, 14)
        li.setSpacing(8)
        li.addWidget(BodyLabel(
            "功能：拖入视频批量转码（H.264 MP4 / MKV / WebM / MP3），"
            "画质档位、全局进度、完成后关机、开机自启、系统托盘。"))
        li.addWidget(BodyLabel(
            "UI 参考 Ghost Downloader（MIT 协议开源项目）的设计风格，"
            "仅借鉴设计语言，代码独立实现。"))
        root.addWidget(info)

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
            "以上组件均为宽松开源协议（MIT / BSD / PSF）或 LGPL：使用它们不需要开源本程序。"
            "LGPL 要求用户可替换库版本（Python 虚拟环境天然满足）。"
            "FFmpeg 以独立进程命令行方式调用，不构成衍生作品。"
            "各组件许可证全文见其官方仓库。"))
        root.addWidget(note)
