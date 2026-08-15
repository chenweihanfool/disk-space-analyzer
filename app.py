import ctypes
import os
import sys

import webview

from api import Api


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main():
    api = Api()
    window = webview.create_window(
        "D槽容量分析 Disk Space Analyzer",
        resource_path("ui.html"),
        js_api=api,
        width=1280,
        height=820,
        min_size=(900, 600),
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(0, str(e), "Disk Space Analyzer - 啟動失敗", 0x10)
        raise
