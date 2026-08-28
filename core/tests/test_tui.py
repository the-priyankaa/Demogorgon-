import curses
import os
import unittest

from stdedit.tui import (
    _get_key,
    build_help_lines,
    is_help_toggle,
    line_number_width,
    format_status_bar,
    _lines_fingerprint,
    _insert_text,
    _ghost_wanted,
    _draw_ghost,
    _draw_suggest_overlay,
    _fetch_ghost_text,
    _draw_settings_overlay,
)
from stdedit.buffer import Buffer
from stdedit import suggest


class TestLineNumbers(unittest.TestCase):
    def test_line_number_width_is_stable_for_small_files(self):
        self.assertEqual(line_number_width(1), 2)
        self.assertEqual(line_number_width(9), 2)
        self.assertEqual(line_number_width(10), 2)

    def test_line_number_width_grows_with_document(self):
        self.assertEqual(line_number_width(99), 2)
        self.assertEqual(line_number_width(100), 3)
        self.assertEqual(line_number_width(1000), 4)


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
                        "GIT STATUS", "SOURCE CONTROL",
                        "DIFF VIEWER", "SETTINGS", "MOUSE",
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

    def test_backspace_constant_never_toggles(self):
        # Backspace should never open the help overlay.
        self.assertFalse(is_help_toggle(curses.KEY_BACKSPACE, True))
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


class TestSearchIntegration(unittest.TestCase):
    def test_search_mode_enter_exit(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        self.assertTrue(e.searching)
        e.exit_search()
        self.assertFalse(e.searching)

    def test_search_results_replace_items_in_draw(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        e.search("__init__")
        self.assertTrue(len(e.search_results) > 0)
        # All results should be flat (depth=0)
        for item in e.search_results:
            self.assertEqual(item[0], 0)

    def test_search_query_updates(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        e.search("test")
        self.assertEqual(e.search_query, "test")
        e.search("test_")
        self.assertEqual(e.search_query, "test_")

    def test_exit_search_clears_state(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        e.search("something")
        e.exit_search()
        self.assertEqual(e.search_query, "")
        self.assertEqual(e.search_results, [])


class TestMouseMultiClick(unittest.TestCase):
    def test_scroll_wheel_up(self):
        import curses
        from stdedit.buffer import Buffer
        from stdedit.tui import _mouse_dragging, _last_click_time, _click_count
        b = Buffer()
        b.lines = [f"line{i}" for i in range(50)]
        b.move_to(0, 25)
        b.update_scroll(20, 80)
        b.move_cursor(dy=-3)
        b.update_scroll(20, 80)
        self.assertLess(b.cursor_y, 25)

    def test_scroll_wheel_down(self):
        from stdedit.buffer import Buffer
        b = Buffer()
        b.lines = [f"line{i}" for i in range(50)]
        b.move_to(0, 0)
        b.update_scroll(20, 80)
        b.move_cursor(dy=3)
        b.update_scroll(20, 80)
        self.assertGreater(b.cursor_y, 0)

    def test_select_word_and_line(self):
        from stdedit.buffer import Buffer
        b = Buffer()
        b.lines = ["hello world"]
        b.select_word_at(0, 2)
        self.assertEqual(b.selected_text(), "hello")
        b.select_line_at(0)
        self.assertEqual(b.selected_text(), "hello world")


class TestFontFamily(unittest.TestCase):
    def test_settings_panel_includes_font_keys(self):
        from stdedit import settings
        keys = [k for k, _ in settings.LABELS if k is not None]
        for fk in settings._font_keys:
            self.assertIn(fk, keys)

    def test_apply_font_family_sends_osc(self):
        from stdedit import tui
        import io
        import sys
        from unittest.mock import patch
        from stdedit import settings
        fake = io.StringIO()
        with patch.object(sys, "stdout", fake):
            tui._apply_font_family()
        output = fake.getvalue()
        self.assertIn("\033]50;", output)
        self.assertIn("\007", output)

    def test_apply_font_family_with_no_font(self):
        from stdedit import tui
        from stdedit import settings
        for fk in settings._font_keys:
            settings.set(fk, False)
        import io
        import sys
        from unittest.mock import patch
        fake = io.StringIO()
        with patch.object(sys, "stdout", fake):
            tui._apply_font_family()
        self.assertEqual(fake.getvalue(), "")


class TestSettingsDropdown(unittest.TestCase):
    def setUp(self):
        from stdedit import settings
        self.settings = settings
        settings._settings = dict(settings._DEFAULTS)

    def test_all_collapsed_nav_is_only_headers(self):
        from stdedit.tui import _settings_nav_indices
        from stdedit import settings
        headers = [i for i, (k, _) in enumerate(settings.LABELS)
                   if k is None and settings.LABELS[i][1]]
        self.assertEqual(_settings_nav_indices({}), headers)
        self.assertEqual(len(headers), 4)  # AUTO-SAVE, THEME, FONT FAMILY, SUGGESTIONS

    def test_expanded_section_shows_items(self):
        from stdedit.tui import _settings_nav_indices
        from stdedit import settings
        theme_keys = set(settings._theme_keys)
        nav = set(_settings_nav_indices({"THEME": True}))
        self.assertGreater(len(nav), 10)  # headers + all 15 themes
        for i, (k, _) in enumerate(settings.LABELS):
            if k in theme_keys:
                self.assertIn(i, nav, f"{k} should be listed")
            elif k is not None:
                self.assertNotIn(i, nav, f"{k} should be hidden")

    def test_headers_always_navigable(self):
        from stdedit.tui import _settings_nav_indices
        nav = _settings_nav_indices({"AUTO-SAVE": True, "FONT FAMILY": True})
        headers = {"AUTO-SAVE", "THEME", "FONT FAMILY"}
        for i in nav:
            if self.settings.LABELS[i][0] is None:
                headers.discard(self.settings.LABELS[i][1])
        self.assertEqual(headers, set())

    def test_display_rows_all_collapsed(self):
        from stdedit.tui import _settings_display_rows
        rows = _settings_display_rows({})
        kinds = [r[0] for r in rows]
        self.assertEqual(kinds, ["header", "header", "header", "header"])
        for r in rows:
            self.assertEqual(r[0], "header")

    def test_display_rows_expanded_adds_items_and_separator(self):
        from stdedit.tui import _settings_display_rows
        rows = _settings_display_rows({"THEME": True})
        kinds = [r[0] for r in rows]
        self.assertEqual(kinds.count("header"), 4)
        self.assertEqual(kinds.count("item"), len(self.settings._theme_keys))
        self.assertEqual(kinds.count("separator"), 1)

    def test_display_layout_selection_centered_expanded(self):
        from stdedit.tui import _settings_display_rows
        from stdedit.tui import _settings_display_layout
        rows = _settings_display_rows({"THEME": True})
        item_idx = next(r[4] for r in rows if r[0] == "item")
        _, start = _settings_display_layout({"THEME": True}, item_idx, 10)
        # The selected item is visible within the viewport.
        sel_pos = next(i for i, r in enumerate(rows) if r[0] == "item" and r[4] == item_idx)
        self.assertLessEqual(start, sel_pos)
        self.assertLess(sel_pos - start, 10)


class TestSettingsAccordion(unittest.TestCase):
    def setUp(self):
        from stdedit import settings
        self.settings = settings
        settings._settings = dict(settings._DEFAULTS)

    def test_close_others_keeps_one(self):
        from stdedit.tui import _settings_close_others
        exp = {"AUTO-SAVE": True, "THEME": True, "FONT FAMILY": True}
        _settings_close_others(exp, "THEME")
        self.assertEqual(exp, {"AUTO-SAVE": False, "THEME": True,
                                 "FONT FAMILY": False, "SUGGESTIONS": False})

    def test_close_others_none_clears_all(self):
        from stdedit.tui import _settings_close_others
        exp = {"AUTO-SAVE": True, "THEME": True, "FONT FAMILY": True}
        _settings_close_others(exp, None)
        self.assertFalse(any(exp.values()))

    def test_navigation_to_header_closes_previous(self):
        """
        With THEME expanded, navigating Down to the FONT FAMILY header must
        collapse THEME (single-open accordion).
        """
        from stdedit.tui import _settings_nav_indices, _settings_close_others
        from stdedit import settings
        exp = {"THEME": True}
        settings_idx = _settings_nav_indices(exp)[0]  # AUTO-SAVE header
        for _ in range(30):
            nav = _settings_nav_indices(exp)
            cur = nav.index(settings_idx) if settings_idx in nav else 0
            settings_idx = nav[(cur + 1) % len(nav)]
            if settings.LABELS[settings_idx][0] is None:
                _settings_close_others(exp, settings.LABELS[settings_idx][1])
                if settings.LABELS[settings_idx][1] == "FONT FAMILY":
                    break
        self.assertEqual(settings.LABELS[settings_idx][1], "FONT FAMILY")
        self.assertFalse(exp["THEME"])

    def test_open_one_after_heading_to_another(self):
        from stdedit.tui import _settings_close_others
        exp = {}
        _settings_close_others(exp, "THEME")
        exp["THEME"] = True
        _settings_close_others(exp, "FONT FAMILY")
        exp["FONT FAMILY"] = True
        self.assertEqual(exp["THEME"], False)
        self.assertEqual(exp["FONT FAMILY"], True)

    def test_suggestions_render_as_mutually_exclusive_radios(self):
        """Expanded SUGGESTIONS shows (x)/ ( ) radio rows, Off on by default."""
        from stdedit import settings
        settings._settings = dict(settings._DEFAULTS)

        class FakeScr:
            def __init__(self):
                self.lines = []

            def getmaxyx(self):
                return (24, 80)

            def addstr(self, row, col, text, attr):
                self.lines.append(text)

        s = FakeScr()
        _draw_settings_overlay(s, 0, 30, {"SUGGESTIONS": True})
        joined = "\n".join(s.lines)
        self.assertIn("(x) Suggestions: off", joined)
        self.assertIn("( ) Auto-suggest", joined)
        self.assertIn("( ) AI inline (Codeium)", joined)

    def test_suggestions_radio_marks_only_active(self):
        """With Auto-suggest selected, only its radio row is marked (x)."""
        from stdedit import settings
        settings._settings["suggestions_off"] = False
        settings._settings["suggestions_on"] = True
        settings._settings["codeium_on"] = False

        class FakeScr:
            def __init__(self):
                self.lines = []

            def getmaxyx(self):
                return (24, 80)

            def addstr(self, row, col, text, attr):
                self.lines.append(text)

        s = FakeScr()
        _draw_settings_overlay(s, 0, 30, {"SUGGESTIONS": True})
        joined = "\n".join(s.lines)
        self.assertIn("( ) Suggestions: off", joined)
        self.assertIn("(x) Auto-suggest", joined)
        self.assertIn("( ) AI inline (Codeium)", joined)


class TestQuitDialog(unittest.TestCase):
    def test_choices_unmodified(self):
        from stdedit.tui import _quit_dialog_choices
        self.assertEqual(_quit_dialog_choices(False, True),
                         [("Quit", "quit"), ("Cancel", "cancel")])
        self.assertEqual(_quit_dialog_choices(False, False),
                         [("Quit", "quit"), ("Cancel", "cancel")])

    def test_choices_modified_with_save(self):
        from stdedit.tui import _quit_dialog_choices
        self.assertEqual(_quit_dialog_choices(True, True),
                         [("Save & Quit", "save"), ("Discard & Quit", "discard"),
                          ("Cancel", "cancel")])

    def test_choices_modified_no_save(self):
        from stdedit.tui import _quit_dialog_choices
        self.assertEqual(_quit_dialog_choices(True, False),
                         [("Discard & Quit", "discard"), ("Cancel", "cancel")])

    def test_step_navigation_wraps(self):
        from stdedit.tui import _quit_dialog_choices, _quit_dialog_step
        choices = _quit_dialog_choices(True, True)
        sel, action = _quit_dialog_step(curses.KEY_LEFT, 0, choices)
        self.assertEqual(sel, len(choices) - 1)
        self.assertIsNone(action)
        sel, action = _quit_dialog_step(curses.KEY_RIGHT, len(choices) - 1, choices)
        self.assertEqual(sel, 0)
        self.assertIsNone(action)

    def test_step_enter_activates_focused(self):
        from stdedit.tui import _quit_dialog_choices, _quit_dialog_step
        choices = _quit_dialog_choices(True, True)
        self.assertEqual(_quit_dialog_step("\n", 1, choices)[1], "discard")
        self.assertEqual(_quit_dialog_step(" ", len(choices) - 1, choices)[1], "cancel")

    def test_step_shortcuts(self):
        from stdedit.tui import _quit_dialog_choices, _quit_dialog_step
        choices = _quit_dialog_choices(True, True)
        self.assertEqual(_quit_dialog_step("s", 0, choices)[1], "save")
        self.assertEqual(_quit_dialog_step("d", 0, choices)[1], "discard")
        self.assertEqual(_quit_dialog_step("q", 0, choices)[1], "discard")
        self.assertEqual(_quit_dialog_step("\x1b", 0, choices)[1], "cancel")

    def test_confirm_dialog_default_is_cancel(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["\n"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      True, True)
        self.assertEqual(result, "cancel")

    def test_confirm_dialog_quit_shortcut(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["q"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      False, True)
        self.assertEqual(result, "quit")

    def test_confirm_dialog_save_shortcut(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["s"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      True, True)
        self.assertEqual(result, "save")

    def test_confirm_dialog_esc_cancels(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["\x1b"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      True, False)
        self.assertEqual(result, "cancel")

    def test_confirm_dialog_select_then_enter(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter([curses.KEY_LEFT, "\n"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      False, True)
        self.assertEqual(result, "quit")

    def test_draw_quit_dialog_no_error(self):
        from stdedit.tui import _draw_quit_dialog, _quit_dialog_choices

        class FakeScr:
            def __init__(self):
                self.calls = []

            def getmaxyx(self):
                return (24, 80)

            def addstr(self, row, col, text, attr):
                self.calls.append((row, col, text))

        s = FakeScr()
        choices = _quit_dialog_choices(True, True)
        _draw_quit_dialog(s, "Quit stdedit?", ["Unsaved."], choices, 1)
        joined = "".join(t for _, _, t in s.calls)
        self.assertIn("[ Save & Quit ]", joined)
        self.assertIn("[ Discard & Quit ]", joined)
        self.assertIn("[ Cancel ]", joined)
        self.assertIn("\u250c", joined)
        self.assertIn("\u2518", joined)


class TestFingerprint(unittest.TestCase):
    def test_changes_on_edit(self):
        lines = ["foo", "bar baz"]
        self.assertNotEqual(_lines_fingerprint(lines),
                            _lines_fingerprint(lines + [""]))
        self.assertEqual(_lines_fingerprint(lines),
                         _lines_fingerprint(list(lines)))

    def test_scannable_window_only(self):
        base = [""] * 3000
        a = _lines_fingerprint(base)
        base[2999] = "changed"
        self.assertEqual(a, _lines_fingerprint(base))


class TestInsertText(unittest.TestCase):
    def make_buffer(self, text="", row=0, col=0):
        b = Buffer()
        if text:
            b.lines = text.split("\n")
        b.cursor_y = row
        b.cursor_x = col
        return b

    def test_single_line(self):
        b = self.make_buffer("abc", 0, 1)
        _insert_text(b, "XY")
        self.assertEqual(b.lines[0], "aXYbc")
        self.assertEqual((b.cursor_y, b.cursor_x), (0, 3))
        self.assertTrue(b.modified)

    def test_multi_line(self):
        b = self.make_buffer("abc\ndef", 0, 1)
        _insert_text(b, "X\nYZ")
        self.assertEqual(list(b.lines), ["aX", "YZbc", "def"])
        self.assertEqual((b.cursor_y, b.cursor_x), (1, 2))

    def test_multi_line_empty_tail_preserved(self):
        b = self.make_buffer("abc", 0, 3)
        _insert_text(b, "1\n2\n3")
        self.assertEqual(list(b.lines), ["abc1", "2", "3"])
        self.assertEqual((b.cursor_y, b.cursor_x), (2, 1))

    def test_empty_noop(self):
        b = self.make_buffer("abc", 0, 1)
        _insert_text(b, "")
        self.assertEqual(list(b.lines), ["abc"])
        self.assertFalse(b.modified)


class TestGhostWanted(unittest.TestCase):
    def make_buffer(self, text, col):
        b = Buffer()
        b.lines = [text]
        b.cursor_y = 0
        b.cursor_x = col
        return b

    def test_at_end_of_line(self):
        self.assertTrue(_ghost_wanted(self.make_buffer("print", 5)))

    def test_after_identifier_inside_line(self):
        self.assertFalse(_ghost_wanted(self.make_buffer("print(x)", 3)))

    def test_at_column_zero(self):
        self.assertTrue(_ghost_wanted(self.make_buffer("xy", 0)))

    def test_after_space(self):
        self.assertTrue(_ghost_wanted(self.make_buffer("a b", 2)))


class TestDrawGhost(unittest.TestCase):
    class FakeScr:
        def __init__(self):
            self.calls = []

        def addstr(self, row, col, text, attr):
            self.calls.append((row, col, text, attr))

    def make_ghost(self, text, y=0, x=0):
        import stdedit.codeium as codeium
        return codeium.Completion(text, y, x)

    def test_draws_at_cursor_when_anchored(self):
        g = self.make_ghost(" hello", 0, 1)
        s = self.FakeScr()
        b = Buffer()
        b.lines = ["a"]
        b.cursor_y = 0
        b.cursor_x = 1
        b.scroll_y = 0
        b.scroll_x = 0
        _draw_ghost(s, b, g, 0, 3, 40)
        self.assertEqual(s.calls, [(0, 4, " hello", curses.A_DIM)])

    def test_stale_anchor_skipped(self):
        g = self.make_ghost(" hi", 0, 1)
        s = self.FakeScr()
        b = Buffer()
        b.lines = ["aa"]
        b.cursor_y = 0
        b.cursor_x = 2
        _draw_ghost(s, b, g, 0, 3, 40)
        self.assertEqual(s.calls, [])

    def test_mid_line_skipped(self):
        g = self.make_ghost(" hi", 0, 1)
        s = self.FakeScr()
        b = Buffer()
        b.lines = ["abc"]
        b.cursor_x = 1
        _draw_ghost(s, b, g, 0, 3, 40)
        self.assertEqual(s.calls, [])


class TestDrawSuggestOverlay(unittest.TestCase):
    class FakeScr:
        def __init__(self):
            self.calls = []

        def addstr(self, row, col, text, attr):
            self.calls.append((row, col, text))

    def test_renders_box_and_candidates(self):
        s = self.FakeScr()
        sug = suggest.Suggestor()
        sug.open("python", {"gamma": 5}, "ga")
        b = Buffer()
        b.lines = ["ga"]
        b.cursor_y = 0
        b.cursor_x = 2
        b.scroll_y = 0
        b.scroll_x = 0
        _draw_suggest_overlay(s, sug, b, 0, 3, 40, 24, 80)
        joined = "".join(t for _, _, t in s.calls)
        self.assertIn("\u250c", joined)
        self.assertIn("\u2518", joined)
        self.assertIn("gamma", joined)

    def test_hidden_popup_noop(self):
        s = self.FakeScr()
        sug = suggest.Suggestor()
        b = Buffer()
        _draw_suggest_overlay(s, sug, b, 0, 3, 40, 24, 80)
        self.assertEqual(s.calls, [])


class TestFetchGhostText(unittest.TestCase):
    def test_fake_ghost_string(self):
        os.environ["STDEDIT_FAKE_GHOST"] = "import math"
        try:
            result = _fetch_ghost_text(None)
            self.assertIsNotNone(result)
            self.assertEqual(result.text, "import math")
        finally:
            del os.environ["STDEDIT_FAKE_GHOST"]

    def test_fake_ghost_none(self):
        os.environ["STDEDIT_FAKE_GHOST"] = "none"
        try:
            self.assertIsNone(_fetch_ghost_text(None))
        finally:
            del os.environ["STDEDIT_FAKE_GHOST"]


if __name__ == "__main__":
    unittest.main()
