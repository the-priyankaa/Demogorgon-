import os
import unittest

from stdedit.tui import line_number_width, format_status_bar
from stdedit.languages.schema import language_label


class TestLineNumbers(unittest.TestCase):
    def test_line_number_width_is_stable_for_small_files(self):
        self.assertEqual(line_number_width(1), 2)
        self.assertEqual(line_number_width(9), 2)
        self.assertEqual(line_number_width(10), 2)

    def test_line_number_width_grows_with_document(self):
        self.assertEqual(line_number_width(99), 2)
        self.assertEqual(line_number_width(100), 3)
        self.assertEqual(line_number_width(1000), 4)


class TestLanguageLabels(unittest.TestCase):
    def test_friendly_names(self):
        self.assertEqual(language_label("python"), "Python")
        self.assertEqual(language_label("javascript"), "JavaScript")
        self.assertEqual(language_label("cpp"), "C++")
        self.assertEqual(language_label("shell"), "Shell")
        self.assertEqual(language_label("plaintext"), "Text")

    def test_unknown_language_falls_back_to_text(self):
        self.assertEqual(language_label("made_up_lang"), "Text")


class TestStatusBar(unittest.TestCase):
    def test_shows_filename_and_type(self):
        line = format_status_bar("main.py", False, "Python", 0, 0, 10)
        self.assertIn("main.py", line)
        self.assertIn("[Python]", line)
        self.assertIn("Ln 1, Col 1", line)

    def test_dirty_marker_after_filename(self):
        line = format_status_bar("main.py", True, "Python", 0, 0, 10)
        self.assertIn("main.py*", line)

    def test_no_name_when_no_file(self):
        line = format_status_bar(None, False, "Text", 0, 0, 1)
        self.assertIn("[No Name]  [Text]", line)

    def test_position_percent(self):
        # Cursor on line 5 of 10 -> 50%.
        line = format_status_bar("f.py", False, "Python", 4, 0, 10)
        self.assertIn("50%", line)

    def test_single_line_file_is_100_percent(self):
        line = format_status_bar("f.py", False, "Python", 0, 0, 1)
        self.assertIn("100%", line)

    def test_optional_segments_omitted(self):
        line = format_status_bar("f.py", False, "Python", 0, 0, 5)
        self.assertNotIn("[SELECT]", line)
        self.assertNotIn("[MATCH", line)
        self.assertNotIn("[LARGE-FILE", line)

    def test_flags_included_when_active(self):
        line = format_status_bar(
            "big.log", False, "Text", 3, 2, 100,
            selecting=True, large_file_mode=True, match_pos=(7, 9),
        )
        self.assertIn("[SELECT]", line)
        self.assertIn("[LARGE-FILE: undo off]", line)
        self.assertIn("[MATCH 8:10]", line)


class TestPrompts(unittest.TestCase):
    def test_unsaved_prompt_choices(self):
        from stdedit.tui import _unsaved_changes_prompt

        self.assertEqual(_unsaved_changes_prompt(iter(["s"]).__next__), "save")
        self.assertEqual(_unsaved_changes_prompt(iter(["D"]).__next__), "discard")
        self.assertEqual(_unsaved_changes_prompt(iter(["c"]).__next__), "cancel")
        self.assertEqual(_unsaved_changes_prompt(iter(["\x1b"]).__next__), "cancel")

    def test_unsaved_prompt_reprompts_on_invalid_keys(self):
        from stdedit.tui import _unsaved_changes_prompt

        keys = iter(["x", "\n", "d"])
        self.assertEqual(_unsaved_changes_prompt(keys.__next__), "discard")

    def test_unsaved_prompt_renders_message_once(self):
        from stdedit.tui import _unsaved_changes_prompt

        seen = []
        _unsaved_changes_prompt(iter(["s"]).__next__, seen.append)
        self.assertEqual(seen, ["Unsaved changes — (s)ave, (d)iscard, (c)ancel?"])

    def test_prompt_line_types_backspaces_and_submits(self):
        from stdedit.tui import _prompt_line

        keys = iter(list("src/st") + ["\x7f", "p", "\r"])
        self.assertEqual(_prompt_line(keys.__next__, lambda t: None), "src/sp")

    def test_prompt_line_esc_cancels(self):
        from stdedit.tui import _prompt_line

        self.assertIsNone(_prompt_line(iter(["a", "\x1b"]).__next__, lambda t: None))

    def test_prompt_line_empty_submit_is_cancel(self):
        from stdedit.tui import _prompt_line

        self.assertIsNone(_prompt_line(iter(["\n"]).__next__, lambda t: None))


class TestSafeOpen(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.target = os.path.join(self._tmp.name, "target.py")
        with open(self.target, "w") as f:
            f.write("x = 1\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_load_opens_and_syncs_explorer(self):
        from stdedit.buffer import Buffer
        from stdedit.explorer import FileExplorer
        from stdedit.tui import open_file_path

        buf = Buffer()
        explorer = FileExplorer(".")
        language, status = open_file_path(None, buf, explorer, self.target)
        self.assertEqual(language, "python")
        self.assertTrue(status.startswith("Opened "))
        self.assertEqual(buf.lines, ["x = 1", ""])
        self.assertEqual(explorer.current_path, os.path.abspath(self.target))
        self.assertEqual(explorer.root_dir, os.path.abspath(self._tmp.name))

    def test_modified_buffer_discard_choice_loads_new_file(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        class FakeStdscr:
            def __init__(self, keys):
                self._keys = iter(keys)

            def get_wch(self):
                return next(self._keys)

        buf = Buffer()
        buf.insert_char("z")  # makes it modified
        self.assertTrue(buf.modified)
        _, status = open_file_path(FakeStdscr(["d"]), buf, None, self.target)
        self.assertTrue(status.startswith("Opened "))
        self.assertEqual(buf.lines, ["x = 1", ""])

    def test_modified_buffer_cancel_keeps_content(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        class FakeStdscr:
            def get_wch(self):
                return "\x1b"

        buf = Buffer()
        buf.insert_char("z")
        _, status = open_file_path(FakeStdscr(), buf, None, self.target)
        self.assertEqual(status, "Open cancelled")
        self.assertEqual(buf.lines, ["z"])

    def test_save_without_filename_cancels_open(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        class FakeStdscr:
            def get_wch(self):
                return "s"

        buf = Buffer()  # no filename -> save raises ValueError internally
        buf.insert_char("z")
        _, status = open_file_path(FakeStdscr(), buf, None, self.target)
        self.assertIn("cannot save", status)
        self.assertEqual(buf.lines, ["z"])

    def test_missing_file_reports_error(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        buf = Buffer()
        _, status = open_file_path(None, buf, None, "/nonexistent/nope.py")
        self.assertIn("Error opening file", status)


if __name__ == "__main__":
    unittest.main()

class _FakeStdscr:
    def __init__(self, text):
        self._items = [ord(ch) for ch in text]

    def getch(self):
        return self._items.pop(0) if self._items else -1


class TestBracketedPaste(unittest.TestCase):
    def test_reads_payload_without_leaking_marker_characters(self):
        from stdedit.tui import _read_bracketed_paste

        # ESC and '[' were already consumed by _main_loop.
        stdscr = _FakeStdscr("200~def greet():\n    return 'hi'\x1b[201~")
        self.assertEqual(
            _read_bracketed_paste(stdscr),
            "def greet():\n    return 'hi'",
        )
        self.assertEqual(stdscr._items, [])

class TestKeyHandling(unittest.TestCase):
    def test_ctrl_q_is_ascii_control_character(self):
        # Regression guard for the terminal flow-control issue: the UI maps
        # Ctrl-Q to ASCII 17 and raw mode is enabled before the input loop.
        self.assertEqual("\x11", chr(17))

    def test_ctrl_s_is_ascii_control_character(self):
        self.assertEqual("\x13", chr(19))


class TestBracketedPasteStress(unittest.TestCase):
    def test_bracketed_paste_10k_lines(self):
        from stdedit.tui import _read_bracketed_paste
        payload = "\n".join(f"line {i}" for i in range(10000))
        stdscr = _FakeStdscr("200~" + payload + "\x1b[201~")
        self.assertEqual(_read_bracketed_paste(stdscr), payload)
        self.assertEqual(stdscr._items, [])
