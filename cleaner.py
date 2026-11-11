"""已知垃圾類別的估算與清除。"""

import ctypes
import fnmatch
import os
import stat
import sys
import tempfile
import time

_DAY_SECONDS = 24 * 60 * 60
_E_UNEXPECTED = 0x8000FFFF
_SHEMPTY_FLAGS = 0x1 | 0x2 | 0x4  # NOCONFIRMATION | NOPROGRESSUI | NOSOUND


def _subdirs(path):
    """列出 path 下的直接子資料夾（排序），不存在或無法讀取時回傳空清單。"""
    try:
        with os.scandir(path) as it:
            names = [entry.path for entry in it if entry.is_dir()]
    except OSError:
        return []
    return sorted(names, key=lambda p: os.path.basename(p).lower())


def _existing_dirs(paths):
    """濾掉空字串與不存在的路徑，保留順序並去重。"""
    result = []
    for path in paths:
        if not path or not os.path.isdir(path):
            continue
        if path not in result:
            result.append(path)
    return result


def get_categories(env=None):
    """回傳類別定義（含後端算出的根目錄清單）。

    env 為 None 時讀取 os.environ／tempfile.gettempdir()；給 dict 時只使用
    該 dict 的 TEMP、LOCALAPPDATA，方便測試注入。
    """
    if env is None:
        temp_root = tempfile.gettempdir()
        local_appdata = os.environ.get("LOCALAPPDATA", "")
    else:
        temp_root = env.get("TEMP", "")
        local_appdata = env.get("LOCALAPPDATA", "")

    browser_roots = []
    if local_appdata:
        for vendor in (
            ("Google", "Chrome"),
            ("Microsoft", "Edge"),
            ("BraveSoftware", "Brave-Browser"),
        ):
            user_data = os.path.join(local_appdata, *vendor, "User Data")
            for profile in _subdirs(user_data):
                for leaf in ("Cache", "Code Cache", "GPUCache"):
                    cache_dir = os.path.join(profile, leaf)
                    if os.path.isdir(cache_dir):
                        browser_roots.append(cache_dir)
        firefox_profiles = os.path.join(
            local_appdata, "Mozilla", "Firefox", "Profiles"
        )
        for profile in _subdirs(firefox_profiles):
            cache2 = os.path.join(profile, "cache2")
            if os.path.isdir(cache2):
                browser_roots.append(cache2)

    explorer_dir = os.path.join(local_appdata, "Microsoft", "Windows", "Explorer")
    crash_roots = [
        os.path.join(local_appdata, "CrashDumps"),
        os.path.join(local_appdata, "Microsoft", "Windows", "WER", "ReportArchive"),
        os.path.join(local_appdata, "Microsoft", "Windows", "WER", "ReportQueue"),
    ]
    dev_roots = [
        os.path.join(local_appdata, "pip", "Cache"),
        os.path.join(local_appdata, "npm-cache"),
        os.path.join(local_appdata, "Yarn", "Cache"),
    ]

    return [
        {
            "id": "user_temp",
            "name": "使用者暫存檔",
            "desc": "程式執行時產生的暫存檔，刪除後可釋放空間，不會影響已安裝的程式或個人檔案。",
            "default_checked": True,
            "warning": None,
            "kind": "files",
            "mode": "older_than_day",
            "recursive": True,
            "patterns": (),
            "roots": _existing_dirs([temp_root]),
        },
        {
            "id": "browser_cache",
            "name": "瀏覽器快取",
            "desc": "瀏覽器儲存的網頁快取，刪除後首次載入網站會稍慢，書籤與密碼不受影響。",
            "default_checked": True,
            "warning": "瀏覽器開著時部分檔案會被略過",
            "kind": "files",
            "mode": "all",
            "recursive": True,
            "patterns": (),
            "roots": _existing_dirs(browser_roots),
        },
        {
            "id": "thumbnail_cache",
            "name": "縮圖快取",
            "desc": "檔案總管顯示圖片與影片縮圖用的快取，刪除後縮圖會自動重新產生。",
            "default_checked": True,
            "warning": None,
            "kind": "files",
            "mode": "pattern",
            "recursive": False,
            "patterns": ("thumbcache_*.db", "iconcache_*.db"),
            "roots": _existing_dirs([explorer_dir]),
        },
        {
            "id": "crash_dumps",
            "name": "當機傾印與錯誤報告",
            "desc": "程式當機時留下的傾印檔與 Windows 錯誤報告，刪除後不影響系統運作。",
            "default_checked": True,
            "warning": None,
            "kind": "files",
            "mode": "all",
            "recursive": True,
            "patterns": (),
            "roots": _existing_dirs(crash_roots),
        },
        {
            "id": "dev_cache",
            "name": "開發工具快取",
            "desc": "pip、npm、Yarn 等開發工具的下載快取，刪除後下次安裝套件需重新下載。",
            "default_checked": False,
            "warning": "下次安裝套件需重新下載",
            "kind": "files",
            "mode": "all",
            "recursive": True,
            "patterns": (),
            "roots": _existing_dirs(dev_roots),
        },
        {
            "id": "recycle_bin",
            "name": "資源回收筒",
            "desc": "資源回收筒內尚未永久刪除的檔案，清空後將無法復原。",
            "default_checked": False,
            "warning": "清空後無法復原",
            "kind": "recycle",
            "mode": "recycle",
            "recursive": False,
            "patterns": (),
            "roots": [],
        },
    ]


def _matches(category, name, st, now):
    if category["mode"] == "older_than_day":
        return now - st.st_mtime > _DAY_SECONDS
    if category["mode"] == "pattern":
        lower_name = name.lower()
        return any(
            fnmatch.fnmatchcase(lower_name, pattern.lower())
            for pattern in category["patterns"]
        )
    return True


def _is_reparse_point(entry, st):
    try:
        if entry.is_symlink():
            return True
    except OSError:
        return True
    attributes = getattr(st, "st_file_attributes", 0)
    if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if is_junction is not None:
        try:
            if is_junction(entry.path):
                return True
        except OSError:
            return True
    return False


def _inside(path, root_real):
    """path 的 realpath 是否嚴格位於 root_real 之下（root 本身不算）。"""
    try:
        real = os.path.normcase(os.path.realpath(path))
    except OSError:
        return False
    if real == root_real:
        return False
    try:
        return os.path.commonpath([real, root_real]) == root_real
    except ValueError:
        return False


def _remove_file(path):
    try:
        os.remove(path)
        return True
    except OSError:
        pass
    try:
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)
        return True
    except OSError:
        return False


def _measure(category, root, now):
    size = 0
    count = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if _is_reparse_point(entry, st):
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if category["recursive"]:
                    stack.append(entry.path)
                continue
            if _matches(category, entry.name, st, now):
                size += st.st_size
                count += 1
    return size, count


def _clean_root(category, root, now, result):
    try:
        root_real = os.path.normcase(os.path.realpath(root))
    except OSError:
        result["skipped"] += 1
        return

    pending_dirs = []
    touched_dirs = set()
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            result["skipped"] += 1
            continue
        entries.sort(key=lambda e: e.name.lower())
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                result["skipped"] += 1
                continue
            if _is_reparse_point(entry, st):
                result["skipped"] += 1
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                result["skipped"] += 1
                continue
            if is_dir:
                if not category["recursive"]:
                    continue
                pending_dirs.append((depth + 1, entry.path))
                stack.append((entry.path, depth + 1))
                continue
            if not _matches(category, entry.name, st, now):
                continue
            if not _inside(entry.path, root_real):
                result["skipped"] += 1
                continue
            if _remove_file(entry.path):
                result["freed"] += st.st_size
                result["deleted"] += 1
                touched_dirs.add(os.path.dirname(entry.path))
            else:
                result["failed"] += 1

    # 由深到淺移除「因這次清理而變空」的資料夾；根目錄本身永遠不在清單內。
    pending_dirs.sort(key=lambda item: item[0], reverse=True)
    for _, path in pending_dirs:
        if path not in touched_dirs:
            continue
        if not _inside(path, root_real):
            result["skipped"] += 1
            continue
        try:
            os.rmdir(path)
        except OSError:
            continue
        touched_dirs.add(os.path.dirname(path))


def _measure_category(category, now):
    size = 0
    count = 0
    for root in category["roots"]:
        part_size, part_count = _measure(category, root, now)
        size += part_size
        count += part_count
    return size, count


def preview(env=None, now=None):
    if now is None:
        now = time.time()
    categories = []
    for category in get_categories(env):
        entry = {
            "id": category["id"],
            "name": category["name"],
            "desc": category["desc"],
            "size": 0,
            "count": 0,
            "available": False,
            "default_checked": category["default_checked"],
            "warning": category["warning"],
        }
        if category["kind"] == "recycle":
            query = _query_recycle_bin()
            if query is not None:
                entry["size"], entry["count"] = query
                entry["available"] = True
        elif category["roots"]:
            entry["available"] = True
            entry["size"], entry["count"] = _measure_category(category, now)
        categories.append(entry)
    return {"categories": categories}


def run(ids, env=None, now=None):
    if now is None:
        now = time.time()
    wanted = set(ids or [])
    results = []
    total_freed = 0
    for category in get_categories(env):
        if category["id"] not in wanted:
            continue
        result = {
            "id": category["id"],
            "name": category["name"],
            "freed": 0,
            "deleted": 0,
            "failed": 0,
            "skipped": 0,
        }
        if category["kind"] == "recycle":
            query = _query_recycle_bin()
            if query is not None:
                size, count = query
                code = _empty_recycle_bin()
                if code is None or (
                    code != 0 and (code & 0xFFFFFFFF) != _E_UNEXPECTED
                ):
                    result["failed"] = count
                else:
                    result["freed"] = size
                    result["deleted"] = count
        else:
            for root in category["roots"]:
                _clean_root(category, root, now, result)
        total_freed += result["freed"]
        results.append(result)
    return {"results": results, "total_freed": total_freed}


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


def _query_recycle_bin():
    """回傳 (總大小, 項目數)；非 Windows 或查詢失敗回傳 None。"""
    if sys.platform != "win32":
        return None
    try:
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if hr != 0:
            return None
        return int(info.i64Size), int(info.i64NumItems)
    except Exception:
        return None


def _empty_recycle_bin():
    """回傳 SHEmptyRecycleBinW 的 HRESULT；非 Windows 或呼叫失敗回傳 None。"""
    if sys.platform != "win32":
        return None
    try:
        return int(
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, _SHEMPTY_FLAGS)
        )
    except Exception:
        return None
