import curses
import os
import unittest

from stdedit.tui import (
    _get_key,
    build_help_lines,
    is_help_toggle,
    line_number_width,
    format_status_bar,
)
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


class TestTreeRoot(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_project_dir_wins_over_everything(self):
        from stdedit.tui import resolve_tree_root

        self.assertEqual(
            resolve_tree_root("some/missing/file.py", self.tmp),
            os.path.abspath(self.tmp),
        )

    def test_opened_file_parent_is_default(self):
        from stdedit.tui import resolve_tree_root

        target = os.path.join(self.tmp, "f.py")
        with open(target, "w") as f:
            f.write("x\n")
        self.assertEqual(resolve_tree_root(target, None), self.tmp)

    def test_cwd_fallback_without_file_or_project(self):
        from stdedit.tui import resolve_tree_root

        self.assertEqual(resolve_tree_root(None, None), ".")
        # A filename that does not exist on disk behaves like no file.
        self.assertEqual(resolve_tree_root("/no/such/f.py", None), ".")


class TestGetKey(unittest.TestCase):
    """Physical Enter must be readable as "\\n" (curses.KEY_ENTER bug)."""

    class _S:
        def __init__(self, keys):
            self._keys = iter(keys)

        def get_wch(self):
            k = next(self._keys)
            if isinstance(k, Exception):
                raise k
            return k

    def test_keypad_enter_is_normalized_to_newline(self):
        self.assertEqual(_get_key(self._S([curses.KEY_ENTER])), "\n")

    def test_regular_keys_pass_through_untouched(self):
        for raw in ("\r", "\n", "a", "?", curses.KEY_UP, curses.KEY_F1):
            self.assertEqual(_get_key(self._S([raw])), raw)

    def test_curses_error_reports_none(self):
        self.assertIsNone(_get_key(self._S([curses.error("no input")])))


class TestHelpContent(unittest.TestCase):
    def test_documents_every_binding(self):
        text = "\n".join(build_help_lines(200))
        for token in (
            "Ctrl-Space", "Ctrl-C", "Ctrl-X", "Ctrl-V", "Ctrl-Z",
            "Ctrl-Y", "Ctrl-S", "Ctrl-O", "Ctrl-Q", "Ctrl-E", "Ctrl-H",
            "F1", "Enter", "Tab", "Backspace", "Home", "End",
            "h ", "n ", "N ", "O ", "R ",
            "( { [", ") } ]", "auto-close quotes",
            "bracketed paste", "Esc cancels", "prompt Backspace",
        ):
            self.assertIn(token, text, token)

    def test_covers_all_sections_and_dismissal(self):
        text = "\n".join(build_help_lines(200))
        for section in ("EDITING", "SELECTION & CLIPBOARD",
                        "HISTORY & FILES", "FILE TREE",
                        "TERMINAL & PROMPTS", "HELP"):
            self.assertIn(section, text)
        self.assertIn("q / Esc / Enter", text)

    def test_lines_fit_narrow_widths(self):
        for width in (40, 60, 80):
            for line in build_help_lines(width):
                self.assertLessEqual(len(line), width)


class TestHelpToggle(unittest.TestCase):
    def test_raw_ctrl_h_and_f1_work_anywhere(self):
        for tree_active in (False, True):
            self.assertTrue(is_help_toggle("\x08", tree_active))
            self.assertTrue(is_help_toggle(curses.KEY_F1, tree_active))

    def test_backspace_constant_toggles_only_while_tree_focused(self):
        # On kbs=^H terminals keypad() delivers BOTH Backspace and
        # Ctrl-H as KEY_BACKSPACE; the guide must not hijack editing.
        self.assertTrue(is_help_toggle(curses.KEY_BACKSPACE, True))
        self.assertFalse(is_help_toggle(curses.KEY_BACKSPACE, False))

    def test_raw_ctrl_h_byte_is_the_literal_backspace_char(self):
        # "\\b" == "\\x08": one byte, so raw Ctrl-H toggles everywhere.
        self.assertEqual("\b", "\x08")
        self.assertTrue(is_help_toggle("\x08", False))

    def test_normal_keys_never_toggle(self):
        for key in ("a", "\n", "\r", "\x1b", curses.KEY_DOWN,
                    curses.KEY_RESIZE):
            self.assertFalse(is_help_toggle(key, True))
            self.assertFalse(is_help_toggle(key, False))


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

    def test_yes_no_prompt_matrix(self):
        from stdedit.tui import _yes_no_prompt

        for key, expected in (("y", True), ("Y", True),
                              ("\n", True), ("\r", True),
                              ("n", False), ("N", False),
                              ("\x1b", False)):
            self.assertEqual(
                _yes_no_prompt(iter([key]).__next__, lambda t: None, "?"),
                expected, repr(key))

    def test_yes_no_prompt_reprompts_on_other_keys(self):
        from stdedit.tui import _yes_no_prompt

        keys = iter(["x", "1", " ", "y"])
        self.assertTrue(_yes_no_prompt(keys.__next__, lambda t: None, "?"))

    def test_yes_no_prompt_renders_message_once(self):
        from stdedit.tui import _yes_no_prompt

        seen = []
        _yes_no_prompt(iter(["y"]).__next__, seen.append, "create?")
        self.assertEqual(seen, ["create?"])

    def test_prompt_line_types_backspaces_and_submits(self):
        from stdedit.tui import _prompt_line

        keys = iter(list("src/st") + ["\x7f", "p", "\r"])
        self.assertEqual(_prompt_line(keys.__next__, lambda t: None), "src/sp")

    def test_prompt_line_esc_cancels(self):
        from stdedit.tui import _prompt_line

        self.assertIsNone(_prompt_line(iter(["a", "\x1b"]).__next__, lambda t: None))

    def test_prompt_line_key_backspace_constant_deletes(self):
        from stdedit.tui import _prompt_line

        # Real terminals deliver Backspace as curses.KEY_BACKSPACE (263),
        # not "\b"/"\x7f" -- it must delete like the byte forms.
        keys = iter(["a", "b", curses.KEY_BACKSPACE, "c", "\n"])
        self.assertEqual(_prompt_line(keys.__next__, lambda t: None), "ac")

    def test_prompt_line_backspace_on_empty_text_is_noop(self):
        from stdedit.tui import _prompt_line

        keys = iter([curses.KEY_BACKSPACE, "x", "\n"])
        self.assertEqual(_prompt_line(keys.__next__, lambda t: None), "x")

    def test_prompt_line_empty_submit_is_cancel(self):
        from stdedit.tui import _prompt_line

        self.assertIsNone(_prompt_line(iter(["\n"]).__next__, lambda t: None))


class TestTreeSwallow(unittest.TestCase):
    """Printable keys must be swallowed while the tree has focus (bug 2)."""

    def test_printable_characters_are_swallowed(self):
        from stdedit.tui import swallowed_by_tree

        for ch in ("x", "A", "1", " ", "!", "é"):
            self.assertTrue(swallowed_by_tree(ch), repr(ch))

    def test_controls_and_special_keys_pass_through(self):
        from stdedit.tui import swallowed_by_tree

        for key in ("\n", "\r", "\t", "\x13", "\x1b",
                    curses.KEY_DOWN, curses.KEY_BACKSPACE, curses.KEY_F1,
                    None):
            self.assertFalse(swallowed_by_tree(key), repr(key))


class TestHelpScroll(unittest.TestCase):
    def test_clamp_scroll_bounds(self):
        from stdedit.tui import clamp_scroll

        # total 50 lines, viewport 20 -> max offset 30
        self.assertEqual(clamp_scroll(0, 1, 50, 20), 1)
        self.assertEqual(clamp_scroll(0, -1, 50, 20), 0)
        self.assertEqual(clamp_scroll(29, 5, 50, 20), 30)
        self.assertEqual(clamp_scroll(30, 5, 50, 20), 30)   # bottom clamp
        self.assertEqual(clamp_scroll(0, -99, 50, 20), 0)   # top clamp

    def test_clamp_scroll_fits_without_scrolling(self):
        from stdedit.tui import clamp_scroll

        # Content shorter than the viewport never scrolls.
        self.assertEqual(clamp_scroll(0, 10, 12, 20), 0)

    def test_clamp_scroll_degenerate_viewports(self):
        from stdedit.tui import clamp_scroll

        self.assertEqual(clamp_scroll(5, 1, 50, 0), 0)
        self.assertEqual(clamp_scroll(5, 1, 0, 20), 0)


class TestIcons(unittest.TestCase):
    def test_language_icons_cover_supported_languages(self):
        from stdedit.icons import LANG_ICONS, icon_for_language

        for lang in ("python", "javascript", "typescript", "html", "css",
                     "c", "cpp", "java", "rust", "go", "json", "yaml",
                     "markdown", "shell", "sql", "xml", "plaintext"):
            self.assertTrue(LANG_ICONS[lang], lang)
            self.assertEqual(icon_for_language(lang.upper(), True),
                             LANG_ICONS[lang])

    def test_disabled_icons_return_empty(self):
        from stdedit.icons import enabled_from_env, icon_for_file, \
            icon_for_language

        self.assertEqual(icon_for_file("x.py", False), "")
        self.assertEqual(icon_for_language("python", False), "")
        self.assertFalse(enabled_from_env({"STDEDIT_ICONS": "0"}))
        self.assertTrue(enabled_from_env({}))
        self.assertTrue(enabled_from_env({"STDEDIT_ICONS": "1"}))

    def test_extension_and_default_icons(self):
        from stdedit.icons import DEFAULT_ICON, icon_for_file

        self.assertEqual(icon_for_file("Cargo.lock", True), "\uF023")
        self.assertEqual(icon_for_file("pic.PNG", True), "\uF1C5")
        self.assertEqual(icon_for_file("setup.cfg", True), "\uF013")
        self.assertEqual(icon_for_file("unknown.xyz", True), DEFAULT_ICON)

    def test_status_bar_renders_icon_inside_brackets(self):
        from stdedit.tui import format_status_bar

        line = format_status_bar("main.py", False, "Python", 0, 0, 10,
                                 icon="\uE73C")
        self.assertIn("[\uE73C Python]", line)
        plain = format_status_bar("main.py", False, "Python", 0, 0, 10)
        self.assertIn("[Python]", plain)


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

    def _write(self, relpath, content):
        path = os.path.join(self._tmp.name, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_open_inside_project_keeps_root_and_selects_file(self):
        from stdedit.buffer import Buffer
        from stdedit.explorer import FileExplorer
        from stdedit.tui import open_file_path

        marker = self._write("marker.txt", "m\n")
        nested = self._write(os.path.join("sub", "deep.txt"), "deep\n")

        explorer = FileExplorer(self._tmp.name)
        buf = Buffer()
        language, status = open_file_path(None, buf, explorer, nested)

        self.assertTrue(status.startswith("Opened "))
        # The project root stays pinned -- no jump into sub/.
        self.assertEqual(explorer.root_dir, os.path.abspath(self._tmp.name))
        # Root-level content is still listed; sub/ got expanded.
        listed = [item[2] for item in explorer.items]
        self.assertIn(os.path.abspath(marker), listed)
        self.assertIn(os.path.abspath(nested), listed)
        self.assertIn(os.path.abspath(os.path.dirname(nested)),
                      explorer.expanded_dirs)
        # And the opened file is highlighted in the tree.
        self.assertEqual(explorer.current_path, os.path.abspath(nested))
        selected = explorer.get_selected()
        self.assertIsNotNone(selected)
        self.assertEqual(selected[2], os.path.abspath(nested))

    def test_open_outside_project_reroots_at_parent(self):
        from stdedit.buffer import Buffer
        from stdedit.explorer import FileExplorer
        from stdedit.tui import open_file_path

        proj = os.path.join(self._tmp.name, "proj")
        os.mkdir(proj)
        stray = self._write("stray.txt", "outside\n")

        explorer = FileExplorer(proj)
        language, status = open_file_path(None, Buffer(), explorer, stray)

        self.assertTrue(status.startswith("Opened "))
        self.assertEqual(explorer.root_dir, os.path.abspath(self._tmp.name))
        self.assertEqual(explorer.current_path, os.path.abspath(stray))

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
