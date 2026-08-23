import os
import unittest

from stdedit.main import build_parser


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


if __name__ == "__main__":
    unittest.main()
