"""
tui.py — curses front end. OWNER: Person A.

Phase 1 targets (per plan):
  - curses init, raw mode, color pairs, resize loop, minimal keymap
Phase 2 targets:
  - line numbers, status bar (file/lang/position), word-wrap toggle
Phase 3 targets:
  - multiple buffers/tabs, jump-to-line, autosave, Ctrl-S save

Contract with buffer.py (Person B):
  - Buffer is UI-agnostic. Drive it via:
      buf.move_cursor(dx, dy, extend_selection=bool)
      buf.insert_char(ch) / insert_newline() / backspace() / delete_char()
      buf.insert_tab() / indent_selection() / dedent_selection()
      buf.copy() / cut() / paste()
      buf.undo() / buf.redo()
      buf.update_scroll(viewport_height, viewport_width)  # call every frame
  - Read buf.lines, buf.cursor_x/cursor_y, buf.scroll_x/scroll_y to render.
  - buf.modified tells you whether to prompt on quit / show a dirty marker.

This stub just proves the wiring end-to-end (Phase 1 gate: open -> move ->
edit -> save -> exit) without real curses, so `make run` works on day 0.
Replace `run()` with a real curses.wrapper(...) loop.
"""

from __future__ import annotations

import curses
import sys

from .buffer import Buffer
from .languages import schema
from .perf import PerfMeter
from .extensions import ExtensionAPI, load_extensions, load_requested_extensions

_COLOR_PAIRS = {
    "keyword": 1,
    "string": 2,
    "comment": 3,
    "number": 4,
}

_PASTE_START = "\x1b[200~"
_PASTE_END = "\x1b[201~"


class EditorContext:
    """Small extension-facing editor context shared with the core TUI."""
    def __init__(self, buf: Buffer, stdscr=None):
        self.buffer = buf
        self.stdscr = stdscr
        self.status = ""
        self.quit_requested = False


def run(buf: Buffer, load_user_extensions: bool = False, extension_names=None, extension_files=None, load_all_extensions: bool = False) -> None:
    """Entry point. Wraps curses so the terminal is restored on crash/exit."""
    curses.wrapper(_curses_main, buf, load_user_extensions, extension_names or [], extension_files or [], load_all_extensions)


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_COLOR_PAIRS["keyword"], curses.COLOR_MAGENTA, -1)
    curses.init_pair(_COLOR_PAIRS["string"], curses.COLOR_GREEN, -1)
    curses.init_pair(_COLOR_PAIRS["comment"], curses.COLOR_CYAN, -1)
    curses.init_pair(_COLOR_PAIRS["number"], curses.COLOR_YELLOW, -1)


def _enable_bracketed_paste() -> None:
    """Ask the terminal to wrap pasted text in ESC[200~ ... ESC[201~ markers
    instead of streaming it in as if it were typed. Without this, a paste of
    already-indented multi-line text gets fed through the same path as real
    keystrokes, so every embedded newline triggers auto-indent *on top of*
    the indentation already in the pasted text — indentation doubles every
    line. This is the same mechanism vim/nano/VS Code's terminal use."""
    try:
        sys.stdout.write("\x1b[?2004h")
        sys.stdout.flush()
    except Exception:
        pass


def _disable_bracketed_paste() -> None:
    try:
        sys.stdout.write("\x1b[?2004l")
        sys.stdout.flush()
    except Exception:
        pass


def _read_bracketed_paste(stdscr) -> str:
    """Read a terminal bracketed-paste payload.

    The main loop has already consumed ESC and the following ``[`` before
    calling this function, so only ``200~`` remains in the start marker.
    Previously this function tried to consume ``[200~`` again. That consumed
    the first character (``2``) while expecting ``[`` and returned early,
    leaving ``00~`` in curses' input queue. The remaining pasted newlines were
    then treated as real Enter keypresses, so auto-indent ran on every pasted
    line and indentation grew recursively.
    """
    for expected in "200~":
        ch = stdscr.getch()
        if ch == -1 or chr(ch) != expected:
            return ""  # malformed sequence; bail out safely

    content = []
    end_marker = _PASTE_END
    tail = []
    while True:
        ch = stdscr.getch()
        if ch == -1:
            continue
        tail.append(chr(ch))
        if len(tail) > len(end_marker):
            content.append(tail.pop(0))
        if "".join(tail) == end_marker:
            return "".join(content)
        if len(content) + len(tail) > 2_000_000:  # sanity cap
            content.extend(tail)
            return "".join(content)


def _curses_main(stdscr, buf: Buffer, load_user_extensions: bool = False, extension_names=None, extension_files=None, load_all_extensions: bool = False) -> None:
    """
    TEMPORARY minimal UI — just enough to test buffer.py interactively.
    Person A will replace this with the real thing (line numbers, status
    bar, word-wrap, tabs, etc. per the plan). Keymap here is intentionally
    small: arrows, typing, backspace/delete, ctrl-s save, ctrl-z/y undo/redo,
    ctrl-q quit.
    """
    # Raw mode is required for reliable editor control keys (Ctrl-Q, Ctrl-S,
    # Ctrl-Z, etc.). In normal cbreak mode the terminal driver may consume
    # flow-control keys such as Ctrl-S/Ctrl-Q before curses receives them.
    # curses.wrapper() still restores the terminal state on exit.
    curses.raw()
    curses.noecho()
    curses.curs_set(1)
    stdscr.keypad(True)
    _init_colors()
    _enable_bracketed_paste()

    language = schema.detect_language(buf.filename or "")
    selecting = False
    meter = PerfMeter(interval=0.5)
    editor = EditorContext(buf, stdscr)
    extensions = ExtensionAPI(editor)
    if load_all_extensions or load_user_extensions:
        loaded, extension_errors = load_extensions(extensions)
    elif extension_names or extension_files:
        loaded, extension_errors = load_requested_extensions(extensions, extension_names or [], extension_files or [])
    else:
        loaded, extension_errors = [], []
    extensions.startup()

    try:
        status = f"Loaded extensions: {', '.join(loaded)}" if loaded else ""
        if extension_errors:
            status = (status + "  " if status else "") + f"{len(extension_errors)} extension error(s)"
        _main_loop(stdscr, buf, language, status, selecting, meter, extensions, editor)
    finally:
        extensions.shutdown()
        _disable_bracketed_paste()


def _main_loop(stdscr, buf: Buffer, language: str, status: str, selecting: bool, meter: PerfMeter, extensions: ExtensionAPI, editor: EditorContext) -> None:
    while True:
        frame_started = meter.frame_start()
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        text_height = height - 1  # reserve last row for status line
        gutter_width = line_number_width(len(buf.lines)) + 2
        text_width = max(1, width - gutter_width)

        buf.update_scroll(text_height, text_width)

        for row in range(text_height):
            line_idx = buf.scroll_y + row
            _draw_gutter(stdscr, row, line_idx, len(buf.lines), gutter_width)
            if line_idx >= len(buf.lines):
                continue
            line = buf.lines[line_idx]
            _draw_line(
                stdscr, row, line, buf.scroll_x, text_width, language,
                x_offset=gutter_width,
            )
            _highlight_selection(
                stdscr, row, line_idx, line, buf,
                scroll_x=buf.scroll_x, width=text_width, x_offset=gutter_width,
            )

        dirty = "*" if buf.modified else ""
        sel_flag = " [SELECT]" if selecting else ""
        large_flag = " [LARGE-FILE: undo off]" if buf.large_file_mode else ""
        match = buf.matching_bracket()
        match_flag = f" [MATCH {match[0]+1}:{match[1]+1}]" if match else ""
        ext_status = extensions.status()
        info = (
            f"{buf.filename or '[No Name]'}{dirty}  "
            f"[{language}]  Ln {buf.cursor_y+1}, Col {buf.cursor_x+1}{sel_flag}{large_flag}{match_flag}  "
            f"{meter.label()}"
        )
        status_line = (info + ("   " + ext_status if ext_status else "") + "   " + status)[: width - 1]
        try:
            stdscr.addstr(height - 1, 0, status_line, curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.move(
            buf.cursor_y - buf.scroll_y,
            gutter_width + min(buf.cursor_x - buf.scroll_x, max(text_width - 1, 0)),
        )
        stdscr.refresh()
        meter.frame_end(frame_started)
        status = ""

        try:
            key = stdscr.get_wch()
        except curses.error:
            continue

        editor.status = status
        editor.stdscr = stdscr
        if extensions.dispatch_key(key):
            status = editor.status or ""
            continue

        if key == curses.KEY_RESIZE:
            continue
        elif key == "\x1b":  # ESC — check whether this is a bracketed paste
            stdscr.nodelay(True)
            peek = stdscr.getch()
            stdscr.nodelay(False)
            if peek != -1 and chr(peek) == "[":
                pasted = _read_bracketed_paste(stdscr)
                if pasted:
                    if buf.has_selection():
                        buf.delete_selection()
                    buf.paste(pasted)
                    status = f"Pasted {len(pasted)} chars"
            # else: plain ESC / unrecognized escape sequence — ignored for now
        elif key == "\x11":  # Ctrl-Q
            if buf.modified:
                status = "Unsaved changes — Ctrl-Q again to force quit, Ctrl-S to save"
                stdscr.addstr(height - 1, 0, status[: width - 1], curses.A_REVERSE)
                stdscr.refresh()
                confirm = stdscr.get_wch()
                if confirm == "\x11":
                    break
                continue
            break
        elif key == "\x13":  # Ctrl-S
            try:
                buf.save()
                status = f"Saved {buf.filename}"
            except ValueError:
                status = "No filename — run with a file argument to enable saving"
        elif key == "\x1a":  # Ctrl-Z undo
            status = "Undo" if buf.undo() else "Nothing to undo"
        elif key == "\x19":  # Ctrl-Y redo
            status = "Redo" if buf.redo() else "Nothing to redo"
        elif key == "\x00":  # Ctrl-Space: toggle selection mode
            selecting = not selecting
            if not selecting:
                buf.clear_selection()
            status = "Selection ON — move to select, Ctrl-Space again to stop" if selecting else "Selection OFF"
        elif key in ("\x18",):  # Ctrl-X cut
            text = buf.cut()
            selecting = False
            status = f"Cut {len(text)} chars" if text else "Nothing selected to cut"
        elif key == "\x03":  # Ctrl-C copy
            text = buf.copy()
            status = f"Copied {len(text)} chars" if text else "Nothing selected to copy"
        elif key == "\x16":  # Ctrl-V paste (internal clipboard only)
            buf.paste()
            status = "Pasted" if buf.clipboard else "Clipboard empty"
        elif isinstance(key, str) and key in "([{":
            if buf.has_selection():
                buf.delete_selection()
            buf.auto_close_bracket(key)
        elif isinstance(key, str) and key in ")]}":
            if not buf.skip_closer(key):
                buf.insert_char(key)
        elif isinstance(key, str) and key in "\"'" and not buf.has_selection():
            # Quotes use the same lightweight auto-close path as brackets.
            if buf.cursor_x < len(buf.current_line) and buf.current_line[buf.cursor_x] == key:
                buf.cursor_x += 1
            else:
                buf._checkpoint_if_needed("insert_char")
                line = buf.current_line
                buf.lines[buf.cursor_y] = line[:buf.cursor_x] + key + key + line[buf.cursor_x:]
                buf.cursor_x += 1
                buf.modified = True
        elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            buf.backspace()
        elif key == curses.KEY_DC:
            buf.delete_char()
        elif key in ("\n", "\r"):
            buf.insert_newline()
        elif key == "\t":
            buf.insert_tab()
        elif key == curses.KEY_UP:
            buf.move_cursor(dy=-1, extend_selection=selecting)
        elif key == curses.KEY_DOWN:
            buf.move_cursor(dy=1, extend_selection=selecting)
        elif key == curses.KEY_LEFT:
            buf.move_cursor(dx=-1, extend_selection=selecting)
        elif key == curses.KEY_RIGHT:
            buf.move_cursor(dx=1, extend_selection=selecting)
        elif key == curses.KEY_HOME:
            buf.move_to(0, buf.cursor_y, extend_selection=selecting)
        elif key == curses.KEY_END:
            buf.move_to(len(buf.current_line), buf.cursor_y, extend_selection=selecting)
        elif isinstance(key, str) and key.isprintable():
            buf.insert_char(key)
        # anything else (unmapped function keys etc.) is ignored for now


def line_number_width(line_count: int) -> int:
    """Return the number of columns needed for 1-indexed line numbers."""
    return max(2, len(str(max(1, line_count))))


def _draw_gutter(stdscr, row: int, line_idx: int, line_count: int, gutter_width: int) -> None:
    """Draw a stable, 1-indexed line-number gutter.

    The gutter is intentionally outside the horizontally scrolling text area,
    so line numbers never disappear or restart when the text scrolls.
    """
    digits = line_number_width(line_count)
    if line_idx < line_count:
        label = str(line_idx + 1).rjust(digits)
    else:
        label = " " * digits
    label = f"{label} "  # one separator column
    try:
        stdscr.addstr(row, 0, label[:gutter_width], curses.A_DIM)
    except curses.error:
        pass


def _highlight_selection(stdscr, row, line_idx, line, buf, scroll_x, width, x_offset=0) -> None:
    """Re-draw the selected portion of this row in reverse video, if any."""
    if not buf.has_selection():
        return
    ay, ax = buf.selection_anchor
    by, bx = buf.cursor_y, buf.cursor_x
    sy, sx, ey, ex = (ay, ax, by, bx) if (ay, ax) <= (by, bx) else (by, bx, ay, ax)
    if line_idx < sy or line_idx > ey:
        return
    start = sx if line_idx == sy else 0
    end = ex if line_idx == ey else len(line)
    if start >= end:
        return
    _addstr_clip(stdscr, row, start, line[start:end], scroll_x, width, curses.A_REVERSE, x_offset)


def _draw_line(stdscr, row: int, line: str, scroll_x: int, width: int, language: str, x_offset=0) -> None:
    """Draw one line, colorizing tokens returned by the language tokenizer."""
    spans = schema.tokenize(line, language)
    if not spans:
        try:
            stdscr.addstr(row, x_offset, line[scroll_x : scroll_x + width])
        except curses.error:
            pass
        return

    pos = 0
    col = 0
    for start, end, token_type in spans:
        if start > pos:
            col = _addstr_clip(stdscr, row, col, line[pos:start], scroll_x, width, 0, x_offset)
        pair = _COLOR_PAIRS.get(token_type, 0)
        attr = curses.color_pair(pair) if pair else 0
        col = _addstr_clip(stdscr, row, col, line[start:end], scroll_x, width, attr, x_offset)
        pos = end
    if pos < len(line):
        _addstr_clip(stdscr, row, col, line[pos:], scroll_x, width, 0, x_offset)


def _addstr_clip(stdscr, row: int, col: int, text: str, scroll_x: int, width: int, attr: int, x_offset: int = 0) -> int:
    """Write `text` at logical column `col`, respecting horizontal scroll,
    and return the next logical column. Screen writes are clipped to width."""
    next_col = col + len(text)
    screen_start = col - scroll_x
    screen_end = next_col - scroll_x
    if screen_end <= 0 or screen_start >= width:
        return next_col  # entirely off-screen
    visible_start = max(0, -screen_start)
    visible_end = min(len(text), width - screen_start)
    if visible_end > visible_start:
        try:
            stdscr.addstr(row, x_offset + max(0, screen_start), text[visible_start:visible_end], attr)
        except curses.error:
            pass
    return next_col
