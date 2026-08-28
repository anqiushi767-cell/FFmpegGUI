"""录屏设置弹窗：帧率、鼠标光标、硬件加速、音源。"""
from PySide6.QtWidgets import QHBoxLayout
from qfluentwidgets import (Dialog, BodyLabel, CaptionLabel, ComboBox,
                            SwitchButton)

from converter import list_audio_devices


class RecordDialog(Dialog):
    """录制前选择设置，确认后开始。"""

    def __init__(self, config, parent=None):
        super().__init__("屏幕录制", "选择录制设置，确认后开始", parent)
        self._config = config
        self._build()

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
        devs = list_audio_devices()
        for dev in devs:
            self.audioCombo.addItem(dev, userData=dev)
        self.textLayout.addWidget(self.audioCombo)
        if not devs:
            self.textLayout.addWidget(CaptionLabel(
                "未检测到音频输入设备（麦克风/立体声混音）"))

        # 输出目录提示
        out = self._config.out_dir or "系统视频文件夹"
        self.textLayout.addWidget(CaptionLabel(f"输出目录：{out}"))

        self.yesButton.setText("开始录制")

    def values(self):
        return {
            "fps": self.fpsCombo.currentData(),
            "draw_mouse": self.mouseSwitch.isChecked(),
            "hw_accel": self.hwSwitch.isChecked(),
            "audio": self.audioCombo.currentData() or "",
        }
