"""Win11 窗口装饰：去掉 DWM 给窗口描的 1px 原生边框。

背景：qfluentwidgets 的无边框窗口（MSFluentWindow / Dialog / MessageBox）虽然已经去掉
系统标题栏（自绘 Fluent 标题栏），但 Win11 的 DWM 仍会给窗口描一圈 1px 浅色边框。
深色主题下尤其明显——表现为窗口最外圈一圈发白的细线，看着像"Windows 原生边框"。

这里用 DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE) 去掉这圈描边，
窗口阴影仍由 DWM 保留，不受影响。

该属性仅 Win11（build >= 22000）支持，其它系统静默跳过。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject

DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE


def is_win11() -> bool:
    """当前系统是否支持 DWM 边框颜色属性（Win11，build >= 22000）。"""
    try:
        return sys.platform == "win32" and sys.getwindowsversion().build >= 22000
    except Exception:
        return False


def remove_native_border(widget) -> bool:
    """去掉 widget 所在窗口的 DWM 原生描边，成功返回 True。"""
    if not is_win11():
        return False
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        value = ctypes.c_uint(DWMWA_COLOR_NONE)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), ctypes.c_int(DWMWA_BORDER_COLOR),
            ctypes.byref(value), ctypes.sizeof(value))
        return hr == 0
    except Exception:
        return False


class _NativeBorderFilter(QObject):
    """窗口显示 / 句柄变化 / 最大化还原时自动去掉原生描边。

    装在 QApplication 上，覆盖主窗口、各级对话框、弹出菜单等所有顶层窗口。
    """

    _TRIGGERS = (QEvent.Show, QEvent.WinIdChange, QEvent.WindowStateChange)

    def eventFilter(self, obj, event):
        try:
            if (event.type() in self._TRIGGERS
                    and obj.isWidgetType() and obj.isWindow()):
                remove_native_border(obj)
        except Exception:
            pass
        return False


def install_native_border_removal(app) -> bool:
    """给 QApplication 装过滤器，使之后所有窗口都不带原生描边。"""
    if not is_win11():
        return False
    try:
        f = _NativeBorderFilter(app)
        app.installEventFilter(f)
        app._native_border_filter = f  # 持引用，防止被 GC 回收
        return True
    except Exception:
        return False
