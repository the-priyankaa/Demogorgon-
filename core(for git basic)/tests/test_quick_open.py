"""Tests for quick_open.py — fuzzy file search engine."""
import os
import shutil
import tempfile
import unittest

from stdedit.quick_open import (
    _fuzzy_score,
    fuzzy_search,
    build_file_index,
    QuickOpen,
)


class TestFuzzyScore(unittest.TestCase):
    def test_exact_basename_prefix(self):
        s = _fuzzy_score("tui", "/home/user/src/tui.py")
        self.assertGreater(s, 0)

    def test_no_match(self):
        s = _fuzzy_score("zzz", "/home/user/src/tui.py")
        self.assertEqual(s, -1.0)

    def test_empty_query(self):
        s = _fuzzy_score("", "/home/user/src/tui.py")
        self.assertEqual(s, 0.0)

    def test_basename_bonus(self):
        s_basename = _fuzzy_score("tui", "/src/tui.py")
        s_deep = _fuzzy_score("tui", "/src/deep/nested/tui.py")
        self.assertGreater(s_basename, s_deep)

    def test_contiguous_bonus(self):
        s_contig = _fuzzy_score("tui", "/src/tui.py")
        s_spaced = _fuzzy_score("tp", "/src/tui.py")
        self.assertGreater(s_contig, s_spaced)


class TestFuzzySearch(unittest.TestCase):
    def test_returns_top_results(self):
        files = ["/src/tui.py", "/src/buffer.py", "/src/git.py", "/src/test_tui.py"]
        results = fuzzy_search("tui", files, limit=2)
        self.assertEqual(len(results), 2)
        self.assertIn("tui.py", results[0][1])

    def test_empty_query(self):
        results = fuzzy_search("", ["/src/tui.py"])
        self.assertEqual(results, [])

    def test_no_matches(self):
        results = fuzzy_search("zzz", ["/src/tui.py"])
        self.assertEqual(results, [])


class TestBuildFileIndex(unittest.TestCase):
    def test_collects_files(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "sub"))
            with open(os.path.join(d, "a.py"), "w") as f:
                f.write("x")
            with open(os.path.join(d, "sub", "b.py"), "w") as f:
                f.write("y")
            files = build_file_index(d)
            self.assertEqual(len(files), 2)
            self.assertTrue(any("a.py" in f for f in files))
            self.assertTrue(any("b.py" in f for f in files))
        finally:
            shutil.rmtree(d)

    def test_skips_git_dir(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, ".git"))
            with open(os.path.join(d, ".git", "config"), "w") as f:
                f.write("x")
            with open(os.path.join(d, "a.py"), "w") as f:
                f.write("y")
            files = build_file_index(d)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].endswith("a.py"))
        finally:
            shutil.rmtree(d)


class TestQuickOpen(unittest.TestCase):
    def test_open_and_close(self):
        qo = QuickOpen("/tmp")
        qo.open()
        self.assertTrue(qo.visible)
        qo.close()
        self.assertFalse(qo.visible)

    def test_update_query(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "hello.py"), "w") as f:
                f.write("x")
            qo = QuickOpen(d)
            qo.open()
            qo.update_query("hello")
            deadline = __import__("time").time() + 2.0
            while __import__("time").time() < deadline and not qo.results:
                __import__("time").sleep(0.01)
            self.assertEqual(len(qo.results), 1)
            self.assertIn("hello.py", qo.results[0][1])
            qo.close()
        finally:
            shutil.rmtree(d)

    def test_move_selection(self):
        qo = QuickOpen("/tmp")
        qo.open()
        qo.move_selection(1)
        self.assertEqual(qo.selected_idx, 0)  # no results, stays 0

    def test_get_display_items_recent(self):
        qo = QuickOpen("/tmp")
        qo.open()
        items = qo.get_display_items()
        # With empty query, shows recent files (may be empty)
        self.assertIsInstance(items, list)

    def test_selected_path_none_when_empty(self):
        qo = QuickOpen("/tmp")
        qo.open()
        self.assertIsNone(qo.selected_path())


if __name__ == "__main__":
    unittest.main()
