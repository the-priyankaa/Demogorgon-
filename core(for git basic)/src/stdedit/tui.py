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
import os
import sys

from .buffer import Buffer
from .languages import schema
from .perf import PerfMeter
from .extensions import ExtensionAPI, load_extensions, load_requested_extensions
from .explorer import FileExplorer
from . import filemanager

_COLOR_PAIRS = {
    "keyword": 1,
    "string": 2,
    "comment": 3,
    "number": 4,
    "function": 5,
    "type": 6,
    "operator": 7,
    "tag": 8,
    "attribute": 9,
    "property": 10,
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


def run(buf: Buffer, load_user_extensions: bool = False, extension_names=None, extension_files=None, load_all_extensions: bool = False, project_dir=None) -> None:
    """Entry point. Wraps curses so the terminal is restored on crash/exit."""
    curses.wrapper(_curses_main, buf, load_user_extensions, extension_names or [], extension_files or [], load_all_extensions, project_dir)


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_COLOR_PAIRS["keyword"], curses.COLOR_MAGENTA, -1)
    curses.init_pair(_COLOR_PAIRS["string"], curses.COLOR_GREEN, -1)
    curses.init_pair(_COLOR_PAIRS["comment"], curses.COLOR_CYAN, -1)
    curses.init_pair(_COLOR_PAIRS["number"], curses.COLOR_YELLOW, -1)
    curses.init_pair(_COLOR_PAIRS["function"], curses.COLOR_BLUE, -1)
    curses.init_pair(_COLOR_PAIRS["type"], curses.COLOR_YELLOW, -1)
    curses.init_pair(_COLOR_PAIRS["operator"], curses.COLOR_RED, -1)
    curses.init_pair(_COLOR_PAIRS["tag"], curses.COLOR_MAGENTA, -1)
    curses.init_pair(_COLOR_PAIRS["attribute"], curses.COLOR_CYAN, -1)
    curses.init_pair(_COLOR_PAIRS["property"], curses.COLOR_BLUE, -1)


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


def _curses_main(stdscr, buf: Buffer, load_user_extensions: bool = False, extension_names=None, extension_files=None, load_all_extensions: bool = False, project_dir=None) -> None:
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
    explorer = FileExplorer(".")
    root_dir = resolve_tree_root(buf.filename, project_dir)
    if root_dir != ".":
        explorer.set_root(root_dir)
    if buf.filename and os.path.isfile(buf.filename):
        explorer.current_path = os.path.abspath(buf.filename)
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
        hint = "File tree active — Enter opens file/folder, Esc to focus editor, Ctrl-H help"
        status = (status + "   " if status else "") + hint
        _main_loop(stdscr, buf, language, status, selecting, meter, extensions, editor, explorer)
    finally:
        extensions.shutdown()
        _disable_bracketed_paste()


def _main_loop(stdscr, buf: Buffer, language: str, status: str, selecting: bool, meter: PerfMeter, extensions: ExtensionAPI, editor: EditorContext, explorer: FileExplorer) -> None:
    show_help = False
    while True:
        frame_started = meter.frame_start()
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        text_height = height - 1  # reserve last row for status line

        # Calculate explorer width
        explorer_width = 25 if explorer.visible else 0

        # Draw file explorer if visible
        if explorer.visible:
            _draw_explorer(stdscr, explorer, text_height, explorer_width)

        gutter_width = line_number_width(len(buf.lines)) + 2
        text_width = max(1, width - explorer_width - gutter_width)

        buf.update_scroll(text_height, text_width)

        for row in range(text_height):
            line_idx = buf.scroll_y + row
            _draw_gutter(stdscr, row, line_idx, len(buf.lines), gutter_width, x_offset=explorer_width)
            if line_idx >= len(buf.lines):
                continue
            line = buf.lines[line_idx]
            _draw_line(
                stdscr, row, line, buf.scroll_x, text_width, language,
                x_offset=gutter_width + explorer_width,
            )
            _highlight_selection(
                stdscr, row, line_idx, line, buf,
                scroll_x=buf.scroll_x, width=text_width, x_offset=gutter_width + explorer_width,
            )

        match = buf.matching_bracket()
        status_line = format_status_bar(
            filename=buf.filename,
            modified=buf.modified,
            label=schema.language_label(language),
            cursor_y=buf.cursor_y,
            cursor_x=buf.cursor_x,
            line_count=len(buf.lines),
            selecting=selecting,
            large_file_mode=buf.large_file_mode,
            match_pos=match,
            meter_label=meter.label(),
            extension_status=extensions.status(),
            transient_status=status,
        )[: width - 1]
        try:
            stdscr.addstr(height - 1, 0, status_line, curses.A_REVERSE)
        except curses.error:
            pass

        if show_help:
            _draw_help_overlay(stdscr, build_help_lines(width),
                               help_scroll)

        stdscr.move(
            buf.cursor_y - buf.scroll_y,
            explorer_width + gutter_width + min(buf.cursor_x - buf.scroll_x, max(text_width - 1, 0)),
        )
        stdscr.refresh()
        meter.frame_end(frame_started)
        status = ""

        key = _get_key(stdscr)
        if key is None:
            continue

        # The help guide outranks every other binding (Ctrl-H / F1).
        if is_help_toggle(key, explorer.visible and explorer.active):
            show_help = not show_help
            if show_help:
                help_scroll = 0  # always open at the top
            continue
        if show_help:
            # Scroll, deliberate dismissal; other keys are swallowed.
            total = len(build_help_lines(width))
            view_h = max(1, height - 2)
            if key == curses.KEY_UP:
                help_scroll = clamp_scroll(help_scroll, -1, total, view_h)
            elif key == curses.KEY_DOWN:
                help_scroll = clamp_scroll(help_scroll, 1, total, view_h)
            elif key == curses.KEY_PPAGE:
                help_scroll = clamp_scroll(help_scroll, -view_h, total,
                                           view_h)
            elif key == curses.KEY_NPAGE:
                help_scroll = clamp_scroll(help_scroll, view_h, total,
                                           view_h)
            elif key in ("q", "\x1b", "\n", "\r"):
                show_help = False
            continue

        editor.status = status
        editor.stdscr = stdscr
        if extensions.dispatch_key(key):
            status = editor.status or ""
            continue

        # Handle file explorer keys when active
        if explorer.visible and explorer.active:
            if key == curses.KEY_UP:
                explorer.move_selection(-1)
                continue
            elif key == curses.KEY_DOWN:
                explorer.move_selection(1)
                continue
            elif key == curses.KEY_RIGHT:
                selected = explorer.get_selected()
                if selected and selected[3] and selected[2] not in explorer.expanded_dirs:
                    explorer.toggle_expand(explorer.selected_idx)
                continue
            elif key == curses.KEY_LEFT:
                selected = explorer.get_selected()
                if selected and selected[3] and selected[2] in explorer.expanded_dirs:
                    explorer.toggle_expand(explorer.selected_idx)
                elif explorer.can_go_up():
                    explorer.go_up()
                continue
            elif key in ("\n", "\r"):  # Enter - open file or toggle directory
                selected = explorer.get_selected()
                if selected:
                    depth, name, path, is_dir = selected
                    if path == "..":
                        explorer.go_up()
                    elif is_dir:
                        explorer.toggle_expand(explorer.selected_idx)
                    else:
                        # Open the file through the safe (dirty-guarded) path.
                        language, status = open_file_path(
                            stdscr, buf, explorer, path,
                            render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                        )
                        if status.startswith("Opened"):
                            explorer.active = False  # hand focus to the editor
                        # On failure keep tree focus so the user can retry.
                continue
            elif key == "h":  # toggle hidden files in the tree
                explorer.toggle_hidden()
                continue
            elif key == "n":  # new file in the selected directory
                render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                name = _prompt_line(lambda: _get_key(stdscr), render, "New file name: ")
                if name:
                    _, error = explorer.create_file(name)
                    status = error or f"Created {name}"
                    if not error and name.startswith("."):
                        status += " (hidden — press h to show)"
                continue
            elif key == "N":  # new folder in the selected directory
                render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                name = _prompt_line(lambda: _get_key(stdscr), render, "New folder name: ")
                if name:
                    _, error = explorer.create_folder(name)
                    status = error or f"Created folder {name}"
                    if not error and name.startswith("."):
                        status += " (hidden — press h to show)"
                continue
            elif key == "O":  # choose a project root via the system picker
                picked, info = filemanager.pick_folder(explorer.root_dir)
                if picked:
                    explorer.set_root(picked)
                    status = f"Project root: {picked}"
                elif info == "cancelled":
                    status = "Cancelled"
                elif info == "no system picker available":
                    # No desktop helper installed: fall back to typing a path.
                    render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                    typed = _prompt_line(lambda: _get_key(stdscr), render, "Project folder: ")
                    if typed:
                        target = os.path.expanduser(typed.strip())
                        if os.path.isdir(target):
                            explorer.set_root(target)
                            status = f"Project root: {target}"
                        else:
                            status = f"Not a directory: {target}"
                    else:
                        status = "Cancelled"
                else:
                    status = f"Folder picker failed: {info}"
                continue
            elif key == "R":  # reveal the tree root in the system file manager
                opened, info = filemanager.reveal_in_file_manager(explorer.root_dir)
                status = f"Opened in {info}" if opened else f"Reveal failed: {info}"
                continue
            elif key in ("\t", "\x05", "\x1b"):  # Tab / Ctrl-E / Esc -> editor
                explorer.active = False
                status = ""
                continue

        if explorer.visible and explorer.active and swallowed_by_tree(key):
            continue  # tree has focus: never leak typing into the editor

        if key == "\x05":  # Ctrl-E - toggle explorer visibility
            explorer.visible = not explorer.visible
            if explorer.visible:
                explorer.active = True
                status = "Explorer opened (Ctrl-E to close, Enter to open file/folder)"
            else:
                explorer.active = False
                status = "Explorer closed"
            continue
        elif key == curses.KEY_RESIZE:
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
        elif key == "\x0f":  # Ctrl-O: open a file by typed path
            render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
            target = _prompt_line(lambda: _get_key(stdscr), render)
            if target:
                language, status = open_file_path(
                    stdscr, buf, explorer,
                    os.path.expanduser(target),
                    render_unsaved=render,
                )
            else:
                status = "Open cancelled"
        elif key == "\x11":  # Ctrl-Q
            if buf.modified:
                status = "Unsaved changes — Ctrl-Q again to force quit, Ctrl-S to save"
                stdscr.addstr(height - 1, 0, status[: width - 1], curses.A_REVERSE)
                stdscr.refresh()
                confirm = _get_key(stdscr)
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


def resolve_tree_root(filename, project_dir) -> str:
    """Decide which folder the file tree is rooted at.

    Precedence: explicit --project folder > opened file's parent > cwd.
    """
    if project_dir:
        return os.path.abspath(project_dir)
    if filename and os.path.isfile(filename):
        return os.path.dirname(os.path.abspath(filename))
    return "."


def _draw_status_prompt(stdscr, text: str) -> None:
    """Render prompt text on the status row (used by interactive prompts)."""
    height, width = stdscr.getmaxyx()
    try:
        stdscr.addstr(height - 1, 0, text[: width - 1].ljust(width - 1), curses.A_REVERSE)
        stdscr.refresh()
    except curses.error:
        pass


# ---------------------------------------------------------------------- #
# Help overlay (Ctrl-H / F1)
# ---------------------------------------------------------------------- #
HELP_SECTIONS = [
    ("EDITING", [
        "characters          type to insert text at the cursor",
        "Enter               insert a new line",
        "Tab                 indent",
        "Backspace / Del     delete character",
        "< > ^ v             move cursor",
        "Home / End          jump to line start / end",
        "( { [               auto-close bracket pairs",
        ") } ]               skip over the auto-typed closer",
        "\" '               auto-close quotes",
    ]),
    ("SELECTION & CLIPBOARD", [
        "Ctrl-Space          start / stop selection ([SELECT] in status)",
        "(arrow keys extend the selection while it is active)",
        "Ctrl-C              copy selection",
        "Ctrl-X              cut selection",
        "Ctrl-V              paste (internal clipboard)",
    ]),
    ("HISTORY & FILES", [
        "Ctrl-Z              undo",
        "Ctrl-Y              redo",
        "Ctrl-S              save current file",
        "Ctrl-O              open a file by typed path (~ supported)",
        "Ctrl-Q              quit (press again to force with changes)",
    ]),
    ("FILE TREE (Ctrl-E panel)", [
        "Ctrl-E              hide / show the file tree",
        "^ v                 move selection",
        "< >                 collapse / expand folder (<..> climbs up)",
        "Enter               open file / expand folder / go up on <..>",
        "h                   show / hide dotfiles",
        "n                   new file in selected folder",
        "N                   new folder in selected folder",
        "O                   pick project root via system dialog",
        "R                   reveal root in system file manager",
        "Tab / Esc           focus the editor",
    ]),
    ("TERMINAL & PROMPTS", [
        "terminal paste      bracketed paste inserts multi-line text",
        "typed prompts       Enter confirms, Esc cancels",
        "prompt Backspace    edits the text (new file/folder, open path)",
        "",
        "(prompts appear for n / N / Ctrl-O and the O path fallback)",
    ]),
    ("HELP", [
        "Ctrl-H or F1        open / close this guide",
        "q / Esc / Enter     close this guide",
        "",
        "Note: some terminals merge Ctrl-H with Backspace. If Backspace",
        "stops deleting while editing, use F1 here instead.",
    ]),
]


def build_help_lines(width):
    """Pure helper: help overlay content fitted to `width` columns."""
    out = []
    for title, entries in HELP_SECTIONS:
        out.append(title)
        for entry in entries:
            out.append("  " + entry)
        out.append("")
    limit = max(10, int(width))
    return [line[:limit] for line in out]


def is_help_toggle(key, tree_active):
    """Should `key` open/close the help overlay?

    Raw Ctrl-H (\\x08) and F1 work anywhere.  On terminals whose
    terminfo maps kbs=^H, keypad() translates both Backspace and
    Ctrl-H into curses.KEY_BACKSPACE, so that constant opens the guide
    only while the tree is focused -- in the editor it must keep
    deleting characters.
    """
    if key == "\x08" or key == curses.KEY_F1:
        return True
    return bool(tree_active) and key == curses.KEY_BACKSPACE


def swallowed_by_tree(key) -> bool:
    """Should `key` be swallowed while the file tree has focus?

    Only printable single characters: anything else that reaches this
    point is either a control key with a legitimate global action
    (Ctrl-S save, Ctrl-Q quit, ...) or an editing key that the editor
    branch must keep handling.  Without this guard, typing while the
    tree is focused silently inserts characters into the document.
    """
    return isinstance(key, str) and len(key) == 1 and key.isprintable()


def clamp_scroll(offset, delta, total, view_h):
    """New scroll offset after moving `delta` rows, clamped to content.

    Keeps the viewport inside [0, max(total - view_h, 0)] so the guide
    can never scroll past its own text on any terminal size.
    """
    if total <= 0 or view_h <= 0:
        return 0
    return max(0, min(offset + delta, max(total - view_h, 0)))


def _draw_help_overlay(stdscr, lines, offset=0):
    """Paint a centered bordered help box over the current frame.

    `offset` scrolls through `lines` when they exceed the terminal
    height; ▲/▼ corner markers signal hidden content above/below.
    """
    height, width = stdscr.getmaxyx()
    inner_w = max(3, min(max([len(l) for l in lines] or [20]) + 4,
                         width - 2))
    body_h = len(lines)
    view_h = max(1, min(body_h, height - 2))
    box_h = view_h + 2
    top = max(0, (height - box_h) // 2)
    left = max(0, (width - inner_w) // 2)

    def put(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, text[:width - col], attr)
        except curses.error:
            pass

    title = " stdedit help - q/Esc/Enter close \u00b7 arrows scroll "
    fill = max(inner_w - 2 - len(title), 0)
    put(top, left, "\u250c" + "\u2500" * fill + title + "\u2500" *
        (inner_w - 2 - fill - len(title)) + "\u2510", curses.A_REVERSE)
    for i in range(view_h):
        text = lines[offset + i] if offset + i < body_h else ""
        put(top + 1 + i, left, "\u2502" + " " * inner_w + "\u2502")
        put(top + 1 + i, left + 2, text.rstrip())
    put(top + box_h - 1, left,
        "\u2514" + "\u2500" * (inner_w - 2) + "\u2518")
    # Scroll indicators: ▲ above, ▼ below.
    if offset > 0:
        put(top, left + inner_w - 1, "\u25b2", curses.A_REVERSE)
    if offset + view_h < body_h:
        put(top + box_h - 1, left + inner_w - 1, "\u25bc",
            curses.A_REVERSE)


# ---------------------------------------------------------------------- #
# Prompts (testable: they take read_key/render callables, not raw curses)
# ---------------------------------------------------------------------- #
def _get_key(stdscr):
    """Read one key with curses keypad-Enter normalized to "\\n".

    With keypad(True) enabled, real terminals report the physical Enter
    key as curses.KEY_ENTER rather than "\\n"/"\\r".  Normalizing here
    means every consumer (main loop, tree handler, prompts) sees a plain
    newline.  Returns None when curses reports no readable input.
    """
    try:
        key = stdscr.get_wch()
    except curses.error:
        return None
    if key == curses.KEY_ENTER:
        return "\n"
    return key


def _unsaved_changes_prompt(read_key, render=None) -> str:
    """Ask what to do about unsaved changes. Returns 'save'|'discard'|'cancel'."""
    if render is not None:
        render("Unsaved changes — (s)ave, (d)iscard, (c)ancel?")
    while True:
        try:
            k = read_key()
        except curses.error:
            continue
        if isinstance(k, str):
            if k in ("s", "S"):
                return "save"
            if k in ("d", "D"):
                return "discard"
            if k in ("c", "C", "\x1b"):
                return "cancel"


def _prompt_line(read_key, render, title: str = "Open file: ") -> Optional[str]:
    """Minimal single-line prompt. Returns the entered text, or None on cancel."""
    text = ""
    while True:
        render(title + text)
        try:
            k = read_key()
        except curses.error:
            continue
        if k in ("\n", "\r"):
            return text.strip() or None
        if k == "\x1b":
            return None
        if k in ("\x7f", "\b", curses.KEY_BACKSPACE):
            text = text[:-1]
        elif isinstance(k, str) and k.isprintable():
            text += k


def open_file_path(stdscr, buf: Buffer, explorer: Optional[FileExplorer], path: str, render_unsaved=None) -> Tuple[str, str]:
    """Safely open `path` into the buffer.

    Guards against losing unsaved changes (save/discard/cancel prompt),
    reloads the file, re-detects its language and re-roots/highlights the
    explorer at the file's parent folder. Returns (language, status_text).
    """
    current_language = schema.detect_language(buf.filename or "")
    if buf.modified:
        choice = _unsaved_changes_prompt(lambda: _get_key(stdscr), render_unsaved)
        if choice == "save":
            try:
                buf.save()
            except ValueError:
                return current_language, "No filename — cannot save; open cancelled"
        elif choice != "discard":
            return current_language, "Open cancelled"
    try:
        buf.load(path)
    except Exception as exc:
        return current_language, f"Error opening file: {exc}"
    language = schema.detect_language(buf.filename or "")
    if explorer is not None:
        abs_path = os.path.abspath(path)
        parent = os.path.dirname(abs_path)
        try:
            inside = os.path.commonpath([explorer.root_dir, abs_path]) == explorer.root_dir
        except ValueError:  # e.g. unrelated Windows drives
            inside = False
        if inside:
            # The file lives inside the current tree (typical when a
            # project root was given): keep that root and just reveal
            # the file — expand its ancestors, refresh, highlight it.
            node = parent
            while node != explorer.root_dir and len(node) > len(explorer.root_dir):
                explorer.expanded_dirs.add(node)
                node = os.path.dirname(node)
            explorer.refresh()
            explorer._select_path(abs_path)
        else:
            # Outside the current tree: re-root at the file's folder.
            explorer.set_root(parent)
        explorer.current_path = abs_path
    return language, f"Opened {path}"


def format_status_bar(
    filename,
    modified,
    label,
    cursor_y,
    cursor_x,
    line_count,
    selecting=False,
    large_file_mode=False,
    match_pos=None,
    meter_label="",
    extension_status="",
    transient_status="",
) -> str:
    """Build the status bar text.

    Pure function (no curses access) so it can be unit tested. Shows the
    open file name with a dirty marker, the human-readable file type, cursor
    position and scroll percentage, plus optional mode/meter/extension info.
    """
    name = f"{filename or '[No Name]'}{'*' if modified else ''}"
    sel_flag = " [SELECT]" if selecting else ""
    large_flag = " [LARGE-FILE: undo off]" if large_file_mode else ""
    match_flag = f" [MATCH {match_pos[0]+1}:{match_pos[1]+1}]" if match_pos else ""
    if line_count > 0:
        pct = max(0, min(100, round((cursor_y + 1) / line_count * 100)))
        pct_text = f"  {pct}%"
    else:
        pct_text = ""
    parts = [
        f"{name}  [{label}]  Ln {cursor_y + 1}, Col {cursor_x + 1}{sel_flag}{large_flag}{match_flag}{pct_text}"
    ]
    if meter_label:
        parts.append(meter_label)
    if extension_status:
        parts.append(extension_status)
    if transient_status:
        parts.append(transient_status)
    return "   ".join(parts)


def _draw_explorer(stdscr, explorer: FileExplorer, height: int, width: int) -> None:
    """Draw the file explorer panel on the left side."""
    # Draw vertical separator
    for row in range(height):
        try:
            stdscr.addstr(row, width - 1, "│", curses.A_DIM)
        except curses.error:
            pass

    # Draw explorer items
    visible_items = explorer.items[:]
    start_idx = max(0, explorer.selected_idx - height // 2)
    end_idx = min(len(visible_items), start_idx + height)

    for i, row in enumerate(range(start_idx, end_idx)):
        if row >= len(visible_items):
            break
        depth, name, path, is_dir = visible_items[row]
        indent = "  " * depth
        display = f"{indent}{name}"[:width - 2]

        attr = curses.A_REVERSE if row == explorer.selected_idx else 0
        if is_dir and row != explorer.selected_idx:
            attr |= curses.A_BOLD
        elif not is_dir and path == explorer.current_path:
            # Highlight the file that is currently open in the editor.
            attr |= curses.A_BOLD | curses.A_UNDERLINE

        try:
            stdscr.addstr(i, 0, display.ljust(width - 2)[:width - 2], attr)
        except curses.error:
            pass


def _draw_gutter(stdscr, row: int, line_idx: int, line_count: int, gutter_width: int, x_offset: int = 0) -> None:
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
        stdscr.addstr(row, x_offset, label[:gutter_width], curses.A_DIM)
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
