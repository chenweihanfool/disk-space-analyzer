import json
import os
import shutil
import string
import threading
import time
import webbrowser

import webview

import scanner
import updater
from version import APP_VERSION, GITHUB_REPO


class Api:
    def __init__(self):
        self.window = None
        self._scan_thread = None
        self._cancel = threading.Event()

    def list_drives(self):
        drives = []
        for letter in string.ascii_uppercase:
            path = f"{letter}:\\"
            if os.path.exists(path):
                try:
                    usage = shutil.disk_usage(path)
                    drives.append({
                        "path": path,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                    })
                except OSError:
                    continue
        return drives

    def pick_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            return result[0]
        return None

    def start_scan(self, path):
        if self._scan_thread and self._scan_thread.is_alive():
            return {"error": "已有掃描正在進行"}
        if not path or not os.path.isdir(path):
            return {"error": "路徑不存在"}
        self._cancel.clear()
        self._scan_thread = threading.Thread(target=self._run_scan, args=(path,), daemon=True)
        self._scan_thread.start()
        return {"started": True}

    def _run_scan(self, path):
        def progress(count, elapsed):
            self.window.evaluate_js(f"onScanProgress({count}, {elapsed:.1f})")

        try:
            info = scanner.scan(path, progress_cb=progress, cancel_event=self._cancel)
            if self._cancel.is_set():
                self.window.evaluate_js("onScanCancelled()")
                return
            tree = scanner.build_tree(info, path, max_depth=8, top_n=25)
            top = scanner.flat_top(info, 80)
            result = {
                "root": path,
                "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_size": info[path]["total_size"],
                "total_files": info[path]["total_files"],
                "tree": tree,
                "top_folders": top,
            }
            payload = json.dumps(result, ensure_ascii=False)
            self.window.evaluate_js(f"onScanComplete({payload})")
        except Exception as e:
            self.window.evaluate_js(f"onScanError({json.dumps(str(e))})")

    def cancel_scan(self):
        self._cancel.set()
        return {"cancelled": True}

    def open_path(self, path):
        try:
            os.startfile(path)
        except Exception:
            pass
        return {}

    def open_url(self, url):
        webbrowser.open(url)
        return {}

    def get_version(self):
        return APP_VERSION

    def check_update(self):
        return updater.check_update(APP_VERSION, GITHUB_REPO)

    def do_update(self, download_url, latest_version):
        threading.Thread(
            target=updater.perform_update,
            args=(download_url, latest_version, self.window),
            daemon=True,
        ).start()
        return {"started": True}
