import os
import tempfile
import unittest

from stdedit.dashboard import action_key, action_count, layout
from stdedit.quick_open import build_file_index


class DashboardLayoutTests(unittest.TestCase):
    def test_layout_never_exceeds_terminal_bounds(self):
        for width, height in [(24, 8), (40, 12), (60, 20), (80, 24), (120, 40), (160, 50)]:
            boxes = layout(height, width)
            for name, rect in boxes.items():
                if rect.w <= 0 or rect.h <= 0:
                    continue
                self.assertGreaterEqual(rect.x, 0, name)
                self.assertGreaterEqual(rect.y, 0, name)
                self.assertLessEqual(rect.x + rect.w, width, name)
                self.assertLessEqual(rect.y + rect.h, max(height, 8), name)

    def test_action_mapping(self):
        self.assertEqual(action_count(), 8)
        self.assertEqual(action_key(0), "F1")
        self.assertEqual(action_key(7), "Q")


class HomeSearchScopeTests(unittest.TestCase):
    def test_excluded_roots_are_not_indexed(self):
        with tempfile.TemporaryDirectory() as td:
            keep = os.path.join(td, "keep.txt")
            excluded = os.path.join(td, "yuki-code", "main.py")
            os.makedirs(os.path.dirname(excluded))
            open(keep, "w", encoding="utf-8").close()
            open(excluded, "w", encoding="utf-8").close()
            files = build_file_index(td, exclude_roots=[os.path.dirname(excluded)])
            self.assertIn(os.path.abspath(keep), files)
            self.assertNotIn(os.path.abspath(excluded), files)

    def test_hidden_junk_dirs_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "visible.txt"), "w", encoding="utf-8").close()
            hidden = os.path.join(td, ".cache", "junk.txt")
            os.makedirs(os.path.dirname(hidden))
            open(hidden, "w", encoding="utf-8").close()
            files = build_file_index(td)
            self.assertIn(os.path.abspath(os.path.join(td, "visible.txt")), files)
            self.assertNotIn(os.path.abspath(hidden), files)


if __name__ == "__main__":
    unittest.main()
