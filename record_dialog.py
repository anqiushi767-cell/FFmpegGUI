"""录屏设置弹窗：帧率、鼠标光标、硬件加速、音源。"""
import threading
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout
from qfluentwidgets import (Dialog, BodyLabel, CaptionLabel, ComboBox,
                            SwitchButton)

from converter import list_audio_devices


class RecordDialog(Dialog):
    """录制前选择设置，确认后开始。"""

    devices_ready = Signal(list)  # 音源枚举结果（后台线程 → UI 线程）

    def __init__(self, config, parent=None):
        super().__init__("屏幕录制", "选择录制设置，确认后开始", parent)
        self._config = config
        self._build()
        # 枚举音源要跑 ffmpeg -list_devices（最坏 30s 超时），放后台线程，
        # 否则点开弹窗会整窗卡住
        self.devices_ready.connect(self._fill_audio_devices)
        threading.Thread(target=self._probe_audio_devices, daemon=True).start()

    def _probe_audio_devices(self):
        try:
            devs = list_audio_devices()
        except Exception:
            devs = []
        try:
            self.devices_ready.emit(devs)
        except RuntimeError:
            pass  # 弹窗已被销毁

    def _build(self):
        # 帧率
        self.textLayout.addWidget(BodyLabel("帧率"))
        self.fpsCombo = ComboBox(self)
        for f in (15, 24, 30, 60):
            self.fpsCombo.addItem(f"{f} fps", userData=f)
        self.fpsCombo.setCurrentText("30 fps")
        self.textLayout.addWidget(self.fpsCombo)

        # 鼠标光标
        row_m = QHBoxLayout()
        row_m.addWidget(BodyLabel("显示鼠标光标"))
        row_m.addStretch(1)
        self.mouseSwitch = SwitchButton(self)
        self.mouseSwitch.setChecked(self._config.record_draw_mouse)
        row_m.addWidget(self.mouseSwitch)
        self.textLayout.addLayout(row_m)

        # 硬件加速
        row_h = QHBoxLayout()
        row_h.addWidget(BodyLabel("硬件加速（NVENC）"))
        row_h.addStretch(1)
        self.hwSwitch = SwitchButton(self)
        self.hwSwitch.setChecked(self._config.hw_accel)
        row_h.addWidget(self.hwSwitch)
        self.textLayout.addLayout(row_h)

        # 音源（dshow 音频设备）
        self.textLayout.addWidget(BodyLabel("音源"))
        self.audioCombo = ComboBox(self)
        self.audioCombo.addItem("无声", userData="")
        self.textLayout.addWidget(self.audioCombo)
        self.deviceHint = CaptionLabel("正在检测音频输入设备…")
        self.textLayout.addWidget(self.deviceHint)

        # 输出目录提示
        out = self._config.out_dir or "系统视频文件夹"
        self.textLayout.addWidget(CaptionLabel(f"输出目录：{out}"))

        self.yesButton.setText("开始录制")

    def _fill_audio_devices(self, devs):
        """后台枚举完成后填充音源下拉（"无声"始终在第一项）。"""
        for dev in devs:
            self.audioCombo.addItem(dev, userData=dev)
        self.deviceHint.setText(f"已检测到 {len(devs)} 个音源" if devs
                                else "未检测到音频输入设备（麦克风/立体声混音）")

    def values(self):
        return {
            "fps": self.fpsCombo.currentData(),
            "draw_mouse": self.mouseSwitch.isChecked(),
            "hw_accel": self.hwSwitch.isChecked(),
            "audio": self.audioCombo.currentData() or "",
        }
