"""FFmpeg 转码器入口：GD 风主窗口 + 系统托盘（关闭最小化到托盘）。"""
import sys
import threading
from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from qfluentwidgets import (MSFluentWindow, FluentIcon, NavigationItemPosition,
                            setTheme, setThemeColor, Theme, MessageBox, CheckBox,
                            Action, RoundMenu)

from config import config
from converter import ffmpeg_version, latest_ffmpeg_version, version_tuple
from task_page import TaskPage
from settings_page import SettingsPage
from about_page import AboutPage


def apply_theme_color():
    """按配置应用主题色（预设色或跟随 Windows 强调色）。"""
    if config.theme_color == "system":
        from settings_page import read_system_accent
        c = read_system_accent()
        if c:
            setThemeColor(c, save=False)
    elif config.theme_color:
        setThemeColor(QColor(config.theme_color), save=False)


def make_tray_icon():
    """画一个简易托盘图标：圆角蓝方块 + 白色播放三角（等正式图标做好再换）。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#0078D4"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setBrush(QColor("white"))
    tri = QPolygonF([QPointF(26, 20), QPointF(44, 32), QPointF(26, 44)])
    p.drawPolygon(tri)
    p.end()
    return QIcon(pm)


class TrayRoundMenu(RoundMenu):
    """GD 同款托盘圆角菜单：托盘在屏幕角落，弹出前校正位置防超出屏幕。"""

    def showEvent(self, event):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = min(self.x(), geo.right() - self.width() + 1)
            y = min(self.y(), geo.bottom() - self.height() + 1)
            self.move(max(x, geo.left()), max(y, geo.top()))
        super().showEvent(event)


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FFmpeg 转码器")
        self.resize(980, 580)
        self.setMinimumSize(780, 500)
        self.tray = None
        self._allow_quit = False
        self._ask_open = False  # 关闭询问弹窗防重入（避免叠加模态→按钮失灵/咚音）

        self.taskPage = TaskPage(self)
        self.taskPage.setObjectName("taskPage")
        self.settingsPage = SettingsPage(self)
        self.settingsPage.setObjectName("settingsPage")
        self.aboutPage = AboutPage(self)
        self.aboutPage.setObjectName("aboutPage")

        self.addSubInterface(self.taskPage, FluentIcon.DOWNLOAD, "转码任务")
        self.addSubInterface(self.settingsPage, FluentIcon.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.aboutPage, FluentIcon.INFO, "关于",
                             position=NavigationItemPosition.BOTTOM)

        # 恢复上次的任务列表
        self.taskPage.load_tasks()

    def closeEvent(self, e):
        if self._allow_quit or not self.tray:
            self.taskPage.save_tasks(force=True)
            e.accept()
            return
        e.ignore()
        if self._ask_open:
            return  # 询问弹窗已打开，忽略重复关闭事件（防模态叠加→按钮失灵）
        if config.close_mode == "quit":
            self._really_quit()
            return
        if config.close_mode == "background":
            self._go_tray()
            return
        # GD 同款关闭弹窗：MessageBox + 两个按钮 + 记住选择
        self._ask_open = True
        try:
            dialog = MessageBox("是否完全退出程序？",
                                "后台运行时可通过系统托盘图标重新打开。", self)
            dialog.yesButton.setText("退出程序")
            dialog.cancelButton.setText("继续在后台运行")
            checkbox = CheckBox("记住我的选择", dialog)
            dialog.textLayout.addWidget(checkbox)
            mode = "quit" if dialog.exec() else "background"
        finally:
            self._ask_open = False
        if checkbox.isChecked():
            config.close_mode = mode
            config.save()
        if mode == "quit":
            self._really_quit()
        else:
            self._go_tray()

    def _go_tray(self):
        self.hide()

    def _really_quit(self):
        self.taskPage.cancel_all()  # 停止转码，避免卡住/孤儿 ffmpeg
        self.taskPage.save_tasks(force=True)
        self._allow_quit = True
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关窗不退出，托盘常驻
    setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][config.theme])
    apply_theme_color()
    w = MainWindow()

    # 系统托盘
    tray = QSystemTrayIcon(make_tray_icon(), w)
    tray.setToolTip("FFmpeg 转码器")

    def show_main():
        w.show()
        w.raise_()
        w.activateWindow()

    def do_quit():
        w._really_quit()

    menu = TrayRoundMenu()
    menu.addAction(Action(FluentIcon.HOME, "显示主窗口", menu,
                          triggered=show_main))
    menu.addSeparator()
    record_act = Action(FluentIcon.VIDEO, "屏幕录制", menu,
                        triggered=w.taskPage.toggle_recording)
    menu.addAction(record_act)
    menu.addAction(Action(FluentIcon.PLAY, "开始转码", menu,
                          triggered=lambda: (w.taskPage.start_all(), show_main())))
    menu.addSeparator()
    menu.addAction(Action(FluentIcon.CLOSE, "退出", menu, triggered=do_quit))

    # 弹出菜单前同步录制状态（录制中则显示"停止录制"）
    def sync_menu():
        if w.taskPage.recording_tid:
            record_act.setText("停止录制")
            record_act.setIcon(FluentIcon.PAUSE)
        else:
            record_act.setText("屏幕录制")
            record_act.setIcon(FluentIcon.VIDEO)

    menu.aboutToShow.connect(sync_menu)
    tray.setContextMenu(menu)

    # 托盘左键单击 / 双击都打开主窗口
    def on_tray_activated(reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            show_main()

    tray.activated.connect(on_tray_activated)
    tray.show()
    w.tray = tray

    # 全部完成时的托盘通知（设置项可关）
    w.taskPage._all_done_cb = lambda: tray.showMessage(
        "转码完成", "所有任务已处理完毕",
        QSystemTrayIcon.Information, 3000)

    # 开机自启（--tray）：静默启动到托盘，不弹主窗口
    if "--tray" not in sys.argv:
        w.show()

    # 启动后静默检查 ffmpeg 更新（后台线程，不阻塞启动）
    def check_ffmpeg_update():
        try:
            cur = ffmpeg_version()
            latest = latest_ffmpeg_version()
            if cur and latest and version_tuple(cur) < version_tuple(latest):
                QTimer.singleShot(0, lambda: tray.showMessage(
                    "FFmpeg 有更新",
                    f"当前 {cur}，最新 {latest}，可到「设置」页查看",
                    QSystemTrayIcon.Information, 5000))
        except Exception:
            pass  # 静默失败，不打扰用户

    QTimer.singleShot(3000, lambda: (
        threading.Thread(target=check_ffmpeg_update, daemon=True).start()
        if config.check_update_on_start else None))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
