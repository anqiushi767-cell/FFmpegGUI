"""转码任务页：命令栏 + 分段筛选 + 任务卡片列表 + 全局进度 Toast + 持久化。"""
import os
import json
import time
import subprocess
from PySide6.QtCore import Qt, QSize, QUrl, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
                               QFileDialog, QFrame, QGraphicsDropShadowEffect)
from PySide6.QtGui import QDesktopServices, QColor
from qfluentwidgets import (CommandBar, Action, FluentIcon, SegmentedToggleToolWidget,
                            InfoBar, InfoBarPosition, CardWidget, IconWidget,
                            BodyLabel, TitleLabel, ScrollArea, SmoothMode,
                            qconfig, Theme, ProgressBar, RoundMenu, Dialog,
                            ComboBox, LineEdit, CaptionLabel, PushButton)
from qfluentwidgets.components.widgets.command_bar import CommandButton

from converter import (Task, ConvertWorker, CREATE_NO_WINDOW,
                       KIND_CONVERT, KIND_TRIM, KIND_FRAME,
                       KIND_AUDIO, KIND_MUTE, KIND_NORM, KIND_GIF,
                       KIND_MERGE, KIND_SPEED, KIND_SHOT, KIND_STREAM,
                       KIND_META, KIND_SUBTITLE, KIND_RECORD, KIND_DELOGO,
                       parse_time)
from task_card import TaskCard
from trim_dialog import TrimDialog, fmt_clock
from delogo_dialog import DelogoDialog
from record_dialog import RecordDialog
from config import config

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".hlv", ".m4v",
              ".webm", ".wmv", ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp",
              ".rm", ".rmvb", ".vob", ".asf", ".mts"}

TASKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.json")


class GlobalToast(CardWidget):
    """右下角全局进度卡片（GD 同款 progress_toast：3px 条 + 16ms 0.25 缓动）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(270)
        self.setFixedHeight(58)  # 固定高度，避免文字/进度条被压扁折叠
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(7)
        self.label = BodyLabel("", self)
        self.label.setWordWrap(False)  # 单行，不换行不折叠
        v.addWidget(self.label)
        self.bar = ProgressBar(self)
        self.bar.setRange(0, 1000)          # 0.1% 精度，平滑填充
        self.bar.setFixedHeight(3)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self._target = 0.0
        self._current = 0.0
        # GD 笔记：16ms 定时器 + 0.25 缓动逼近目标值
        self._ani = QTimer(self)
        self._ani.setInterval(16)
        self._ani.timeout.connect(self._tick)
        self.hide()

    def update_state(self, done, total, percent):
        self.label.setText(f"{done}/{total} 已完成 · 总进度 {percent}%")
        self._target = float(percent)
        if not self._ani.isActive():
            self._ani.start()

    def _tick(self):
        diff = self._target - self._current
        if abs(diff) < 0.15:
            self._current = self._target
            self._ani.stop()
        else:
            self._current += diff * 0.25
        self.bar.setValue(int(self._current * 10))


class TaskPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks = {}
        self.cards = {}
        self.workers = {}
        self.pending = []
        self.running = set()
        self._speed_ts = {}
        self.filter = "全部任务"
        self.recording_tid = None  # 当前录制中的任务 id
        self._all_done_cb = None   # 全部完成时的托盘通知回调（由 main 设置）

        self._build()
        self.setAcceptDrops(True)

    # ---------- 构建 ----------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(14)

        # 命令栏
        self.cmdBar = CommandBar(self)
        self.addAction = Action(FluentIcon.ADD, "添加文件", self)
        self.startAction = Action(FluentIcon.PLAY, "开始转码", self)
        self.coverAction = Action(FluentIcon.CAMERA, "抽帧封面", self)
        self.recordAction = Action(FluentIcon.VIDEO, "屏幕录制", self)
        self.clearAction = Action(FluentIcon.DELETE, "清空已完成", self)
        self.addAction.triggered.connect(self._pick_files)
        self.startAction.triggered.connect(self.start_all)
        self.coverAction.triggered.connect(self.make_covers)
        self.recordAction.triggered.connect(self.toggle_recording)
        self.clearAction.triggered.connect(self.clear_done)
        self.cmdBar.addAction(self.addAction)
        self.cmdBar.addAction(self.startAction)
        self.cmdBar.addAction(self.coverAction)
        self.cmdBar.addAction(self.recordAction)

        # 「更多工具」下拉：提取音频 / 响度归一化 / 转 GIF
        self.cmdBar.addSeparator()
        moreBtn = CommandButton(self.cmdBar)
        moreBtn.setIcon(FluentIcon.MORE.icon())
        moreBtn.setText("更多")
        moreBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        moreBtn.clicked.connect(lambda: self._show_more_menu(moreBtn))
        self.cmdBar.addWidget(moreBtn)

        self.cmdBar.addSeparator()
        self.cmdBar.addAction(self.clearAction)
        # GD 同款命令栏投影：35px 模糊 + (0,8) 偏移，深色黑80/浅色黑30
        cmdShadow = QGraphicsDropShadowEffect(self.cmdBar)
        cmdShadow.setBlurRadius(35)
        cmdShadow.setOffset(0, 8)
        cmdShadow.setColor(QColor(0, 0, 0, 80 if qconfig.theme == Theme.DARK else 30))
        self.cmdBar.setGraphicsEffect(cmdShadow)
        root.addWidget(self.cmdBar)

        # 分段筛选（GD 同款三段：纯图标，悬停 tooltip 浮现文字）
        self.seg = SegmentedToggleToolWidget(self)
        for key, icon, tip in (
            ("全部任务", FluentIcon.VIEW, "全部任务"),
            ("正在进行", FluentIcon.PLAY, "正在进行"),
            ("已完成", FluentIcon.COMPLETED, "已完成"),
        ):
            item = self.seg.addItem(key, icon)
            item.setToolTip(tip)
        self.seg.currentItemChanged.connect(self._on_filter)
        root.addWidget(self.seg, 0, Qt.AlignLeft)

        # 任务列表 + 空状态（QStackedWidget 切换）
        self.stack = QStackedWidget(self)

        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setSmoothMode(SmoothMode.COSINE, Qt.Vertical)
        self.cardsHost = QWidget()
        self.cardsLayout = QVBoxLayout(self.cardsHost)
        self.cardsLayout.setContentsMargins(0, 0, 8, 0)
        self.cardsLayout.setSpacing(8)
        self.cardsLayout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.cardsHost)
        # 跟随主题背景（深色下不再透出浅色 viewport），GD 同款透明滚动区
        self.scroll.enableTransparentBackground()

        self.stack.addWidget(self.scroll)
        self.stack.addWidget(self._make_empty())
        root.addWidget(self.stack, 1)

        # 全局进度 Toast（右下角）
        self.toast = GlobalToast(self)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)

    def _make_empty(self):
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        icon = IconWidget(FluentIcon.DOWNLOAD, w)
        icon.setFixedSize(64, 64)
        lay.addWidget(icon, 0, Qt.AlignHCenter)
        lay.addWidget(TitleLabel("拖入视频文件开始转码"), 0, Qt.AlignHCenter)
        lay.addWidget(BodyLabel("支持 mp4 / mkv / flv / hlv 等格式，输出格式见设置"),
                      0, Qt.AlignHCenter)
        return w

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.toast.move(self.width() - self.toast.width() - 24,
                        self.height() - self.toast.height() - 24)

    # ---------- 文件添加 ----------
    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", os.path.expanduser("~"),
            "视频文件 (*.mp4 *.mkv *.avi *.mov *.flv *.hlv *.m4v *.webm *.wmv "
            "*.ts *.m2ts *.mpg *.mpeg *.3gp);;所有文件 (*.*)")
        if files:
            self.add_files(files)

    @staticmethod
    def _collect_video_files(path):
        """目录递归查找视频文件；文件则返回自身（扩展名匹配时）。"""
        if os.path.isfile(path):
            return [path] if os.path.splitext(path)[1].lower() in VIDEO_EXTS else []
        if os.path.isdir(path):
            out = []
            try:
                for root, _dirs, files in os.walk(path):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
                            out.append(os.path.join(root, f))
            except Exception:
                pass
            return out
        return []

    def add_files(self, paths):
        # 展开目录：递归找视频文件（支持拖入文件夹）
        expanded = []
        for p in paths:
            if os.path.isdir(p):
                expanded.extend(self._collect_video_files(p))
            else:
                expanded.append(p)
        added = 0
        self.setUpdatesEnabled(False)  # 批量添加暂停重绘，避免逐个布局重算
        try:
            for p in expanded:
                if not os.path.isfile(p):
                    continue
                if os.path.splitext(p)[1].lower() not in VIDEO_EXTS:
                    continue
                t = Task(path=p, out_dir=config.resolve_out_dir(p),
                         encode_mode=config.encode_mode,
                         out_format=config.out_format,
                         quality=config.quality)
                self.tasks[t.id] = t
                card = TaskCard(t, on_open_file=self.open_file,
                                on_open_folder=self.open_folder,
                                on_delete=self.remove_task,
                                on_trim=self.show_trim_dialog, on_retry=self.retry_task)
                self.cards[t.id] = card
                self.cardsLayout.addWidget(card)
                added += 1
        finally:
            self.setUpdatesEnabled(True)
        if added:
            self._refresh()
            self.save_tasks()
            InfoBar.success("已添加", f"共添加 {added} 个文件",
                            duration=2000, position=InfoBarPosition.BOTTOM_RIGHT,
                            parent=self)

    # ---------- 任务操作 ----------
    def open_file(self, tid):
        """直接打开转出的文件。"""
        t = self.tasks.get(tid)
        if t and t.out_path and os.path.exists(t.out_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(t.out_path))

    def open_folder(self, tid):
        """在资源管理器中定位文件（explorer /select）。"""
        t = self.tasks.get(tid)
        if t and t.out_path and os.path.exists(t.out_path):
            subprocess.Popen(["explorer", "/select,",
                              os.path.normpath(t.out_path)],
                             creationflags=CREATE_NO_WINDOW)

    # ---------- 更多工具菜单 ----------
    def _show_more_menu(self, btn):
        menu = RoundMenu(parent=self)
        # Action(icon, text, parent, triggered=...) —— 回调必须用 keyword，
        # 第三位置参数是 parent（之前误传 lambda 导致点击即抛异常"点不动"）
        menu.addAction(Action(FluentIcon.MUSIC, "提取音频…", self,
                              triggered=self._extract_audio))
        menu.addAction(Action(FluentIcon.MUTE, "提取无声视频", self,
                              triggered=lambda: self._batch_kind(KIND_MUTE)))
        menu.addAction(Action(FluentIcon.VOLUME, "音量归一化（-16 LUFS）", self,
                              triggered=lambda: self._batch_kind(KIND_NORM)))
        menu.addAction(Action(FluentIcon.PHOTO, "转为 GIF 动图（用片段选择）", self,
                              triggered=self._make_gif))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.CONNECT, "合并视频…", self,
                              triggered=self._merge_videos))
        menu.addAction(Action(FluentIcon.MOVE, "变速…", self,
                              triggered=self._speed_batch))
        menu.addAction(Action(FluentIcon.VIDEO, "定点截图…", self,
                              triggered=self._shot_batch))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.DOWNLOAD, "下载 M3U8 / 流媒体…", self,
                              triggered=self._stream_download))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.EDIT, "编辑元数据（标题/封面）…", self,
                              triggered=self._edit_metadata))
        menu.addAction(Action(FluentIcon.FONT, "烧录字幕（srt/ass）…", self,
                              triggered=self._subtitle_burn))
        menu.addAction(Action(FluentIcon.ERASE_TOOL, "去水印（框选区域）…", self,
                              triggered=self._delogo))
        # 延迟一帧再弹出：避免在 clicked 信号处理中弹模态菜单
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        QTimer.singleShot(0, lambda: menu.exec(pos))

    def _batch_kind(self, kind, tag="", extra=None):
        """为所有 pending/done 的视频任务生成指定类型的子任务。"""
        suffix = {"audio": "_音频", "normalize": "_响度归一"}.get(kind, "")
        targets = [t for t in self.tasks.values()
                   if t.kind in (KIND_CONVERT, KIND_TRIM, KIND_FRAME)
                   and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可处理视频", "先添加视频文件或等待转码完成",
                         duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        added = 0
        for src in targets:
            kw = dict(path=src.path, out_dir=src.out_dir,
                      encode_mode=src.encode_mode if kind == KIND_NORM else "copy",
                      out_format=src.out_format, quality=config.quality,
                      kind=kind)
            if extra:
                kw.update(extra)
            sub = Task(**kw)
            self.tasks[sub.id] = sub
            card = TaskCard(sub, on_open_file=self.open_file,
                            on_open_folder=self.open_folder,
                            on_delete=self.remove_task,
                            on_trim=self.show_trim_dialog, on_retry=self.retry_task)
            self.cards[sub.id] = card
            self.cardsLayout.addWidget(card)
            self.pending.append(sub.id)
            added += 1
        self._refresh()
        self.save_tasks()
        self.start_all()
        if added:
            InfoBar.success("已添加", f"生成 {added} 个任务，开始处理",
                            duration=2000, position=InfoBarPosition.BOTTOM_RIGHT,
                            parent=self)

    def _extract_audio(self):
        """提取音频：弹窗选格式（MP3/FLAC/WAV/AAC）。"""
        dlg = Dialog("提取音频", "选择音频格式", self)
        combo = ComboBox(dlg)
        fmt_label = {"mp3": "MP3（通用有损，体积小）",
                     "flac": "FLAC（无损）",
                     "wav": "WAV（无损，未压缩）",
                     "aac": "AAC（m4a，高质量）"}
        for fmt in ("mp3", "flac", "wav", "aac"):
            combo.addItem(fmt_label[fmt], userData=fmt)
        dlg.textLayout.addWidget(combo)
        dlg.yesButton.setText("提取")
        if not dlg.exec():
            return
        fmt = combo.currentData() or "mp3"
        self._batch_kind(KIND_AUDIO, extra={"audio_format": fmt})

    def _make_gif(self):
        """GIF：先选一个源视频（复用片段选择弹窗定范围）。"""
        targets = [t for t in self.tasks.values()
                   if t.kind != KIND_GIF and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可转换视频", "先添加视频文件",
                         duration=2000, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        src = targets[0]
        dlg = TrimDialog(src.name, src.duration, self)
        dlg.setWindowTitle("转 GIF")
        if not dlg.exec():
            return
        s, e = dlg.get_times()
        sub = Task(path=src.path, out_dir=config.resolve_out_dir(src.path),
                   encode_mode="copy", kind=KIND_GIF,
                   trim_start=s, trim_end=e)
        self.tasks[sub.id] = sub
        card = TaskCard(sub, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[sub.id] = card
        self.cardsLayout.addWidget(card)
        self._refresh()
        self.save_tasks()
        self.pending.append(sub.id)
        self._pump()
        self._update_toast()
        InfoBar.success("GIF 任务已添加",
                        f"{fmt_clock(s)} → {fmt_clock(e)}",
                        duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                        parent=self)

    # ---------- 截取片段 ----------
    def show_trim_dialog(self, tid):
        t = self.tasks.get(tid)
        if not t:
            return
        if t.status == "running":
            InfoBar.warning("正在转码", "等这个任务转完再截取",
                            duration=2000, position=InfoBarPosition.BOTTOM_RIGHT,
                            parent=self)
            return
        dlg = TrimDialog(t.name, t.duration, self)
        if not dlg.exec():
            return
        s, e = dlg.get_times()
        sub = Task(path=t.path, out_dir=config.resolve_out_dir(t.path),
                   encode_mode=config.encode_mode,
                   out_format=config.out_format, quality=config.quality,
                   kind=KIND_TRIM, trim_start=s, trim_end=e)
        self.tasks[sub.id] = sub
        card = TaskCard(sub, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[sub.id] = card
        self.cardsLayout.addWidget(card)
        self._refresh()
        self.save_tasks()
        # 片段任务直接开转
        self.pending.append(sub.id)
        self._pump()
        self._update_toast()

    # ---------- 抽帧封面 ----------
    def make_covers(self):
        """为列表里所有视频任务各生成一张封面 PNG，自动开始。"""
        targets = [tid for tid, t in self.tasks.items()
                   if t.kind != KIND_FRAME and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可抽帧视频", "先添加视频文件",
                         duration=2000, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        added = 0
        for tid in targets:
            src = self.tasks[tid]
            cover = Task(path=src.path, out_dir=src.out_dir,
                         encode_mode="copy", kind=KIND_FRAME)
            self.tasks[cover.id] = cover
            card = TaskCard(cover, on_open_file=self.open_file,
                            on_open_folder=self.open_folder,
                            on_delete=self.remove_task,
                            on_trim=self.show_trim_dialog, on_retry=self.retry_task)
            self.cards[cover.id] = card
            self.cardsLayout.addWidget(card)
            self.pending.append(cover.id)
            added += 1
        self._refresh()
        self.save_tasks()
        self._pump()
        self._update_toast()

    # ---------- 合并视频 ----------
    def _merge_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要合并的视频（按顺序）", os.path.expanduser("~"),
            "视频文件 (*.mp4 *.mkv *.avi *.mov *.flv *.hlv *.m4v *.webm "
            "*.ts *.m2ts);;所有文件 (*.*)")
        files = [f for f in files if os.path.isfile(f)]
        if len(files) < 2:
            InfoBar.info("合并视频", "至少选择 2 个视频文件",
                         duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        first = files[0]
        sub = Task(path=first, out_dir=config.resolve_out_dir(first),
                   encode_mode=config.encode_mode,
                   out_format=config.out_format, quality=config.quality,
                   kind=KIND_MERGE, merge_paths=files)
        sub.name = f"合并 {len(files)} 个视频"
        self.tasks[sub.id] = sub
        card = TaskCard(sub, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[sub.id] = card
        self.cardsLayout.addWidget(card)
        self._refresh()
        self.save_tasks()
        self.pending.append(sub.id)
        self._pump()
        self._update_toast()

    # ---------- 变速 ----------
    def _speed_batch(self):
        targets = [t for t in self.tasks.values()
                   if t.kind in (KIND_CONVERT, KIND_TRIM)
                   and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可变速视频", "先添加视频文件或等待转码完成",
                         duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        dlg = Dialog("变速", "选择倍速（变速后音画同步，音频 atempo 处理）",
                     self)
        combo = ComboBox(dlg)
        combo.addItems(["0.5x（慢放）", "0.75x（慢放）", "1.25x（快进）",
                        "1.5x（快进）", "2.0x（快进）"])
        combo.setCurrentIndex(2)
        dlg.textLayout.addWidget(combo)
        dlg.yesButton.setText("生成任务")
        if not dlg.exec():
            return
        rate = [0.5, 0.75, 1.25, 1.5, 2.0][combo.currentIndex()]
        added = 0
        for src in targets:
            sub = Task(path=src.path, out_dir=config.resolve_out_dir(src.path),
                       encode_mode="h264", out_format=config.out_format,
                       quality=config.quality, kind=KIND_SPEED,
                       speed_rate=rate, hw_accel=config.hw_accel)
            self.tasks[sub.id] = sub
            card = TaskCard(sub, on_open_file=self.open_file,
                            on_open_folder=self.open_folder,
                            on_delete=self.remove_task,
                            on_trim=self.show_trim_dialog, on_retry=self.retry_task)
            self.cards[sub.id] = card
            self.cardsLayout.addWidget(card)
            self.pending.append(sub.id)
            added += 1
        self._refresh()
        self.save_tasks()
        self._pump()
        self._update_toast()

    # ---------- 定点截图 ----------
    def _shot_batch(self):
        targets = [t for t in self.tasks.values()
                   if t.kind in (KIND_CONVERT, KIND_TRIM)
                   and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可截图视频", "先添加视频文件或等待转码完成",
                         duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        dlg = Dialog("定点截图", "输入截图时间点（如 1:30 或 90），"
                                "为每个视频在该时刻抽一帧", self)
        edit = LineEdit(dlg)
        edit.setPlaceholderText("0:30")
        dlg.textLayout.addWidget(edit)
        dlg.yesButton.setText("生成任务")
        if not dlg.exec():
            return
        t = parse_time(edit.text())
        if t < 0:
            InfoBar.error("时间格式不对", "示例：1:30 或 90",
                          duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                          parent=self)
            return
        added = 0
        for src in targets:
            sub = Task(path=src.path, out_dir=config.resolve_out_dir(src.path),
                       encode_mode="copy", kind=KIND_SHOT, shot_time=t)
            self.tasks[sub.id] = sub
            card = TaskCard(sub, on_open_file=self.open_file,
                            on_open_folder=self.open_folder,
                            on_delete=self.remove_task,
                            on_trim=self.show_trim_dialog, on_retry=self.retry_task)
            self.cards[sub.id] = card
            self.cardsLayout.addWidget(card)
            self.pending.append(sub.id)
            added += 1
        self._refresh()
        self.save_tasks()
        self._pump()
        self._update_toast()

    # ---------- 流媒体下载 ----------
    def _stream_download(self):
        dlg = Dialog("下载流媒体", "输入 m3u8 / 流媒体地址（B 站直播、网页视频等）",
                     self)
        url_edit = LineEdit(dlg)
        url_edit.setPlaceholderText("https://example.com/index.m3u8")
        dlg.textLayout.addWidget(BodyLabel("地址"))
        dlg.textLayout.addWidget(url_edit)
        name_edit = LineEdit(dlg)
        name_edit.setPlaceholderText("输出文件名（可选）")
        dlg.textLayout.addWidget(BodyLabel("文件名"))
        dlg.textLayout.addWidget(name_edit)
        dlg.yesButton.setText("开始下载")
        if not dlg.exec():
            return
        url = url_edit.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            InfoBar.error("地址无效", "需以 http/https 开头",
                          duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                          parent=self)
            return
        name = name_edit.text().strip()
        if not name:
            seg = url.rstrip("/").split("/")[-1].split("?")[0]
            name = os.path.splitext(seg)[0] if seg else "下载视频"
        name = os.path.splitext(name)[0] or "下载视频"
        out_dir = config.out_dir or os.path.join(os.path.expanduser("~"),
                                                 "Downloads")
        sub = Task(path=url, out_dir=out_dir, encode_mode="copy",
                   kind=KIND_STREAM, stream_url=url)
        sub.name = name
        self.tasks[sub.id] = sub
        card = TaskCard(sub, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[sub.id] = card
        self.cardsLayout.addWidget(card)
        self._refresh()
        self.save_tasks()
        self.pending.append(sub.id)
        self._pump()
        self._update_toast()

    # ---------- 元数据编辑 ----------
    def _edit_metadata(self):
        targets = [t for t in self.tasks.values()
                   if t.kind in (KIND_CONVERT, KIND_TRIM)
                   and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可编辑视频", "先添加视频文件或等待转码完成",
                         duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        dlg = Dialog("编辑元数据", "为视频设置标题 / 嵌入封面图", self)
        dlg.textLayout.addWidget(BodyLabel("目标视频"))
        combo = ComboBox(dlg)
        for t in targets:
            combo.addItem(t.name, userData=t.id)
        dlg.textLayout.addWidget(combo)

        dlg.textLayout.addWidget(BodyLabel("标题（可选）"))
        title_edit = LineEdit(dlg)
        title_edit.setPlaceholderText("留空不修改标题")
        dlg.textLayout.addWidget(title_edit)

        dlg.textLayout.addWidget(BodyLabel("封面图（可选，jpg/png）"))
        cover_row = QHBoxLayout()
        cover_edit = LineEdit(dlg)
        cover_edit.setReadOnly(True)
        cover_row.addWidget(cover_edit, 1)
        browse = PushButton("选择图片", dlg)
        cover_row.addWidget(browse)
        dlg.textLayout.addLayout(cover_row)

        def pick_cover():
            f, _ = QFileDialog.getOpenFileName(
                dlg, "选择封面图", os.path.expanduser("~"),
                "图片 (*.jpg *.jpeg *.png *.bmp)")
            if f:
                cover_edit.setText(f)

        browse.clicked.connect(pick_cover)
        dlg.yesButton.setText("生成任务")
        if not dlg.exec():
            return
        tid = combo.currentData()
        src = self.tasks.get(tid)
        if not src:
            return
        sub = Task(path=src.path, out_dir=src.out_dir, encode_mode="copy",
                   kind=KIND_META,
                   metadata_title=title_edit.text().strip(),
                   cover_path=cover_edit.text().strip())
        self.tasks[sub.id] = sub
        card = TaskCard(sub, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[sub.id] = card
        self.cardsLayout.addWidget(card)
        self._refresh()
        self.save_tasks()
        self.pending.append(sub.id)
        self._pump()
        self._update_toast()

    # ---------- 字幕烧录 ----------
    def _subtitle_burn(self):
        targets = [t for t in self.tasks.values()
                   if t.kind in (KIND_CONVERT, KIND_TRIM)
                   and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可烧录视频", "先添加视频文件或等待转码完成",
                         duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        dlg = Dialog("烧录字幕", "将外挂字幕（srt/ass）烧进视频画面", self)
        dlg.textLayout.addWidget(BodyLabel("目标视频"))
        combo = ComboBox(dlg)
        for t in targets:
            combo.addItem(t.name, userData=t.id)
        dlg.textLayout.addWidget(combo)

        dlg.textLayout.addWidget(BodyLabel("字幕文件（srt/ass/ssa/vtt）"))
        sub_row = QHBoxLayout()
        sub_edit = LineEdit(dlg)
        sub_edit.setReadOnly(True)
        sub_row.addWidget(sub_edit, 1)
        browse = PushButton("选择字幕", dlg)
        sub_row.addWidget(browse)
        dlg.textLayout.addLayout(sub_row)

        def pick():
            f, _ = QFileDialog.getOpenFileName(
                dlg, "选择字幕文件", os.path.expanduser("~"),
                "字幕 (*.srt *.ass *.ssa *.vtt);;所有文件 (*.*)")
            if f:
                sub_edit.setText(f)

        browse.clicked.connect(pick)
        dlg.yesButton.setText("生成任务")
        if not dlg.exec():
            return
        sub_path = sub_edit.text().strip()
        if not sub_path or not os.path.isfile(sub_path):
            InfoBar.error("未选字幕", "请先选择字幕文件",
                          duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                          parent=self)
            return
        tid = combo.currentData()
        src = self.tasks.get(tid)
        if not src:
            return
        sub = Task(path=src.path, out_dir=src.out_dir, encode_mode="h264",
                   out_format="mp4", quality=config.quality,
                   kind=KIND_SUBTITLE, subtitle_path=sub_path,
                   hw_accel=config.hw_accel)
        self.tasks[sub.id] = sub
        card = TaskCard(sub, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[sub.id] = card
        self.cardsLayout.addWidget(card)
        self._refresh()
        self.save_tasks()
        self.pending.append(sub.id)
        self._pump()
        self._update_toast()

    # ---------- 去水印 ----------
    def _delogo(self):
        targets = [t for t in self.tasks.values()
                   if t.kind in (KIND_CONVERT, KIND_TRIM)
                   and t.status in ("pending", "done")]
        if not targets:
            InfoBar.info("无可去水印视频", "先添加视频文件或等待转码完成",
                         duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        src = targets[0]
        if len(targets) > 1:
            dlg = Dialog("去水印", "选择要去水印的视频", self)
            combo = ComboBox(dlg)
            for t in targets:
                combo.addItem(t.name, userData=t.id)
            dlg.textLayout.addWidget(combo)
            dlg.yesButton.setText("下一步")
            if not dlg.exec():
                return
            src = self.tasks.get(combo.currentData())
            if not src:
                return
        dd = DelogoDialog(src.name, src.path, self)
        if not dd.exec():
            return
        region = dd.region_str
        if not region:
            return
        sub = Task(path=src.path, out_dir=src.out_dir, encode_mode="h264",
                   out_format="mp4", quality=config.quality,
                   kind=KIND_DELOGO, delogo_region=region,
                   hw_accel=config.hw_accel)
        self.tasks[sub.id] = sub
        card = TaskCard(sub, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[sub.id] = card
        self.cardsLayout.addWidget(card)
        self._refresh()
        self.save_tasks()
        self.pending.append(sub.id)
        self._pump()
        self._update_toast()

    def remove_task(self, tid):
        card = self.cards.pop(tid, None)
        if card:
            card.deleteLater()
        self.tasks.pop(tid, None)
        self.running.discard(tid)
        self._refresh()
        self._update_toast()
        self.save_tasks()

    def retry_task(self, tid):
        """单个任务重试：失败任务重置为等待并重新入队。"""
        t = self.tasks.get(tid)
        if not t or t.status == "running":
            return
        t.status = "pending"
        t.percent = 0
        t.speed = ""
        t.eta = ""
        t.error = ""
        if tid in self.cards:
            self.cards[tid].refresh()
        if tid not in self.pending:
            self.pending.append(tid)
        self._pump()
        self._update_toast()
        self.save_tasks()

    def start_all(self):
        self.pending = [tid for tid, t in self.tasks.items()
                        if t.status in ("pending", "error")]
        if not self.pending:
            InfoBar.info("无任务", "没有待转码的任务",
                         duration=2000, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        self._pump()
        self._update_toast()

    def cancel_all(self):
        """停止所有运行中的任务（退出程序时用）。"""
        ws = list(self.workers.values())
        for w in ws:
            if getattr(w.task, "kind", "") == KIND_RECORD:
                w.stop()   # 录制写 'q' 优雅退出（terminate 会卡 stdout 读取）
            else:
                w.cancel()
        for w in ws:
            w.wait(3000)  # 等线程收尾

    # ---------- 屏幕录制 ----------
    def toggle_recording(self):
        if self.recording_tid:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        dlg = RecordDialog(config, self)
        if not dlg.exec():
            return
        vals = dlg.values()
        out_dir = config.out_dir or os.path.join(os.path.expanduser("~"),
                                                 "Videos")
        t = Task(path="", out_dir=out_dir, encode_mode="h264",
                 kind=KIND_RECORD, hw_accel=vals["hw_accel"],
                 record_draw_mouse=vals["draw_mouse"],
                 record_fps=vals["fps"],
                 record_audio=vals["audio"])
        t.name = "屏幕录制"
        self.tasks[t.id] = t
        card = TaskCard(t, on_open_file=self.open_file,
                        on_open_folder=self.open_folder,
                        on_delete=self.remove_task,
                        on_trim=self.show_trim_dialog, on_retry=self.retry_task)
        self.cards[t.id] = card
        self.cardsLayout.addWidget(card)
        self.recording_tid = t.id
        self._start(t.id)
        self.recordAction.setText("停止录制")
        self.recordAction.setIcon(FluentIcon.PAUSE)
        self._refresh()
        InfoBar.info("开始录制", "点击「停止录制」结束，录屏保存到视频目录",
                     duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                     parent=self)

    def stop_recording(self):
        tid = self.recording_tid
        self.recording_tid = None
        w = self.workers.get(tid) if tid else None
        if w:
            w.stop()  # 写 'q' 优雅退出
        self.recordAction.setText("屏幕录制")
        self.recordAction.setIcon(FluentIcon.VIDEO)

    def _pump(self):
        while self.pending and len(self.running) < config.max_concurrent:
            tid = self.pending.pop(0)
            self.running.add(tid)
            self._start(tid)

    def _start(self, tid):
        t = self.tasks[tid]
        t.status = "running"
        t.percent = 0
        t.speed = ""
        w = ConvertWorker(t, all_tasks=self.tasks)
        self.workers[tid] = w
        w.progress.connect(self._on_progress)
        w.speed.connect(self._on_speed)
        w.status.connect(self._on_status)
        w.finished.connect(lambda tid=tid: self._on_worker_done(tid))
        w.start()
        self.cards[tid].refresh()

    def clear_done(self):
        done_ids = [tid for tid, t in self.tasks.items() if t.status == "done"]
        if not done_ids:
            InfoBar.info("无需清理", "没有已完成的任务",
                         duration=2000, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)
            return
        # 批量删除：避免逐个 remove_task 的 O(n²) 刷新与重复写盘
        self.setUpdatesEnabled(False)
        try:
            for tid in done_ids:
                card = self.cards.pop(tid, None)
                if card:
                    card.deleteLater()
                self.tasks.pop(tid, None)
        finally:
            self.setUpdatesEnabled(True)
        self._refresh()
        self.save_tasks()
        self._update_toast()

    # ---------- 持久化 ----------
    def save_tasks(self, force=False):
        """去抖写盘：合并高频调用，500ms 后统一写一次（force=True 立即写）。"""
        if force:
            self._save_tasks_now()
            return
        if not hasattr(self, "_save_timer"):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self._save_tasks_now)
        self._save_timer.start(500)

    def _save_tasks_now(self):
        try:
            with open(TASKS_PATH, "w", encoding="utf-8") as f:
                json.dump([t.to_dict() for t in self.tasks.values()],
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_tasks(self):
        try:
            with open(TASKS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        self.setUpdatesEnabled(False)  # 批量恢复卡片，暂停重绘
        try:
            for d in data:
                t = Task.from_dict(d)
                if t.kind == KIND_STREAM:
                    pass  # 流媒体 path 是 URL，不做本地文件检查
                elif not os.path.isfile(t.path):
                    continue  # 源文件已不存在
                if t.status in ("running", "pending"):
                    t.status = "pending"
                    t.percent = 0
                    t.speed = ""
                    t.error = ""
                self.tasks[t.id] = t
                card = TaskCard(t, on_open_file=self.open_file,
                                on_open_folder=self.open_folder,
                                on_delete=self.remove_task,
                                on_trim=self.show_trim_dialog, on_retry=self.retry_task)
                self.cards[t.id] = card
                self.cardsLayout.addWidget(card)
                card.refresh()
        finally:
            self.setUpdatesEnabled(True)
        self._refresh()

    # ---------- 全局 Toast ----------
    def _update_toast(self):
        if not self.tasks:
            self.toast.hide()
            return
        total = len(self.tasks)
        done = sum(1 for t in self.tasks.values()
                   if t.status in ("done", "error"))
        busy = any(t.status in ("pending", "running")
                   for t in self.tasks.values())
        if not busy:
            self.toast.update_state(done, total, 100)
            self.toast.show()
            self.toast.raise_()
            self._toast_timer.start(3000)
            return
        percent = sum(t.percent for t in self.tasks.values()) // total
        self.toast.update_state(done, total, percent)
        self.toast.show()
        self.toast.raise_()

    # ---------- 完成后关机 ----------
    def _check_shutdown(self):
        if not config.shutdown_after_done:
            return
        if not self.tasks or self.running or self.pending:
            return
        if not any(t.status == "done" for t in self.tasks.values()):
            return  # 没有成功完成的，不关机
        subprocess.run(["shutdown", "/s", "/t", "60"],
                       creationflags=CREATE_NO_WINDOW)
        InfoBar.warning("完成后关机", "全部任务已结束，60 秒后关机"
                        "（取消请运行 shutdown /a）",
                        duration=8000, position=InfoBarPosition.BOTTOM_RIGHT,
                        parent=self)
        config.shutdown_after_done = False  # 一次性触发
        config.save()

    # ---------- 信号槽 ----------
    def _on_progress(self, tid, pct):
        t = self.tasks.get(tid)
        if t:
            t.percent = pct
            if tid in self.cards:
                self.cards[tid].refresh()
            self._update_toast()

    def _on_speed(self, tid, speed):
        t = self.tasks.get(tid)
        if not t:
            return
        t.speed = speed
        # 速度刷新节流 200ms，避免高频全量刷新卡片
        now = time.monotonic()
        if now - self._speed_ts.get(tid, 0) >= 0.2:
            self._speed_ts[tid] = now
            if tid in self.cards:
                self.cards[tid].refresh()

    def _on_status(self, tid, status, extra):
        t = self.tasks.get(tid)
        if not t:
            return
        t.status = status
        # 录制结束（自然或停止）：恢复按钮状态
        if status in ("done", "error") and t.kind == KIND_RECORD:
            self.recording_tid = None
            self.recordAction.setText("屏幕录制")
            self.recordAction.setIcon(FluentIcon.VIDEO)
        if status == "done":
            t.out_path = extra
            self.cards[tid].refresh()
            InfoBar.success("转码完成", t.name, duration=2500,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        elif status == "error":
            t.error = extra
            self.cards[tid].refresh()
            InfoBar.error("转码失败", t.name + " — " + (extra[-120:] or ""),
                          duration=4000, position=InfoBarPosition.BOTTOM_RIGHT,
                          parent=self)
        else:
            self.cards[tid].refresh()
        self.save_tasks()
        self._update_toast()

    def _on_worker_done(self, tid):
        self.running.discard(tid)
        self.workers.pop(tid, None)
        self._pump()
        self._check_shutdown()
        # 全部完成时托盘通知（开关 config.notify_on_done）
        if (config.notify_on_done and self._all_done_cb
                and not self.running and not self.pending
                and any(t.status == "done" for t in self.tasks.values())):
            self._all_done_cb()

    def _on_filter(self, key):
        self.filter = key
        self._refresh()

    def _refresh(self):
        has_visible = False
        for tid, card in self.cards.items():
            t = self.tasks[tid]
            if self.filter == "正在进行":
                show = t.status in ("pending", "running")
            elif self.filter == "已完成":
                show = t.status == "done"
            else:
                show = True  # 全部任务（含失败）
            card.setVisible(show)
            if show:
                has_visible = True
        self.stack.setCurrentIndex(0 if self.tasks else 1)

    # ---------- 拖拽 ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.add_files(paths)
        # GD 行为：拖入即自动开始转码
        self.start_all()
