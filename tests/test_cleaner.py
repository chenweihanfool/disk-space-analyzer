import os
import sys
import tempfile
import time
import unittest
from unittest import mock

import cleaner

try:
    import _winapi
except ImportError:  # 非 Windows
    _winapi = None

_OLD = time.time() - 2 * 24 * 60 * 60


def _write(path, content=b"x", old=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    if old:
        os.utime(path, (_OLD, _OLD))
    return path


class CleanerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = self._tmp.name
        self.temp_root = os.path.join(self.base, "temp")
        os.makedirs(self.temp_root, exist_ok=True)
        self.local = os.path.join(self.base, "local")
        os.makedirs(self.local, exist_ok=True)
        self.env = {"TEMP": self.temp_root, "LOCALAPPDATA": self.local}

    def _category(self, payload, category_id):
        for category in payload["categories"]:
            if category["id"] == category_id:
                return category
        self.fail(f"找不到類別 {category_id}")

    def _result(self, payload, category_id):
        for result in payload["results"]:
            if result["id"] == category_id:
                return result
        self.fail(f"找不到結果 {category_id}")


class UserTempTests(CleanerTestBase):
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=None)
    def test_removes_only_old_files_and_empty_dirs(self, _query):
        old_root = _write(os.path.join(self.temp_root, "old_root.tmp"), b"a" * 100, old=True)
        new_root = _write(os.path.join(self.temp_root, "new_root.tmp"), b"b" * 50)
        old_sub = _write(os.path.join(self.temp_root, "sub", "old_sub.tmp"), b"c" * 20, old=True)
        old_nested = _write(
            os.path.join(self.temp_root, "sub", "nested", "old_nested.tmp"),
            b"d" * 10,
            old=True,
        )
        kept_dir = os.path.join(self.temp_root, "kept")
        new_kept = _write(os.path.join(kept_dir, "new_kept.tmp"), b"e" * 5)

        preview = cleaner.preview(env=self.env)
        entry = self._category(preview, "user_temp")
        self.assertTrue(entry["available"])
        self.assertEqual(entry["count"], 3)
        self.assertEqual(entry["size"], 100 + 20 + 10)

        payload = cleaner.run(["user_temp"], env=self.env)
        result = self._result(payload, "user_temp")
        self.assertFalse(os.path.exists(old_root))
        self.assertTrue(os.path.exists(new_root))
        self.assertFalse(os.path.exists(old_sub))
        self.assertFalse(os.path.exists(old_nested))
        self.assertFalse(os.path.exists(os.path.join(self.temp_root, "sub")))
        self.assertTrue(os.path.exists(new_kept))
        self.assertTrue(os.path.isdir(self.temp_root))
        self.assertEqual(result["deleted"], 3)
        self.assertEqual(result["freed"], 100 + 20 + 10)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(payload["total_freed"], 100 + 20 + 10)

    @unittest.skipUnless(
        sys.platform == "win32" and _winapi is not None, "需要 Windows junction"
    )
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=None)
    def test_does_not_follow_junction(self, _query):
        target = os.path.join(self.base, "outside")
        victim = _write(os.path.join(target, "keep_me.txt"), b"keep", old=True)
        link = os.path.join(self.temp_root, "link_to_outside")
        _winapi.CreateJunction(target, link)
        try:
            result = cleaner.run(["user_temp"], env=self.env)["results"][0]
            self.assertTrue(os.path.exists(victim))
            self.assertEqual(result["freed"], 0)
            self.assertGreaterEqual(result["skipped"], 1)
            self.assertFalse(os.path.islink(link))
        finally:
            try:
                os.rmdir(link)
            except OSError:
                pass

    def test_delete_failure_is_counted_not_raised(self):
        locked = _write(os.path.join(self.temp_root, "locked.tmp"), b"z" * 8, old=True)
        with mock.patch.object(cleaner.os, "remove", side_effect=PermissionError("locked")):
            payload = cleaner.run(["user_temp"], env=self.env)
        result = self._result(payload, "user_temp")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["freed"], 0)
        self.assertTrue(os.path.exists(locked))


class CategoryListingTests(CleanerTestBase):
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=None)
    def test_preview_shape_and_unavailable_when_roots_missing(self, _query):
        env = {
            "TEMP": os.path.join(self.base, "no_temp"),
            "LOCALAPPDATA": os.path.join(self.base, "no_local"),
        }
        payload = cleaner.preview(env=env)
        categories = payload["categories"]
        self.assertEqual(
            [c["id"] for c in categories],
            [
                "user_temp",
                "browser_cache",
                "thumbnail_cache",
                "crash_dumps",
                "dev_cache",
                "recycle_bin",
            ],
        )
        allowed = {
            "id",
            "name",
            "desc",
            "size",
            "count",
            "available",
            "default_checked",
            "warning",
        }
        for category in categories:
            self.assertEqual(set(category), allowed)
            self.assertFalse(category["available"])
            self.assertEqual(category["size"], 0)
            self.assertEqual(category["count"], 0)
        self.assertEqual(
            [c["default_checked"] for c in categories],
            [True, True, True, True, False, False],
        )

    def test_unknown_ids_are_ignored(self):
        payload = cleaner.run(["not_a_category"], env=self.env)
        self.assertEqual(payload, {"results": [], "total_freed": 0})

        payload = cleaner.run(["user_temp"], env={
            "TEMP": os.path.join(self.base, "no_temp"),
            "LOCALAPPDATA": os.path.join(self.base, "no_local"),
        })
        self.assertEqual(
            payload["results"],
            [{
                "id": "user_temp",
                "name": "使用者暫存檔",
                "freed": 0,
                "deleted": 0,
                "failed": 0,
                "skipped": 0,
            }],
        )


class ThumbnailTests(CleanerTestBase):
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=None)
    def test_only_pattern_files_are_deleted_non_recursively(self, _query):
        explorer = os.path.join(self.local, "Microsoft", "Windows", "Explorer")
        thumb = _write(os.path.join(explorer, "thumbcache_123.db"), b"t" * 30)
        icon = _write(os.path.join(explorer, "iconcache_456.db"), b"i" * 12)
        other = _write(os.path.join(explorer, "other.bin"), b"o" * 7)
        nested = _write(os.path.join(explorer, "sub", "thumbcache_789.db"), b"n" * 3)

        preview = self._category(cleaner.preview(env=self.env), "thumbnail_cache")
        self.assertTrue(preview["available"])
        self.assertEqual(preview["count"], 2)
        self.assertEqual(preview["size"], 30 + 12)

        payload = cleaner.run(["thumbnail_cache"], env=self.env)
        result = self._result(payload, "thumbnail_cache")
        self.assertFalse(os.path.exists(thumb))
        self.assertFalse(os.path.exists(icon))
        self.assertTrue(os.path.exists(other))
        self.assertTrue(os.path.exists(nested))
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["failed"], 0)


class BrowserCacheTests(CleanerTestBase):
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=None)
    def test_profile_cache_locations_are_collected(self, _query):
        user_data = os.path.join(self.local, "Google", "Chrome", "User Data")
        files = [
            _write(os.path.join(user_data, "Default", "Cache", "c1"), b"a" * 4),
            _write(os.path.join(user_data, "Default", "Code Cache", "c2"), b"b" * 5),
            _write(os.path.join(user_data, "Profile 2", "GPUCache", "c3"), b"c" * 6),
        ]
        unrelated = _write(
            os.path.join(user_data, "NoCacheProfile", "notes.txt"), b"n" * 9
        )
        firefox = os.path.join(self.local, "Mozilla", "Firefox", "Profiles", "abc")
        ff_file = _write(os.path.join(firefox, "cache2", "entry"), b"d" * 7)

        preview = self._category(cleaner.preview(env=self.env), "browser_cache")
        self.assertTrue(preview["available"])
        self.assertEqual(preview["count"], 4)
        self.assertEqual(preview["size"], 4 + 5 + 6 + 7)
        self.assertEqual(preview["warning"], "瀏覽器開著時部分檔案會被略過")

        cleaner.run(["browser_cache"], env=self.env)
        for path in files + [ff_file]:
            self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(unrelated))


class RecycleBinTests(CleanerTestBase):
    @mock.patch.object(cleaner, "_empty_recycle_bin", return_value=0)
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=(4096, 3))
    def test_preview_and_run_use_shell_api_values(self, _query, _empty):
        preview = self._category(cleaner.preview(env=self.env), "recycle_bin")
        self.assertTrue(preview["available"])
        self.assertEqual(preview["size"], 4096)
        self.assertEqual(preview["count"], 3)
        self.assertEqual(preview["warning"], "清空後無法復原")

        payload = cleaner.run(["recycle_bin"], env=self.env)
        result = self._result(payload, "recycle_bin")
        self.assertEqual(result["freed"], 4096)
        self.assertEqual(result["deleted"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(payload["total_freed"], 4096)
        _empty.assert_called_once()

    @mock.patch.object(cleaner, "_empty_recycle_bin", return_value=-2147418113)
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=(1024, 2))
    def test_e_unexpected_is_treated_as_already_empty(self, _query, _empty):
        result = cleaner.run(["recycle_bin"], env=self.env)["results"][0]
        self.assertEqual(result["freed"], 1024)
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["failed"], 0)

    @mock.patch.object(cleaner, "_empty_recycle_bin", return_value=1)
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=(1024, 2))
    def test_empty_failure_marks_items_failed(self, _query, _empty):
        payload = cleaner.run(["recycle_bin"], env=self.env)
        result = payload["results"][0]
        self.assertEqual(result["freed"], 0)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(payload["total_freed"], 0)

    @mock.patch.object(cleaner, "_empty_recycle_bin")
    @mock.patch.object(cleaner, "_query_recycle_bin", return_value=None)
    def test_unavailable_recycle_bin(self, _query, _empty):
        preview = self._category(cleaner.preview(env=self.env), "recycle_bin")
        self.assertFalse(preview["available"])
        self.assertEqual(preview["size"], 0)
        self.assertEqual(preview["count"], 0)

        result = cleaner.run(["recycle_bin"], env=self.env)["results"][0]
        self.assertEqual(
            result,
            {
                "id": "recycle_bin",
                "name": "資源回收筒",
                "freed": 0,
                "deleted": 0,
                "failed": 0,
                "skipped": 0,
            },
        )
        _empty.assert_not_called()


if __name__ == "__main__":
    unittest.main()
