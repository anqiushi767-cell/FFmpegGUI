"""设置页：输出目录、编码、画质、格式、开机自启、完成后关机、外观主题、主题色、FFmpeg 更新。"""
import os
import sys
import threading
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QFileDialog, QToolButton, QFrame)
from PySide6.QtGui import QColor
from qfluentwidgets import (CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
                            ComboBox, LineEdit, PushButton, ToolButton, FluentIcon,
                            setTheme, setThemeColor, Theme, SwitchButton,
                            ScrollArea, SmoothMode)

from config import config
from converter import ffmpeg_version, latest_ffmpeg_version, version_tuple


PRESET_COLORS = ["#0078D4", "#39C5BB", "#6CCB5F", "#8862E0", "#E91E63", "#FF8C00"]

APP_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "FFmpegGUI"


def get_autostart():
    """读注册表判断是否已设置开机自启。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def set_autostart(enabled):
    """写/删 HKCU Run 键（当前用户自启，无需管理员权限）。"""
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                         winreg.KEY_SET_VALUE)
    if enabled:
        # 强制 pythonw（无控制台），避免自启时弹黑窗
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        cmd = f'"{exe}" "{os.path.join(APP_DIR, "main.py")}" --tray'
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
    else:
        try:
            winreg.DeleteValue(key, APP_NAME)
        except OSError:
            pass
    winreg.CloseKey(key)


def read_system_accent():
    """读 Windows 强调色（注册表 DWM ColorizationColor，格式 AABBGGRR）。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\DWM")
        v, _ = winreg.QueryValueEx(key, "ColorizationColor")
        winreg.CloseKey(key)
        return QColor(v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
    except Exception:
        return None


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 内容多，套滚动区避免卡片被布局压扁（"折叠"假象）
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

        root.addWidget(SubtitleLabel("设置", host))

        # 输出目录
        card1 = CardWidget(self)
        l1 = QVBoxLayout(card1)
        l1.setContentsMargins(16, 14, 16, 14)
        l1.setSpacing(8)
        l1.addWidget(BodyLabel("输出目录", card1))
        row = QHBoxLayout()
        self.outEdit = LineEdit(card1)
        self.outEdit.setText(config.out_dir or "（与源文件相同）")
        self.outEdit.setReadOnly(True)
        row.addWidget(self.outEdit, 1)
        browse = ToolButton(FluentIcon.FOLDER, card1)
        browse.clicked.connect(self._pick_dir)
        row.addWidget(browse)
        reset = PushButton("默认", card1)
        reset.clicked.connect(self._reset_dir)
        row.addWidget(reset)
        l1.addLayout(row)
        root.addWidget(card1)

        # 编码设置
        card2 = CardWidget(self)
        l2 = QVBoxLayout(card2)
        l2.setContentsMargins(16, 14, 16, 14)
        l2.setSpacing(8)

        l2.addWidget(BodyLabel("编码方式", card2))
        self.encodeCombo = ComboBox(card2)
        self.encodeCombo.addItems([
            "重编码 H.264（兼容性最好，文件小）",
            "无损封装（仅换容器，速度快，需源已是 H.264）",
        ])
        self.encodeCombo.setCurrentIndex(0 if config.encode_mode == "h264" else 1)
        self.encodeCombo.currentIndexChanged.connect(self._on_encode)
        l2.addWidget(self.encodeCombo)

        l2.addWidget(BodyLabel("画质档位", card2))
        self.qualityCombo = ComboBox(card2)
        self.qualityCombo.addItems([
            "极速（转码最快，文件大）",
            "平衡（推荐）",
            "高质量（更小更清晰，转码慢）",
        ])
        self.qualityCombo.setCurrentIndex(
            {"fast": 0, "balanced": 1, "high": 2}[config.quality])
        self.qualityCombo.currentIndexChanged.connect(self._on_quality)
        l2.addWidget(self.qualityCombo)

        l2.addWidget(BodyLabel("输出格式", card2))
        self.formatCombo = ComboBox(card2)
        self.formatCombo.addItems([
            "MP4（H.264 + AAC，最通用）",
            "MKV（H.264 + AAC）",
            "WebM（VP9 + Opus，速度慢）",
            "MP3（仅提取音频）",
        ])
        self.formatCombo.setCurrentIndex(
            {"mp4": 0, "mkv": 1, "webm": 2, "mp3": 3}[config.out_format])
        self.formatCombo.currentIndexChanged.connect(self._on_format)
        l2.addWidget(self.formatCombo)
        root.addWidget(card2)

        # 开机自启
        card_auto = CardWidget(self)
        la = QHBoxLayout(card_auto)
        la.setContentsMargins(16, 14, 16, 14)
        la_col = QVBoxLayout()
        la_col.addWidget(BodyLabel("开机自启", card_auto))
        la_col.addWidget(BodyLabel("开机后静默启动到托盘，随时可拖文件转码",
                                   card_auto))
        la_col.addStretch(1)
        la.addLayout(la_col, 1)
        self.autoSwitch = SwitchButton(card_auto)
        self.autoSwitch.setChecked(get_autostart())
        self.autoSwitch.checkedChanged.connect(set_autostart)
        la.addWidget(self.autoSwitch, 0, Qt.AlignVCenter)
        root.addWidget(card_auto)

        # 硬件加速（NVENC）
        card_hw = CardWidget(self)
        lh = QHBoxLayout(card_hw)
        lh.setContentsMargins(16, 14, 16, 14)
        hw_col = QVBoxLayout()
        hw_col.addWidget(BodyLabel("硬件加速（NVIDIA NVENC）", card_hw))
        hw_col.addWidget(BodyLabel("显卡转码，速度翻倍（需 NVIDIA 显卡 + 驱动支持）",
                                   card_hw))
        hw_col.addStretch(1)
        lh.addLayout(hw_col, 1)
        self.hwSwitch = SwitchButton(card_hw)
        from converter import nvenc_available
        hw_ok = nvenc_available()
        self.hwSwitch.setChecked(config.hw_accel and hw_ok)
        self.hwSwitch.setEnabled(hw_ok)
        self.hwSwitch.checkedChanged.connect(self._on_hw)
        lh.addWidget(self.hwSwitch, 0, Qt.AlignVCenter)
        root.addWidget(card_hw)

        # 录屏鼠标光标
        card_mouse = CardWidget(self)
        lm = QHBoxLayout(card_mouse)
        lm.setContentsMargins(16, 14, 16, 14)
        mouse_col = QVBoxLayout()
        mouse_col.addWidget(BodyLabel("录屏显示鼠标光标", card_mouse))
        mouse_col.addWidget(BodyLabel("关闭后录屏画面不含光标，但抓屏不再抽搐",
                                      card_mouse))
        mouse_col.addStretch(1)
        lm.addLayout(mouse_col, 1)
        self.mouseSwitch = SwitchButton(card_mouse)
        self.mouseSwitch.setChecked(config.record_draw_mouse)
        self.mouseSwitch.checkedChanged.connect(self._on_mouse)
        lm.addWidget(self.mouseSwitch, 0, Qt.AlignVCenter)
        root.addWidget(card_mouse)

        # 完成后关机
        card_shutdown = CardWidget(self)
        ls = QHBoxLayout(card_shutdown)
        ls.setContentsMargins(16, 14, 16, 14)
        label_col = QVBoxLayout()
        label_col.addWidget(BodyLabel("全部任务完成后关机", card_shutdown))
        label_col.addWidget(BodyLabel("批量转码挂机时有用（60 秒倒计时，可取消）",
                                      card_shutdown))
        label_col.addStretch(1)
        ls.addLayout(label_col, 1)
        self.shutdownSwitch = SwitchButton(card_shutdown)
        self.shutdownSwitch.setChecked(config.shutdown_after_done)
        self.shutdownSwitch.checkedChanged.connect(self._on_shutdown)
        ls.addWidget(self.shutdownSwitch, 0, Qt.AlignVCenter)
        root.addWidget(card_shutdown)

        # 并发转码数
        card_conc = CardWidget(self)
        lc = QHBoxLayout(card_conc)
        lc.setContentsMargins(16, 14, 16, 14)
        conc_col = QVBoxLayout()
        conc_col.addWidget(BodyLabel("并发转码数", card_conc))
        conc_col.addWidget(BodyLabel("同时处理几个任务（1~8，建议 2~4）", card_conc))
        conc_col.addStretch(1)
        lc.addLayout(conc_col, 1)
        self.concCombo = ComboBox(card_conc)
        for i in range(1, 9):
            self.concCombo.addItem(str(i), userData=i)
        self.concCombo.setCurrentText(str(config.max_concurrent))
        self.concCombo.currentIndexChanged.connect(self._on_concurrent)
        lc.addWidget(self.concCombo, 0, Qt.AlignVCenter)
        root.addWidget(card_conc)

        # 完成后通知
        card_notify = CardWidget(self)
        ln = QHBoxLayout(card_notify)
        ln.setContentsMargins(16, 14, 16, 14)
        notify_col = QVBoxLayout()
        notify_col.addWidget(BodyLabel("全部完成后托盘通知", card_notify))
        notify_col.addWidget(BodyLabel("最小化到托盘时弹出完成气泡", card_notify))
        notify_col.addStretch(1)
        ln.addLayout(notify_col, 1)
        self.notifySwitch = SwitchButton(card_notify)
        self.notifySwitch.setChecked(config.notify_on_done)
        self.notifySwitch.checkedChanged.connect(self._on_notify)
        ln.addWidget(self.notifySwitch, 0, Qt.AlignVCenter)
        root.addWidget(card_notify)

        # 启动检查更新
        card_cu = CardWidget(self)
        lcu = QHBoxLayout(card_cu)
        lcu.setContentsMargins(16, 14, 16, 14)
        cu_col = QVBoxLayout()
        cu_col.addWidget(BodyLabel("启动时检查 FFmpeg 更新", card_cu))
        cu_col.addWidget(BodyLabel("有新版本时托盘提示", card_cu))
        cu_col.addStretch(1)
        lcu.addLayout(cu_col, 1)
        self.checkUpdateSwitch = SwitchButton(card_cu)
        self.checkUpdateSwitch.setChecked(config.check_update_on_start)
        self.checkUpdateSwitch.checkedChanged.connect(self._on_check_update)
        lcu.addWidget(self.checkUpdateSwitch, 0, Qt.AlignVCenter)
        root.addWidget(card_cu)

        # 外观主题
        card3 = CardWidget(self)
        l3 = QVBoxLayout(card3)
        l3.setContentsMargins(16, 14, 16, 14)
        l3.setSpacing(8)
        l3.addWidget(BodyLabel("外观主题", card3))
        self.themeCombo = ComboBox(card3)
        self.themeCombo.addItems(["跟随系统", "浅色", "深色"])
        self.themeCombo.setCurrentIndex(config.theme)
        self.themeCombo.currentIndexChanged.connect(self._on_theme)
        l3.addWidget(self.themeCombo)
        root.addWidget(card3)

        # 主题色
        card4 = CardWidget(self)
        l4 = QVBoxLayout(card4)
        l4.setContentsMargins(16, 14, 16, 14)
        l4.setSpacing(10)
        l4.addWidget(BodyLabel("主题色", card4))
        row4 = QHBoxLayout()
        row4.setSpacing(10)
        for c in PRESET_COLORS:
            btn = QToolButton(card4)
            btn.setFixedSize(30, 30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QToolButton{{background:{c};border-radius:15px;border:none;}}"
                f"QToolButton:hover{{border:2px solid rgba(128,128,128,150);}}")
            btn.setToolTip(c)
            btn.clicked.connect(lambda _=False, col=c: self._set_color(col))
            row4.addWidget(btn)
        sysBtn = PushButton("跟随系统", card4)
        sysBtn.clicked.connect(self._set_system_color)
        row4.addWidget(sysBtn)
        row4.addStretch(1)
        l4.addLayout(row4)
        root.addWidget(card4)

        # FFmpeg 引擎版本
        card_ff = CardWidget(self)
        lff = QVBoxLayout(card_ff)
        lff.setContentsMargins(16, 14, 16, 14)
        lff.setSpacing(8)
        lff.addWidget(BodyLabel("FFmpeg 引擎"))
        self.ffVerLabel = BodyLabel(f"当前版本：{ffmpeg_version() or '未检测到'}")
        lff.addWidget(self.ffVerLabel)
        self.ffCheckBtn = PushButton("检查更新", card_ff)
        self.ffCheckBtn.clicked.connect(self._check_ffmpeg_update)
        lff.addWidget(self.ffCheckBtn)
        self.ffUpdateLabel = CaptionLabel("")
        lff.addWidget(self.ffUpdateLabel)
        root.addWidget(card_ff)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择输出目录",
            config.out_dir or os.path.expanduser("~"))
        if d:
            config.out_dir = d
            self.outEdit.setText(d)
            config.save()

    def _reset_dir(self):
        config.out_dir = ""
        self.outEdit.setText("（与源文件相同）")
        config.save()

    def _on_encode(self, idx):
        config.encode_mode = "h264" if idx == 0 else "copy"
        config.save()

    def _on_quality(self, idx):
        config.quality = ["fast", "balanced", "high"][idx]
        config.save()

    def _on_format(self, idx):
        config.out_format = ["mp4", "mkv", "webm", "mp3"][idx]
        config.save()

    def _on_shutdown(self, checked):
        config.shutdown_after_done = checked
        config.save()

    def _on_hw(self, checked):
        config.hw_accel = checked
        config.save()

    def _on_mouse(self, checked):
        config.record_draw_mouse = checked
        config.save()

    def _on_concurrent(self, idx):
        config.max_concurrent = self.concCombo.itemData(idx) or 2
        config.save()

    def _on_notify(self, checked):
        config.notify_on_done = checked
        config.save()

    def _on_check_update(self, checked):
        config.check_update_on_start = checked
        config.save()

    def _on_theme(self, idx):
        theme = [Theme.AUTO, Theme.LIGHT, Theme.DARK][idx]
        setTheme(theme)
        config.theme = idx
        config.save()

    def _set_color(self, c):
        config.theme_color = c
        setThemeColor(QColor(c), save=False)
        config.save()

    def _set_system_color(self):
        c = read_system_accent()
        if c:
            config.theme_color = "system"
            setThemeColor(c, save=False)
            config.save()

    def _check_ffmpeg_update(self):
        """后台请求 gyan.dev 最新版本，避免阻塞 UI。"""
        self.ffCheckBtn.setEnabled(False)
        self.ffUpdateLabel.setText("正在检查 gyan.dev…")

        def worker():
            latest = latest_ffmpeg_version()
            QTimer.singleShot(0, lambda: self._show_update_result(latest))

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_result(self, latest):
        self.ffCheckBtn.setEnabled(True)
        current = ffmpeg_version()
        if not latest:
            self.ffUpdateLabel.setText("检查失败（网络不可达）")
            return
        if version_tuple(current) >= version_tuple(latest):
            self.ffUpdateLabel.setText(f"已是最新版本（{latest}）")
        else:
            self.ffUpdateLabel.setText(f"有新版本 {latest}，请到 gyan.dev 下载替换")
