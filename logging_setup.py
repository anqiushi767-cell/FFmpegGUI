"""全局异常捕获 + 崩溃日志（写到程序目录，失败则 AppData）。"""
import logging
import os
import sys


def log_path():
    base = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    try:
        p = os.path.join(base, "ffmpegGUI.log")
        with open(p, "a", encoding="utf-8"):
            pass
        return p
    except OSError:
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                         "FFmpegGUI")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "ffmpegGUI.log")


def setup():
    """配置日志 + 全局异常钩子。在 main() 最开始调用。"""
    logging.basicConfig(
        filename=log_path(),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    def excepthook(tp, val, tb):
        logging.error("未捕获异常", exc_info=(tp, val, tb))
        sys.__excepthook__(tp, val, tb)

    sys.excepthook = excepthook
    logging.info("=" * 40)
    logging.info("程序启动")
