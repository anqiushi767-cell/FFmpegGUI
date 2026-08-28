"""生成程序图标 app.ico：液态玻璃渐变圆角方块 + 白色播放三角。"""
import sys

sys.argv = ["t"]
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QImage, QPainter, QLinearGradient, QColor,
                           QPolygonF, QBrush, QPen)

SIZE = 256
img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
img.fill(Qt.transparent)

p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)

# 液态玻璃渐变背景（圆角方块）
grad = QLinearGradient(0, 0, SIZE, SIZE)
grad.setColorAt(0.0, QColor("#39C5BB"))
grad.setColorAt(1.0, QColor("#66CCFF"))
rect = QRectF(24, 24, SIZE - 48, SIZE - 48)
p.setBrush(QBrush(grad))
p.setPen(Qt.NoPen)
p.drawRoundedRect(rect, 56, 56)

# 白色播放三角
tri = QPolygonF([
    QPointF(100, 72),
    QPointF(100, 184),
    QPointF(188, 128),
])
p.setBrush(QBrush(QColor(255, 255, 255, 235)))
p.drawPolygon(tri)

p.end()

# 多尺寸保存
img.save("app.ico", "ICO")
print("已生成 app.ico")
