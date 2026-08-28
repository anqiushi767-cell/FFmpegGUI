"""托盘流程测试：模拟 main() 完整启动（托盘+窗口），3 秒后保存退出。"""
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import setTheme, Theme

from main import MainWindow, make_tray_icon, apply_theme_color

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
setTheme(Theme.DARK)
apply_theme_color()
w = MainWindow()
tray = QSystemTrayIcon(make_tray_icon(), w)
tray.setToolTip("FFmpeg 转码器")
tray.show()
w.tray = tray
w.show()
print("窗口+托盘创建成功，3 秒后退出")
QTimer.singleShot(3000, lambda: (w.taskPage.save_tasks(), app.quit()))
sys.exit(app.exec())
