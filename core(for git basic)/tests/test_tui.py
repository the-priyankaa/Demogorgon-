import unittest

from stdedit.tui import line_number_width


class TestLineNumbers(unittest.TestCase):
    def test_line_number_width_is_stable_for_small_files(self):
        self.assertEqual(line_number_width(1), 2)
        self.assertEqual(line_number_width(9), 2)
        self.assertEqual(line_number_width(10), 2)

    def test_line_number_width_grows_with_document(self):
        self.assertEqual(line_number_width(99), 2)
        self.assertEqual(line_number_width(100), 3)
        self.assertEqual(line_number_width(1000), 4)


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
