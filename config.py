"""应用配置：输出目录、编码、画质、格式、主题、完成后关机，持久化到 config.json。"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


class Config:
    def __init__(self):
        self.out_dir = ""            # 空 = 与源文件同目录
        self.encode_mode = "h264"    # h264(重编码) | copy(无损封装)
        self.quality = "balanced"    # fast | balanced | high
        self.out_format = "mp4"      # mp4 | mkv | webm | mp3
        self.theme = 0               # 0=跟随系统 1=浅色 2=深色
        self.theme_color = ""        # 主题色 hex；"system"=跟随系统；""=默认
        self.shutdown_after_done = False  # 全部完成后关机（一次性）
        self.hw_accel = False            # 硬件加速（NVENC）
        self.close_mode = "ask"          # 关闭窗口行为：ask | background | quit
        self.record_draw_mouse = True    # 录屏时绘制鼠标光标（False=不抽搐但画面无鼠标）
        self.max_concurrent = 2          # 并发转码数（1~8）
        self.notify_on_done = True       # 全部完成时托盘通知
        self.check_update_on_start = True  # 启动时静默检查 ffmpeg 更新
        self.load()

    def resolve_out_dir(self, src_path):
        return self.out_dir if self.out_dir else os.path.dirname(src_path)

    def load(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.out_dir = d.get("out_dir", "")
            self.encode_mode = d.get("encode_mode", "h264")
            self.quality = d.get("quality", "balanced")
            self.out_format = d.get("out_format", "mp4")
            self.theme = d.get("theme", 0)
            self.theme_color = d.get("theme_color", "")
            self.shutdown_after_done = d.get("shutdown_after_done", False)
            self.hw_accel = d.get("hw_accel", False)
            self.close_mode = d.get("close_mode", "ask")
            self.record_draw_mouse = d.get("record_draw_mouse", True)
            self.max_concurrent = max(1, min(8, int(d.get("max_concurrent", 2))))
            self.notify_on_done = d.get("notify_on_done", True)
            self.check_update_on_start = d.get("check_update_on_start", True)
        except Exception:
            pass

    def save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "out_dir": self.out_dir,
                    "encode_mode": self.encode_mode,
                    "quality": self.quality,
                    "out_format": self.out_format,
                    "theme": self.theme,
                    "theme_color": self.theme_color,
                    "shutdown_after_done": self.shutdown_after_done,
                    "hw_accel": self.hw_accel,
                    "close_mode": self.close_mode,
                    "record_draw_mouse": self.record_draw_mouse,
                    "max_concurrent": self.max_concurrent,
                    "notify_on_done": self.notify_on_done,
                    "check_update_on_start": self.check_update_on_start,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


config = Config()
