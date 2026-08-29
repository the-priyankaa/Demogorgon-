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

    def test_dirs_only_collects_directories(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "sub"))
            os.makedirs(os.path.join(d, "inner", "deep"))
            with open(os.path.join(d, "a.py"), "w") as f:
                f.write("x")
            with open(os.path.join(d, "sub", "b.py"), "w") as f:
                f.write("y")
            dirs = build_file_index(d, dirs_only=True)
            self.assertEqual(len(dirs), 3)
            self.assertTrue(any(x.endswith("sub") for x in dirs))
            self.assertTrue(any(x.endswith(os.path.join("inner", "deep")) for x in dirs))
            self.assertFalse(any(x.endswith(".py") for x in dirs))
        finally:
            shutil.rmtree(d)

    def test_dirs_only_skips_hidden_and_git_dirs(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, ".cache"))
            os.makedirs(os.path.join(d, ".git"))
            os.makedirs(os.path.join(d, "keep"))
            dirs = build_file_index(d, dirs_only=True)
            self.assertTrue(any(x.endswith("keep") for x in dirs))
            self.assertFalse(any(".git" in x or ".cache" in x for x in dirs))
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

    def test_close_releases_index(self):
        d = tempfile.mkdtemp(prefix="stdedit-qo-")
        try:
            for name in ("a.py", "b.py", "c.py"):
                with open(os.path.join(d, name), "w") as f:
                    f.write("x")
            qo = QuickOpen(d)
            qo.open()
            deadline = __import__("time").time() + 2.0
            while (__import__("time").time() < deadline
                   and not qo.files):
                __import__("time").sleep(0.01)
            self.assertTrue(qo.files)
            self.assertEqual(len(qo.files), len(qo._lowers))
            qo.close()
            self.assertEqual(qo.files, [])
            self.assertEqual(qo._lowers, [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestDirectLocation(unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp(prefix="stdedit-qo-")
        self._file = os.path.join(self._root, "sample.py")
        with open(self._file, "w") as f:
            f.write("x")
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

    def test_direct_folder_absolute(self):
        qo = QuickOpen(self._root)
        qo.open()
        qo.update_query(self._root)
        self.assertEqual(qo._direct_folder(), os.path.abspath(self._root))
        self.assertIsNone(qo._direct_candidate())  # folder is not a file

    def test_direct_folder_relative_to_root(self):
        sub = os.path.join(self._root, "sub")
        os.makedirs(sub)
        qo = QuickOpen(self._root)
        qo.open()
        qo.update_query("sub")
        self.assertEqual(qo._direct_folder(), sub)

    def test_direct_folder_trailing_slash(self):
        qo = QuickOpen(self._root)
        qo.open()
        qo.update_query(self._root + os.sep)
        self.assertEqual(qo._direct_folder(), os.path.abspath(self._root))

    def test_direct_folder_missing_gives_none(self):
        qo = QuickOpen(self._root)
        qo.open()
        qo.update_query(os.path.join(self._root, "nope"))
        self.assertIsNone(qo._direct_folder())
        self.assertIsNone(qo._direct_candidate())

    def test_direct_folder_excluded(self):
        qo = QuickOpen(self._root, exclude_roots=[self._root])
        qo.open()
        qo.update_query(self._root)
        self.assertIsNone(qo._direct_folder())

    def test_direct_folder_none_on_empty_query(self):
        qo = QuickOpen(self._root)
        qo.open()
        self.assertIsNone(qo._direct_folder())

    def test_selected_location_file_takes_precedence(self):
        qo = QuickOpen(self._root)
        qo.open()
        qo.update_query("sample")
        deadline = __import__("time").time() + 2.0
        while __import__("time").time() < deadline and not qo.results:
            __import__("time").sleep(0.01)
        self.assertEqual(qo.selected_location(), self._file)
        qo.close()

    def test_selected_location_falls_back_to_folder(self):
        sub = os.path.join(self._root, "folder")
        os.makedirs(sub)
        qo = QuickOpen(self._root)
        qo.open()
        qo.update_query("folder")
        self.assertEqual(qo.selected_location(), sub)

    def test_selected_location_none_when_nothing_matches(self):
        qo = QuickOpen(self._root)
        qo.open()
        qo.update_query("totally-absent")
        self.assertIsNone(qo.selected_location())

    def test_typed_location_beats_fuzzy_subpath_match(self):
        unrelated = tempfile.mkdtemp(prefix="stdedit-qo-")
        sub = os.path.join(unrelated, "opencodetest")
        os.makedirs(sub)
        self.addCleanup(shutil.rmtree, unrelated, ignore_errors=True)
        with open(os.path.join(sub, "backend.xml"), "w") as f:
            f.write("x")
        qo = QuickOpen(unrelated)
        qo.open()
        qo.update_query("/tmp")
        deadline = __import__("time").time() + 2.0
        while __import__("time").time() < deadline and not qo.results:
            __import__("time").sleep(0.01)
        self.assertNotEqual(qo.selected_location(), os.path.join(sub, "backend.xml"))
        self.assertTrue(os.path.isdir(qo.selected_location()))
        qo.close()


class TestFolderMode(unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp(prefix="stdedit-qo-")
        self._sub = os.path.join(self._root, "sub")
        os.makedirs(self._sub)
        self._file = os.path.join(self._root, "sample.py")
        with open(self._file, "w") as f:
            f.write("x")
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

    def test_fuzzy_match_returns_directory(self):
        qo = QuickOpen(self._root, mode="folders")
        qo.open()
        qo.update_query("sub")
        deadline = __import__("time").time() + 2.0
        while __import__("time").time() < deadline and not qo.results:
            __import__("time").sleep(0.01)
        self.assertTrue(qo.results)
        self.assertTrue(all(os.path.isdir(p) for _, p in qo.results))
        self.assertEqual(qo.selected_location(), self._sub)
        qo.close()

    def test_typed_file_rejected_in_folder_mode(self):
        qo = QuickOpen(self._root, mode="folders")
        qo.open()
        qo.update_query(self._file)
        deadline = __import__("time").time() + 2.0
        while __import__("time").time() < deadline and not qo.results:
            __import__("time").sleep(0.01)
        self.assertIsNone(qo.selected_location())
        qo.close()

    def test_typed_folder_accepted_in_folder_mode(self):
        qo = QuickOpen(self._root, mode="folders")
        qo.open()
        qo.update_query(self._sub)
        self.assertEqual(qo.selected_location(), self._sub)
        qo.close()

    def test_empty_query_ignores_recent_in_folder_mode(self):
        qo = QuickOpen(self._root, mode="folders", show_recent_on_empty=True)
        qo.open()
        self.assertEqual(qo.get_display_items(), [])
        qo.close()


if __name__ == "__main__":
    unittest.main()
