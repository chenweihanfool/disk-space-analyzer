import os
import time


def scan(root, progress_cb=None, cancel_event=None):
    """Iterative post-order scan. Returns dict: path -> {own_size, file_count, children, total_size, total_files}."""
    info = {}
    order = []
    stack = [root]
    visited_count = 0
    t0 = time.time()

    while stack:
        if cancel_event is not None and cancel_event.is_set():
            return info

        d = stack.pop()
        order.append(d)
        own_size = 0
        file_count = 0
        subdirs = []
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            subdirs.append(entry.path)
                        else:
                            st = entry.stat(follow_symlinks=False)
                            own_size += st.st_size
                            file_count += 1
                    except OSError:
                        continue
        except OSError:
            pass

        info[d] = {
            "own_size": own_size,
            "file_count": file_count,
            "children": subdirs,
            "total_size": 0,
            "total_files": 0,
        }
        for sd in subdirs:
            stack.append(sd)

        visited_count += 1
        if progress_cb is not None and visited_count % 500 == 0:
            progress_cb(visited_count, time.time() - t0)

    for d in reversed(order):
        node = info[d]
        total = node["own_size"]
        totalf = node["file_count"]
        for c in node["children"]:
            cn = info.get(c)
            if cn is None:
                continue
            total += cn["total_size"]
            totalf += cn["total_files"]
        node["total_size"] = total
        node["total_files"] = totalf

    if progress_cb is not None:
        progress_cb(visited_count, time.time() - t0)

    return info


def build_tree(info, path, depth=0, max_depth=8, top_n=25):
    node = info[path]
    name = os.path.basename(path.rstrip("\\/")) or path
    result = {
        "name": name,
        "path": path,
        "size": node["total_size"],
        "files": node["total_files"],
    }

    children_out = []
    if node["own_size"] > 0:
        children_out.append({
            "name": "(此層檔案)",
            "path": None,
            "size": node["own_size"],
            "files": node["file_count"],
        })

    if depth < max_depth and node["children"]:
        kids = sorted(node["children"], key=lambda c: info[c]["total_size"], reverse=True)
        shown = [c for c in kids[:top_n] if info[c]["total_size"] > 0]
        rest = kids[top_n:]
        for c in shown:
            children_out.append(build_tree(info, c, depth + 1, max_depth, top_n))
        if rest:
            rest_size = sum(info[c]["total_size"] for c in rest)
            rest_files = sum(info[c]["total_files"] for c in rest)
            if rest_size > 0:
                children_out.append({
                    "name": f"...其他 {len(rest)} 個較小資料夾",
                    "path": None,
                    "size": rest_size,
                    "files": rest_files,
                })

    if children_out:
        result["children"] = children_out
    return result


def flat_top(info, n=80):
    items = sorted(info.items(), key=lambda kv: kv[1]["total_size"], reverse=True)
    out = []
    for path, node in items[:n]:
        out.append({
            "path": path,
            "size": node["total_size"],
            "files": node["total_files"],
        })
    return out
