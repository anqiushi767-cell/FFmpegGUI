"""截取片段弹窗 v2：GD 同款双滑块 + 悬停预览（时间随拖动实时刷新）。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout
from qfluentwidgets import (Dialog, Slider, BodyLabel, CaptionLabel,
                            StrongBodyLabel, LineEdit)

from converter import parse_time


def fmt_clock(sec):
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class TrimDialog(Dialog):
    """双滑块选片段：拖动时大字实时预览起止时间和时长。"""

    RES = 100  # 滑块分辨率：0.01s 粒度

    def __init__(self, task_name, duration, parent=None):
        super().__init__("截取片段", task_name, parent)
        self.duration = duration or 0
        self.start_sec = -1
        self.end_sec = -1

        self.titleLabel.hide()
        if self.duration <= 0:
            # 探测不到时长时退化为输入框模式
            self._build_inputs()
            self.textLayout.addLayout(self.inputBox)
        else:
            self._build_sliders()
            self.textLayout.addLayout(self.sliderBox)

        self.yesButton.setText("添加任务")
        self.cancelButton.setText("取消")
        self.yesButton.clicked.connect(self._validate)
        self.resize(420, 260)

    # ---------- 双滑块模式 ----------
    def _build_sliders(self):
        self.sliderBox = QVBoxLayout()
        self.sliderBox.setSpacing(8)

        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        dur_text = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        cap = CaptionLabel(f"视频时长 {dur_text} · 拖动滑块选择片段")
        self.sliderBox.addWidget(cap)

        # 预览区：开始 — 时长 — 结束（拖动时实时刷新）
        prev = QGridLayout()
        prev.setSpacing(4)
        self.startPreview = StrongBodyLabel("0:00")
        self.lenPreview = StrongBodyLabel("0:00")
        self.endPreview = StrongBodyLabel(fmt_clock(self.duration))
        for col, (w, t) in enumerate(((self.startPreview, "开始"),
                                      (self.lenPreview, "片段长度"),
                                      (self.endPreview, "结束"))):
            box = QVBoxLayout()
            box.setAlignment(Qt.AlignHCenter)
            lab = CaptionLabel(t)
            lab.setAlignment(Qt.AlignHCenter)
            w.setAlignment(Qt.AlignHCenter)
            box.addWidget(w)
            box.addWidget(lab)
            prev.addLayout(box, 0, col)
        self.sliderBox.addLayout(prev)

        max_v = int(self.duration * self.RES)
        self.startSlider = Slider(Qt.Horizontal)
        self.startSlider.setRange(0, max_v)
        self.endSlider = Slider(Qt.Horizontal)
        self.endSlider.setRange(0, max_v)
        self.endSlider.setValue(max_v)
        self.sliderBox.addWidget(self.startSlider)
        self.sliderBox.addWidget(self.endSlider)

        row = QHBoxLayout()
        row.addWidget(CaptionLabel("◀ 开始"))
        row.addStretch(1)
        row.addWidget(CaptionLabel("结束 ▶"))
        self.sliderBox.addLayout(row)

        # 精调输入框（可选）
        fine = QHBoxLayout()
        fine.addWidget(CaptionLabel("精调："))
        self.startEdit = LineEdit()
        self.startEdit.setPlaceholderText("0:00")
        self.startEdit.setFixedWidth(90)
        self.endEdit = LineEdit()
        self.endEdit.setPlaceholderText(fmt_clock(self.duration))
        self.endEdit.setFixedWidth(90)
        fine.addWidget(self.startEdit)
        fine.addWidget(CaptionLabel("→"))
        fine.addWidget(self.endEdit)
        fine.addStretch(1)
        self.sliderBox.addLayout(fine)

        self.startSlider.valueChanged.connect(self._on_slider)
        self.endSlider.valueChanged.connect(self._on_slider)
        self._on_slider()

    def _on_slider(self):
        s = self.startSlider.value() / self.RES
        e = self.endSlider.value() / self.RES
        if s > e:  # 防交叉：谁在后面谁让路
            if self.startSlider.hasFocus() or self.startSlider.isSliderDown():
                e = s
                self.endSlider.setValue(int(e * self.RES))
            else:
                s = e
                self.startSlider.setValue(int(s * self.RES))
        self._s, self._e = s, e
        self.startPreview.setText(fmt_clock(s))
        self.endPreview.setText(fmt_clock(e))
        self.lenPreview.setText(fmt_clock(max(0, e - s)))
        # 同步精调框（不打断输入）
        if not self.startEdit.hasFocus():
            self.startEdit.setText(fmt_clock(s))
        if not self.endEdit.hasFocus():
            self.endEdit.setText(fmt_clock(e))

    # ---------- 无时长退化模式 ----------
    def _build_inputs(self):
        self.sliderBox = None
        self.inputBox = QVBoxLayout()
        self.inputBox.addWidget(CaptionLabel("无法读取视频时长，请手动输入时间"))
        row = QHBoxLayout()
        row.addWidget(BodyLabel("开始时间"))
        self.startEdit = LineEdit()
        self.startEdit.setPlaceholderText("1:30 或 90")
        row.addWidget(self.startEdit)
        row.addWidget(BodyLabel("结束（留空=结尾）"))
        self.endEdit = LineEdit()
        self.endEdit.setPlaceholderText("留空到结尾")
        row.addWidget(self.endEdit)
        self.inputBox.addLayout(row)
        self.hintLabel = CaptionLabel("")
        self.hintLabel.setStyleSheet("color:#C42B1C;")
        self.inputBox.addWidget(self.hintLabel)

    # ---------- 校验 ----------
    def _validate(self):
        if self.sliderBox is not None:
            s, e = getattr(self, "_s", 0), getattr(self, "_e", 0)
            # 输入框优先（用户手动改过）
            if self.startEdit.text().strip() and not self.startEdit.text().strip() == fmt_clock(getattr(self, '_s', 0)):
                ps = parse_time(self.startEdit.text())
                if ps >= 0:
                    s = min(ps, self.duration)
            if self.endEdit.text().strip() and not self.endEdit.text().strip() == fmt_clock(getattr(self, '_e', self.duration)):
                pe = parse_time(self.endEdit.text())
                if pe >= 0:
                    e = min(pe, self.duration)
            if e <= s:
                return
            self.start_sec, self.end_sec = s, e
        else:
            from converter import parse_time as _pt
            s = _pt(self.startEdit.text())
            e = (_pt(self.endEdit.text()) if self.endEdit.text().strip() else 0)
            if s < 0:
                self.hintLabel.setText("开始时间格式不对（示例：1:30 或 90）")
                return
            if e == 0 and self.duration > 0:
                e = self.duration
            if e <= s:
                self.hintLabel.setText("结束时间必须大于开始时间")
                return
            self.start_sec, self.end_sec = s, e
        self.accept()

    def get_times(self):
        return self.start_sec, self.end_sec
