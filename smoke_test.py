"""GUI 冒烟测试：offscreen 模式构造整个主窗口，2 秒无异常即通过。"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from qfluentwidgets import setTheme, Theme

import main


app = QApplication(sys.argv)
setTheme(Theme.DARK)
w = main.MainWindow()
w.show()
QTimer.singleShot(2000, app.quit)
sys.exit(app.exec())
