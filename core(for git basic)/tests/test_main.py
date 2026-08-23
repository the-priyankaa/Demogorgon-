import os
import tempfile
import unittest

from stdedit.main import build_parser, resolve_open_targets


class TestProjectFlag(unittest.TestCase):
    def test_project_defaults_to_none(self):
        args = build_parser().parse_args(["a.py"])
        self.assertIsNone(args.project)

    def test_project_is_parsed_with_optional_file(self):
        args = build_parser().parse_args(["--project", "/tmp", "a.py"])
        self.assertEqual(args.project, "/tmp")

    def test_project_works_without_file(self):
        args = build_parser().parse_args(["--project", "~/myapp"])
        self.assertEqual(args.project, "~/myapp")


class TestResolveOpenTargets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_arguments(self):
        self.assertEqual(resolve_open_targets(None, None), (None, None, None))

    def test_plain_file_opens_in_buffer(self):
        target = os.path.join(self.tmp, "x.py")
        with open(target, "w") as f:
            f.write("1\n")
        buf_file, project_dir, error = resolve_open_targets(target, None)
        self.assertIsNone(error)
        self.assertEqual(buf_file, target)
        # No explicit project: tui.resolve_tree_root() later falls back to
        # the opened file's parent folder.
        self.assertIsNone(project_dir)

    def test_directory_positional_means_project(self):
        buf_file, project_dir, error = resolve_open_targets(self.tmp, None)
        self.assertIsNone(error)
        self.assertIsNone(buf_file)
        self.assertEqual(project_dir, os.path.abspath(self.tmp))

    def test_tilde_expands_for_both_arguments(self):
        home = os.path.expanduser("~")
        _, project_dir, _ = resolve_open_targets(None, "~")
        self.assertEqual(project_dir, home)
        # A path under ~ that does not exist is treated as a new file.
        buf_file, _, error = resolve_open_targets("~/no_such_file_xyz.py", None)
        self.assertIsNone(error)
        self.assertEqual(buf_file, "~/no_such_file_xyz.py")

    def test_project_flag_validated(self):
        buf_file, project_dir, error = resolve_open_targets(None, "/no/such/dir")
        self.assertIsNotNone(error)
        self.assertIn("not a directory", error)
        self.assertIsNone(buf_file)

    def test_positional_dir_and_project_conflict(self):
        buf_file, project_dir, error = resolve_open_targets(self.tmp, self.tmp)
        self.assertIsNotNone(error)
        self.assertIn("once", error)
        self.assertIsNone(buf_file)
        self.assertIsNone(project_dir)

    def test_nonexistent_path_stays_a_new_file(self):
        missing = "/definitely/not/here.py"
        buf_file, project_dir, error = resolve_open_targets(missing, None)
        self.assertIsNone(error)
        self.assertEqual(buf_file, missing)


if __name__ == "__main__":
    unittest.main()
