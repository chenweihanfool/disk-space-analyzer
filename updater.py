import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from version import UPDATE_ASSET_NAME


def _parse_version(v):
    return tuple(int(p) for p in v.split(".") if p.isdigit())


def check_update(current_version, repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "DiskSpaceAnalyzer-Updater"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

    latest = data.get("tag_name", "").lstrip("vV")
    if not latest:
        return {"error": "找不到任何 release"}

    asset_url = None
    for asset in data.get("assets", []):
        if asset.get("name") == UPDATE_ASSET_NAME:
            asset_url = asset.get("browser_download_url")
            break

    try:
        is_newer = _parse_version(latest) > _parse_version(current_version)
    except ValueError:
        is_newer = latest != current_version

    return {
        "update_available": bool(is_newer and asset_url),
        "latest_version": latest,
        "current_version": current_version,
        "download_url": asset_url,
        "notes": data.get("body", ""),
        "release_url": data.get("html_url", ""),
    }


def perform_update(download_url, version, window):
    if not getattr(sys, "frozen", False):
        window.evaluate_js('onUpdateError("開發模式下無法自動更新，請自行 git pull 更新原始碼")')
        return
    if not download_url:
        window.evaluate_js('onUpdateError("找不到可下載的安裝檔")')
        return

    try:
        window.evaluate_js('onUpdateProgress("正在下載新版本...")')
        tmp_dir = tempfile.gettempdir()
        new_exe = os.path.join(tmp_dir, f"DiskSpaceAnalyzer_new_{version}.exe")
        urllib.request.urlretrieve(download_url, new_exe)

        current_exe = sys.executable
        pid = os.getpid()
        bat_path = os.path.join(tmp_dir, "disk_space_analyzer_update.bat")
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
move /y "{new_exe}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
""")
        window.evaluate_js('onUpdateProgress("即將重新啟動...")')
        subprocess.Popen(["cmd", "/c", bat_path], creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(0.5)
        os._exit(0)
    except Exception as e:
        window.evaluate_js(f'onUpdateError({json.dumps(str(e))})')
