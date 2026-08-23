import os
import tempfile
import unittest

from stdedit.explorer import PARENT, FileExplorer


class ExplorerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        # Layout:
        #   root/
        #     alpha.txt
        #     beta.py
        #     sub_one/  (contains inner.txt)
        #     sub_two/
        #     .hidden_dir/  (contains secret.txt)
        #     .hidden_file
        os.mkdir(os.path.join(self.root, "sub_one"))
        os.mkdir(os.path.join(self.root, "sub_two"))
        os.mkdir(os.path.join(self.root, ".hidden_dir"))
        with open(os.path.join(self.root, "alpha.txt"), "w") as f:
            f.write("a")
        with open(os.path.join(self.root, "beta.py"), "w") as f:
            f.write("b")
        with open(os.path.join(self.root, ".hidden_file"), "w") as f:
            f.write("h")
        with open(os.path.join(self.root, "sub_one", "inner.txt"), "w") as f:
            f.write("i")
        with open(os.path.join(self.root, ".hidden_dir", "secret.txt"), "w") as f:
            f.write("s")

    def tearDown(self):
        self._tmp.cleanup()

    def paths(self, explorer):
        return [item[2] for item in explorer.items]


class TestTreeBuilding(ExplorerTestBase):
    def test_dirs_listed_before_files_sorted_case_insensitive(self):
        e = FileExplorer(self.root)
        names = [os.path.basename(p) for p in self.paths(e) if p != PARENT]
        dirs = names[:2]
        files = names[2:]
        self.assertEqual(sorted(dirs, key=str.lower), ["sub_one", "sub_two"])
        self.assertEqual(files, ["alpha.txt", "beta.py"])

    def test_hidden_entries_filtered_by_default(self):
        e = FileExplorer(self.root)
        all_paths = " ".join(self.paths(e))
        self.assertNotIn(".hidden_file", all_paths)
        self.assertNotIn(".hidden_dir", all_paths)

    def test_toggle_hidden_reveals_dotfiles(self):
        e = FileExplorer(self.root)
        e.toggle_hidden()
        all_paths = " ".join(self.paths(e))
        self.assertIn(".hidden_file", all_paths)
        self.assertIn(".hidden_dir", all_paths)
        # And back off again.
        e.toggle_hidden()
        self.assertNotIn(".hidden_file", " ".join(self.paths(e)))

    def test_ignored_names_never_shown(self):
        junk = os.path.join(self.root, "__pycache__")
        venv = os.path.join(self.root, ".venv")
        node = os.path.join(self.root, "node_modules")
        for d in (junk, venv, node):
            os.mkdir(d)
            with open(os.path.join(d, "x.bin"), "w") as f:
                f.write("x")
        e = FileExplorer(self.root)
        e.toggle_hidden()  # even with hidden files visible
        joined = " ".join(self.paths(e))
        for d in (junk, venv, node):
            self.assertNotIn(os.path.basename(d), joined)


class TestRootingAndNavigation(ExplorerTestBase):
    def test_set_root_reroots_tree(self):
        e = FileExplorer(".")
        e.set_root(self.root)
        self.assertEqual(e.root_dir, os.path.abspath(self.root))
        self.assertIn("alpha.txt", " ".join(e.items[i][1] for i in range(len(e.items))))

    def test_set_root_ignores_non_directories(self):
        e = FileExplorer(self.root)
        before = list(e.items)
        e.set_root(os.path.join(self.root, "alpha.txt"))  # a file
        self.assertEqual(e.items, before)

    def test_parent_entry_present_with_parent(self):
        e = FileExplorer(self.root)  # root has a parent on any normal FS
        self.assertEqual(e.items[0], (0, PARENT, PARENT, False))

    def test_no_parent_entry_at_filesystem_root(self):
        e = FileExplorer("/")
        e.refresh()
        self.assertTrue(all(item[2] != PARENT for item in e.items))

    def test_go_up_selects_previous_root(self):
        sub_one = os.path.join(self.root, "sub_one")
        e = FileExplorer(sub_one)
        self.assertTrue(e.can_go_up())
        e.go_up()
        self.assertEqual(e.root_dir, os.path.abspath(self.root))
        selected = e.get_selected()
        self.assertIsNotNone(selected)
        self.assertTrue(selected[3])  # is_dir
        self.assertEqual(selected[2], os.path.abspath(sub_one))

    def test_expansion_state_survives_climb_and_return(self):
        sub_one = os.path.join(self.root, "sub_one")
        e = FileExplorer(self.root)
        # Expand sub_one by toggling its entry.
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.toggle_expand(idx)
        self.assertIn("inner.txt", " ".join(it[1] for it in e.items))
        e.go_up()
        e.set_root(self.root)
        self.assertIn(
            "sub_one", " ".join(it[1] for it in e.items if it[3])
        )
        # Still expanded after returning: inner.txt is listed again.
        self.assertIn("inner.txt", " ".join(it[1] for it in e.items))


class TestSelection(ExplorerTestBase):
    def test_move_selection_clamps_to_bounds(self):
        e = FileExplorer(self.root)
        count = len(e.items)
        e.move_selection(-5)
        self.assertEqual(e.selected_idx, 0)
        e.move_selection(count + 10)
        self.assertEqual(e.selected_idx, count - 1)

    def test_get_selected_out_of_range_returns_none(self):
        e = FileExplorer(self.root)
        e.selected_idx = len(e.items)
        self.assertIsNone(e.get_selected())

    def test_toggle_expand_adds_and_removes_children(self):
        sub_one = os.path.join(self.root, "sub_one")
        e = FileExplorer(self.root)
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.toggle_expand(idx)
        self.assertIn("inner.txt", " ".join(it[1] for it in e.items))
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.toggle_expand(idx)
        self.assertNotIn("inner.txt", " ".join(it[1] for it in e.items))

    def test_toggle_expand_ignores_files(self):
        alpha = os.path.join(self.root, "alpha.txt")
        e = FileExplorer(self.root)
        before = list(e.items)
        idx = [i for i, it in enumerate(e.items) if it[2] == alpha][0]
        e.toggle_expand(idx)
        self.assertEqual(e.items, before)


if __name__ == "__main__":
    unittest.main()
