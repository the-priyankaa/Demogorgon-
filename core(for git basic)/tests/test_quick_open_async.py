import os
import tempfile
import time
import unittest
from unittest import mock

import stdedit.quick_open as quick_open


class TestQuickOpenAsync(unittest.TestCase):
    def test_open_is_non_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            real_iter = quick_open._iter_file_index

            def slow_iter(root, excludes=None):
                time.sleep(0.25)
                yield from real_iter(root, excludes)

            with mock.patch.object(quick_open, "_iter_file_index", slow_iter):
                qo = quick_open.QuickOpen(td)
                started = time.perf_counter()
                qo.open()
                elapsed = time.perf_counter() - started
                self.assertLess(elapsed, 0.10)
                self.assertTrue(qo.visible)
                qo.close()

    def test_results_arrive_after_background_scan(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "hello_world.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("print('hi')")
            qo = quick_open.QuickOpen(td)
            qo.open()
            qo.update_query("hello")
            deadline = time.time() + 2.0
            while time.time() < deadline and not qo.results:
                time.sleep(0.01)
            self.assertTrue(qo.results)
            self.assertEqual(qo.selected_path(), os.path.abspath(path))
            qo.close()

    def test_direct_path_can_open_before_scan_finishes(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "instant.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x = 1")
            qo = quick_open.QuickOpen(td)
            qo.open()
            qo.update_query("instant.py")
            self.assertEqual(qo.selected_path(), os.path.abspath(path))
            qo.close()

    def test_empty_search_has_no_random_selection(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "file.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            qo = quick_open.QuickOpen(td)
            qo.open(background_index=False)
            self.assertEqual(qo.get_display_items(), [])
            self.assertIsNone(qo.selected_path())
            qo.close()

    def test_recent_mode_does_not_start_scan(self):
        qo = quick_open.QuickOpen("/definitely/not/a/real/path", show_recent_on_empty=True)
        qo.open(background_index=False)
        self.assertFalse(qo.loading)
        self.assertTrue(qo.visible)
        qo.close()

    def test_stale_scan_cannot_replace_new_scan(self):
        with tempfile.TemporaryDirectory() as td:
            first = os.path.join(td, "first.txt")
            second = os.path.join(td, "second.txt")
            open(first, "w", encoding="utf-8").close()
            open(second, "w", encoding="utf-8").close()

            release = []
            real_iter = quick_open._iter_file_index

            def controlled_iter(root, excludes=None):
                release.append(True)
                yield from real_iter(root, excludes)

            with mock.patch.object(quick_open, "_iter_file_index", controlled_iter):
                qo = quick_open.QuickOpen(td)
                qo.open()
                qo.open()
                deadline = time.time() + 2.0
                while time.time() < deadline and qo.loading:
                    time.sleep(0.01)
                self.assertTrue(qo.files)
                self.assertTrue(all(p.endswith(("first.txt", "second.txt")) for p in qo.files))
                qo.close()


if __name__ == "__main__":
    unittest.main()
