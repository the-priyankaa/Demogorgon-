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
      buf.insert_tab() / indent_selection()
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
import time

from .buffer import Buffer
from .languages import schema
from .perf import PerfMeter
from .extensions import ExtensionAPI, load_extensions, load_requested_extensions
from .explorer import FileExplorer
from . import filemanager
from . import icons
from . import settings
from . import git
from .git_panel import GitPanel, init_panel_colors, draw_git_panel, git_panel_key
from .diff_viewer import DiffViewer, init_diff_colors, draw_diff_overlay, diff_viewer_key

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


def run(buf: Buffer, extension_names=None, extension_files=None, load_all_extensions: bool = False, project_dir=None) -> None:
    """Entry point. Wraps curses so the terminal is restored on crash/exit."""
    curses.wrapper(_curses_main, buf, extension_names or [], extension_files or [], load_all_extensions, project_dir)


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


# ---------------------------------------------------------------------- #
# Find / Replace state (module-level, persists across frames)
# ---------------------------------------------------------------------- #
_search: dict = {
    "query": "",
    "replace": "",
    "matches": [],
    "idx": 0,
    "anchor": None,
    "mode": "find",
    "replacements": [],
}

_mouse_dragging: bool = False


def _curses_main(stdscr, buf: Buffer, extension_names=None, extension_files=None, load_all_extensions: bool = False, project_dir=None) -> None:
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
    init_panel_colors()
    init_diff_colors()
    _enable_bracketed_paste()
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    curses.mouseinterval(0)
    icons_on = icons.enabled_from_env()

    language = schema.detect_language(buf.filename or "")
    buf.configure_for_language(language)
    selecting = False
    meter = PerfMeter(interval=0.5)
    editor = EditorContext(buf, stdscr)
    explorer = FileExplorer(".")
    root_dir = resolve_tree_root(buf.filename, project_dir)
    git_panel = GitPanel(root_dir if root_dir != "." else os.path.dirname(os.path.abspath(buf.filename)) if buf.filename else ".")
    diff_viewer = DiffViewer()
    if root_dir != ".":
        explorer.set_root(root_dir)
    if buf.filename and os.path.isfile(buf.filename):
        explorer.current_path = os.path.abspath(buf.filename)
    extensions = ExtensionAPI(editor)
    if load_all_extensions:
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
        _main_loop(stdscr, buf, language, status, selecting, meter, extensions, editor, explorer, icons_on, root_dir, git_panel, diff_viewer)
    finally:
        extensions.shutdown()
        _disable_bracketed_paste()


def _main_loop(stdscr, buf: Buffer, language: str, status: str, selecting: bool, meter: PerfMeter, extensions: ExtensionAPI, editor: EditorContext, explorer: FileExplorer, icons_on: bool = False, root_dir: str = ".", git_panel: GitPanel | None = None, diff_viewer: DiffViewer | None = None) -> None:
    show_help = False
    show_settings = False
    settings_idx = 0
    _last_edit_time = time.time()
    _last_save_time = time.time()
    _auto_save_flag = False
    _git_branch = None
    _git_counts: dict[str, int] = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0}
    _git_refresh_time = 0.0
    _git_refresh_interval = 2.0  # seconds between git status refreshes
    while True:
        frame_started = meter.frame_start()
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        text_height = height - 1  # reserve last row for status line

        # Calculate explorer width — proportional to terminal width
        explorer_width = (min(25, max(18, width // 4))
                          if explorer.visible else 0)

        # Calculate git panel width — proportional to terminal width
        git_panel_width = (min(30, max(20, width // 5))
                           if git_panel and git_panel.visible else 0)

        # Draw file explorer if visible
        if explorer.visible:
            _draw_explorer(stdscr, explorer, text_height, explorer_width,
                           icons_on)

        # Draw git panel if visible
        if git_panel and git_panel.visible:
            if git_panel.mode == "diff":
                # Diff overlay mode — load diff if needed and draw full overlay
                if diff_viewer and not diff_viewer.diff_text:
                    diff_text = git_panel.get_selected_diff()
                    f = git_panel.selected_file()
                    title = f.path if f else "diff"
                    diff_viewer.load(diff_text, title=title)
                if diff_viewer:
                    draw_diff_overlay(stdscr, diff_viewer, height, width)
                    stdscr.move(height - 1, 0)
                    status_line = format_status_bar(
                        filename=buf.filename, modified=buf.modified,
                        label=schema.language_label(language),
                        cursor_y=buf.cursor_y, cursor_x=buf.cursor_x,
                        total_lines=len(buf.lines), selected_line=buf.cursor_y,
                        scroll_y=buf.scroll_y, viewport_height=text_height,
                        finding=finding, git_branch=_git_branch,
                        git_counts=_git_counts, width=width,
                    )
                    stdscr.addstr(height - 1, 0, status_line[:width - 1],
                                  curses.A_REVERSE | curses.A_BOLD)
                    try:
                        stdscr.move(buf.cursor_y - buf.scroll_y, 0)
                    except curses.error:
                        pass
                    if frame_started:
                        meter.frame_end()
                    continue
            else:
                draw_git_panel(stdscr, git_panel, text_height, git_panel_width)

        gutter_width = line_number_width(len(buf.lines)) + 2
        text_width = max(1, width - explorer_width - git_panel_width - gutter_width)

        buf.update_scroll(text_height, text_width)

        for row in range(text_height):
            line_idx = buf.scroll_y + row
            _draw_gutter(stdscr, row, line_idx, len(buf.lines), gutter_width, x_offset=explorer_width + git_panel_width)
            if line_idx >= len(buf.lines):
                continue
            line = buf.lines[line_idx]
            _draw_line(
                stdscr, row, line, buf.scroll_x, text_width, language,
                x_offset=gutter_width + explorer_width + git_panel_width,
            )
            _highlight_selection(
                stdscr, row, line_idx, line, buf,
                scroll_x=buf.scroll_x, width=text_width, x_offset=gutter_width + explorer_width + git_panel_width,
            )
            _highlight_find_match(
                stdscr, row, line_idx, text_width, buf.scroll_x,
                gutter_width + explorer_width + git_panel_width,
            )

        match = buf.matching_bracket()

        # Refresh git info periodically (not every frame)
        now_frame = time.time()
        if now_frame - _git_refresh_time >= _git_refresh_interval:
            _git_refresh_time = now_frame
            project = root_dir if root_dir != "." else (os.path.dirname(buf.filename) if buf.filename else ".")
            if git.is_git_repo(project):
                _git_branch = git.get_branch(project)
                _git_counts = git.get_status_counts(project)
                # Also refresh git panel if visible
                if git_panel and git_panel.visible:
                    git_panel.refresh()
            else:
                _git_branch = None
                _git_counts = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0}

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
            icon=icons.icon_for_language(schema.language_label(language), icons_on),
            width=width,
            git_branch=_git_branch,
            git_counts=_git_counts,
        )
        try:
            stdscr.addstr(height - 1, 0, status_line, curses.A_REVERSE)
        except curses.error:
            pass

        if show_help:
            _draw_help_overlay(stdscr, build_help_lines(width),
                               help_scroll)
        if show_settings:
            _draw_settings_overlay(stdscr, settings_idx)

        stdscr.move(
            buf.cursor_y - buf.scroll_y,
            explorer_width + git_panel_width + gutter_width + min(buf.cursor_x - buf.scroll_x, max(text_width - 1, 0)),
        )
        stdscr.refresh()
        meter.frame_end(frame_started)
        status = ""

        _prev_modified = buf.modified
        key = _get_key(stdscr)
        if key is None:
            continue

        # Check auto-save conditions on every key event.
        now = time.time()
        if buf.modified and buf.filename:
            saved = False
            if settings.get("auto_save_idle") and now - _last_edit_time >= 5:
                buf.save()
                saved = True
            elif settings.get("auto_save_periodic") and now - _last_save_time >= 30:
                buf.save()
                saved = True
            if saved:
                _last_save_time = now
                status = "Auto-saved"

        # --- Mouse events (before all other key handling) ---
        if isinstance(key, tuple) and key[0] == "__mouse__":
            global _mouse_dragging
            _, mx, my, bstate = key
            # Convert screen coords → buffer coords.
            buf_y = buf.scroll_y + my
            buf_x = buf.scroll_x + (mx - gutter_width - explorer_width)
            buf_y = max(0, min(buf_y, len(buf.lines) - 1))
            buf_x = max(0, min(buf_x, len(buf.lines[buf_y])))

            if bstate & curses.BUTTON1_PRESSED:
                # Click in text area only.
                if my < text_height and mx >= gutter_width + explorer_width:
                    buf.move_to(buf_x, buf_y)
                    buf.selection_anchor = (buf_y, buf_x)
                    _mouse_dragging = True
                    selecting = False
                elif my >= text_height:
                    # Click on status bar — ignore.
                    pass
                else:
                    # Click in gutter/explorer — ignore (let explorer handle if needed).
                    pass
                continue
            if bstate & curses.BUTTON1_RELEASED:
                _mouse_dragging = False
                continue
            # Motion while dragging (REPORT_MOUSE_POSITION events).
            if _mouse_dragging:
                if 0 <= my < text_height and mx >= gutter_width + explorer_width:
                    buf.move_to(buf_x, buf_y, extend_selection=True)
            continue

        # The help guide outranks every other binding (Ctrl-H / F1).
        if is_help_toggle(key, explorer.visible and explorer.active) and not explorer.searching:
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

        # Settings overlay (Ctrl-P).
        if key == "\x10" and not explorer.searching:
            show_settings = not show_settings
            settings_idx = 0
            continue
        if show_settings:
            n_items = len(settings.LABELS)
            if key == curses.KEY_UP:
                settings_idx = (settings_idx - 1) % n_items
            elif key == curses.KEY_DOWN:
                settings_idx = (settings_idx + 1) % n_items
            elif key in (" ", "\n", "\r"):
                settings.toggle_radio(settings.LABELS[settings_idx][0])
            elif key in ("\x1b", "\x10", "q"):
                show_settings = False
            continue

        editor.status = status
        editor.stdscr = stdscr
        if extensions.dispatch_key(key):
            status = editor.status or ""
            continue

        # Handle file explorer keys when active
        if explorer.visible and explorer.active:
            # --- search mode: redirect all keys to the search buffer ---
            if explorer.searching:
                if key == "\x1b":  # Esc — exit search
                    explorer.exit_search()
                    status = ""
                    continue
                elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    explorer.search_query = explorer.search_query[:-1]
                    explorer.search(explorer.search_query)
                    status = f"/{explorer.search_query}" if explorer.search_query else ""
                    continue
                elif key in ("\n", "\r"):  # Enter — open selected result
                    selected = explorer.get_selected()
                    if selected:
                        depth, name, path, is_dir = selected
                        if path == "..":
                            pass  # ignore parent entry in search results
                        elif is_dir:
                            # Exit search and navigate tree to this folder.
                            explorer.exit_search()
                            # Expand every ancestor so the folder is visible.
                            p = os.path.dirname(path)
                            while p and p != explorer.root_dir:
                                explorer.expanded_dirs.add(p)
                                p = os.path.dirname(p)
                            explorer.expanded_dirs.add(path)
                            explorer.refresh()
                            explorer._select_path(path)
                            explorer.active = True
                            status = ""
                        else:
                            language, open_status = open_file_path(
                                stdscr, buf, explorer, path,
                                render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                            )
                            if open_status.startswith("Opened"):
                                buf.configure_for_language(language)
                                explorer.exit_search()
                                explorer.active = False
                                status = open_status
                            else:
                                status = open_status
                    continue
                elif key == curses.KEY_UP:
                    explorer.move_selection(-1)
                    continue
                elif key == curses.KEY_DOWN:
                    explorer.move_selection(1)
                    continue
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    explorer.search_query += key
                    explorer.search(explorer.search_query)
                    status = f"/{explorer.search_query}"
                    continue
                # swallow everything else during search
                continue
            if key == curses.KEY_UP:
                explorer.move_selection(-1)
                continue
            elif key == curses.KEY_DOWN:
                explorer.move_selection(1)
                continue
            elif key == "/":  # enter search mode
                explorer.enter_search()
                status = "/"
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
                            buf.configure_for_language(language)
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
                    path, error = explorer.create_file(name)
                    status = error or f"Created {name}"
                    if not error and name.startswith("."):
                        status += " (hidden — press h to show)"
                    if not error:
                        # Create-then-edit: open it straight away (the
                        # dirty-buffer guard inside still applies).
                        language, open_status = open_file_path(
                            stdscr, buf, explorer, path,
                            render_unsaved=render,
                        )
                        if open_status.startswith("Opened"):
                            buf.configure_for_language(language)
                            explorer.active = False
                            status = f"Created + opened {name}"
                        else:
                            status = f"Created {name} ({open_status})"
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

        # Handle git panel keys when active
        if git_panel and git_panel.visible and git_panel.active:
            if git_panel.mode == "diff" and diff_viewer:
                # Ctrl-G closes panel entirely from diff mode
                if key == "\x07":
                    git_panel.visible = False
                    git_panel.active = False
                    git_panel.end_diff()
                    diff_viewer.diff_text = ""
                    diff_viewer.lines = []
                    status = ""
                    continue
                # Route other keys to diff viewer
                if not diff_viewer_key(diff_viewer, key, text_height):
                    # q/Esc → exit diff mode
                    git_panel.end_diff()
                    diff_viewer.diff_text = ""
                    diff_viewer.lines = []
                    status = ""
                else:
                    status = ""
                continue
            if git_panel_key(git_panel, key):
                status = git_panel.last_result or ""
                continue
            # Tab/Ctrl-G/Esc from git panel → focus editor
            if key in ("\t", "\x07", "\x1b"):
                git_panel.active = False
                status = ""
                continue

        if key == "\x07":  # Ctrl-G - toggle git panel
            if not git_panel:
                continue
            if not git_panel.visible:
                git_panel.visible = True
                git_panel.active = True
                git_panel.refresh()
                status = "Source Control (c:commit s:stage u:unstage d:diff p:push)"
            elif not git_panel.active:
                git_panel.active = True
                status = ""
            else:
                git_panel.visible = False
                git_panel.active = False
                status = "Source Control closed"
            continue

        if key == "\x05":  # Ctrl-E - toggle explorer
            if not explorer.visible:
                # Hidden → show and activate
                explorer.visible = True
                explorer.active = True
                status = "Explorer opened (Esc to close, Enter to open file/folder)"
            else:
                # Visible but editor-focused → activate tree
                explorer.active = True
                status = ""
            continue
        if key == "\x1b" and explorer.visible and not explorer.active:
            # Esc from editor with tree visible → hide tree
            explorer.visible = False
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
                expanded = os.path.expanduser(target)
                can_open = True
                if not os.path.exists(expanded):
                    # Create-before-editing: offer to make the missing file.
                    can_open = False
                    msg = f"'{target}' not found - create it? (y/n)"
                    if _yes_no_prompt(lambda: _get_key(stdscr), render, msg):
                        parent = os.path.dirname(expanded) or "."
                        if not os.path.isdir(parent):
                            status = f"Cannot create: no folder {parent}"
                        else:
                            try:
                                with open(expanded, "x"):
                                    pass
                                can_open = True
                            except OSError as exc:
                                status = f"Cannot create file: {exc}"
                    else:
                        status = "Cancelled"
                if can_open:
                    language, status = open_file_path(
                        stdscr, buf, explorer, expanded,
                        render_unsaved=render,
                    )
                    if status.startswith("Opened"):
                        buf.configure_for_language(language)
                        explorer.active = False
            else:
                status = "Open cancelled"
        elif key == "\x06":  # Ctrl-F: find in buffer
            explorer.active = False
            _find_replace_prompt(stdscr, buf, mode="find", git_panel_width=git_panel_width)
        elif key == "\x12":  # Ctrl-R: replace all
            explorer.active = False
            result = _find_replace_prompt(stdscr, buf, mode="replace", git_panel_width=git_panel_width)
            if result:
                status = result
        elif key == "\x11":  # Ctrl-Q
            if buf.modified and not settings.any_auto_save():
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
        elif key == "\x01":  # Ctrl-A select all
            buf.select_all()
            selecting = False
            status = "Selected all"
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
        elif key == "\x16":  # Ctrl-V paste
            buf.paste()
            status = "Pasted" if buf.clipboard else "Clipboard empty"
        elif isinstance(key, str) and key in "([{":
            if buf.has_selection():
                buf.delete_selection()
            buf.auto_close_bracket(key)
        elif isinstance(key, str) and key in ")]}":
            if not buf.smart_dedent_on_char(key) and not buf.skip_closer(key):
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

        # Track last edit time for idle auto-save.
        if buf.modified and not _prev_modified:
            _last_edit_time = time.time()
            if settings.get("auto_save_on_edit") and buf.filename:
                buf.save()
                _last_save_time = time.time()
                status = "Auto-saved"


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


def _find_all_matches(buf, query):
    """Return list of (line, start, end) for every occurrence of *query*."""
    q = query.lower()
    results = []
    for y in range(len(buf.lines)):
        line = buf.lines[y].lower()
        start = 0
        while True:
            pos = line.find(q, start)
            if pos < 0:
                break
            results.append((y, pos, pos + len(query)))
            start = pos + 1
    return results


def _find_replace_prompt(stdscr, buf, mode="find", git_panel_width=0):
    """Modal find / replace prompt.  Renders the full editor on each keystroke
    so the user sees highlighted matches in real-time."""
    global _search
    _search["mode"] = mode
    _search["query"] = ""
    _search["replace"] = ""
    _search["matches"] = []
    _search["idx"] = 0
    _search["anchor"] = (buf.cursor_y, buf.cursor_x)
    _search["replacements"] = []

    field = "query"  # which field has focus: "query" or "replace"
    height, width = stdscr.getmaxyx()
    explorer_width = 25
    gutter_width = max(2, len(str(max(1, len(buf.lines))))) + 2
    text_width = max(1, width - explorer_width - git_panel_width - gutter_width)
    text_height = height - 1

    def _render():
        """Redraw the full screen with match highlights and the prompt."""
        stdscr.erase()
        buf.update_scroll(text_height, text_width)
        for row in range(text_height):
            line_idx = buf.scroll_y + row
            _draw_gutter(stdscr, row, line_idx, len(buf.lines), gutter_width,
                         x_offset=explorer_width + git_panel_width)
            if line_idx < len(buf.lines):
                _draw_line(stdscr, row, buf.lines[line_idx], buf.scroll_x,
                           text_width, schema.detect_language(buf.filename or ""),
                           x_offset=gutter_width + explorer_width + git_panel_width)
                _highlight_selection(stdscr, row, line_idx, buf.lines[line_idx], buf,
                                     scroll_x=buf.scroll_x, width=text_width,
                                     x_offset=gutter_width + explorer_width + git_panel_width)
                _highlight_find_match(stdscr, row, line_idx, text_width,
                                      buf.scroll_x, gutter_width + explorer_width + git_panel_width)
        # Status prompt
        n = len(_search["matches"])
        pos = f" [{_search['idx'] + 1}/{n}]" if n else ""
        if field == "replace" or mode == "replace":
            label = "Replace" if field == "replace" else "Find"
            text = f" {label}: {_search[field]}{pos}"
        else:
            text = f" Find: {_search['query']}{pos}"
        try:
            stdscr.addstr(height - 1, 0, text[: width - 1].ljust(width - 1),
                          curses.A_REVERSE)
        except curses.error:
            pass
        stdscr.refresh()

    _render()
    while True:
        try:
            key = stdscr.get_wch()
        except curses.error:
            continue
        if isinstance(key, int):
            if key == curses.KEY_ENTER:
                key = "\n"
            elif key == curses.KEY_BACKSPACE:
                key = "\x7f"
            else:
                continue  # ignore other special keys
        if key == "\x1b":  # Esc — cancel
            # Undo any replacements made (walk backwards).
            for y, start, old_text, new_len in reversed(_search["replacements"]):
                line = buf.lines[y]
                buf.lines[y] = line[:start] + old_text + line[start + new_len:]
            buf.move_to(_search["anchor"][1], _search["anchor"][0])
            _search["query"] = ""
            _search["replace"] = ""
            _search["matches"] = []
            _search["idx"] = 0
            _search["anchor"] = None
            _search["replacements"] = []
            return
        if key == "\t":  # Tab — switch field (replace mode only)
            if mode == "replace":
                field = "replace" if field == "query" else "query"
                _render()
            continue
        if key in ("\n", "\r"):  # Enter
            if mode == "replace" and field == "query":
                # Move to replace field.
                field = "replace"
                _render()
                continue
            if mode == "replace" and _search["matches"]:
                # Replace ALL matches.
                for m_line, m_start, m_end in _search["matches"]:
                    old_text = buf.lines[m_line][m_start:m_end]
                    new_len = len(_search["replace"])
                    _search["replacements"].append((m_line, m_start, old_text, new_len))
                    buf.lines[m_line] = (buf.lines[m_line][:m_start]
                                         + _search["replace"]
                                         + buf.lines[m_line][m_end:])
                buf.modified = True
                count = len(_search["replacements"])
                _search["query"] = ""
                _search["replace"] = ""
                _search["matches"] = []
                _search["idx"] = 0
                _search["anchor"] = None
                _search["replacements"] = []
                return f"Replaced {count} occurrences"
            # Find mode: confirm and close.
            _search["query"] = ""
            _search["replace"] = ""
            _search["matches"] = []
            _search["idx"] = 0
            _search["anchor"] = None
            _search["replacements"] = []
            return
        if key == "\x06":  # Ctrl-F — next match
            if _search["matches"]:
                _search["idx"] = (_search["idx"] + 1) % len(_search["matches"])
                ml, ms, me = _search["matches"][_search["idx"]]
                buf.move_to(ms, ml)
                _render()
            continue
        if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            target = _search[field]
            if target:
                _search[field] = target[:-1]
                if field == "query" and _search["query"]:
                    _search["matches"] = _find_all_matches(buf, _search["query"])
                    _search["idx"] = 0
                    if _search["matches"]:
                        ml, ms, me = _search["matches"][0]
                        buf.move_to(ms, ml)
                _render()
            continue
        if isinstance(key, str) and len(key) == 1 and key.isprintable():
            _search[field] += key
            if field == "query":
                _search["matches"] = _find_all_matches(buf, _search["query"])
                _search["idx"] = 0
                if _search["matches"]:
                    ml, ms, me = _search["matches"][0]
                    buf.move_to(ms, ml)
            _render()
            continue


# ---------------------------------------------------------------------- #
# Help overlay (Ctrl-H / F1)
# ---------------------------------------------------------------------- #
HELP_SECTIONS = [
    ("EDITING", [
        "characters          type to insert text at the cursor",
        "Enter               new line (auto-indents per language)",
        "Tab                 indent (width adapts to the language)",
        "Backspace / Del     delete character",
        "< > ^ v             move cursor",
        "Home / End          jump to line start / end",
        "( { [               auto-close bracket pairs",
        ") } ]               skip closer / dedent on block close",
        "\" '                auto-close quotes",
        "Ctrl-F              find text in the file",
        "Ctrl-R              replace all occurrences",
    ]),
    ("SELECTION & CLIPBOARD", [
        "Ctrl-A              select all",
        "Ctrl-Space          start / stop selection ([SELECT] in status)",
        "(arrow keys extend the selection while it is active)",
        "Ctrl-C              copy selection",
        "Ctrl-X              cut selection",
        "Ctrl-V              paste (system + internal clipboard)",
    ]),
    ("HISTORY & FILES", [
        "Ctrl-Z              undo",
        "Ctrl-Y              redo",
        "Ctrl-S              save current file",
        "Ctrl-P              settings / preferences",
        "Ctrl-O              open a file by typed path (~ supported;",
        "                    offers to create it if missing)",
        "Ctrl-Q              quit (press again to force with changes)",
    ]),
    ("FILE TREE (Ctrl-E panel)", [
        "Ctrl-E              open / focus the file tree",
        "^ v                 move selection",
        "< >                 collapse / expand folder (<..> climbs up)",
        "Enter               open file / expand folder / go up on <..>",
        "/                   search files and folders (Esc to cancel)",
        "Esc                 close the file tree",
        "h                   show / hide dotfiles",
        "n                   new file (opens it for editing)",
        "N                   new folder in selected folder",
        "O                   pick project root via system dialog",
        "R                   reveal root in system file manager",
        "Tab / Esc           focus the editor",
    ]),
    ("GIT STATUS", [
        "status bar          shows branch name and change counts",
        "                    +N added  ~N modified  -N deleted  !N untracked",
        "automatic           refreshes every 2 seconds (no manual trigger)",
    ]),
    ("SOURCE CONTROL (Ctrl-G panel)", [
        "Ctrl-G              open / close source control panel",
        "j / k               move selection",
        "c                   commit (type message, Enter to confirm)",
        "s                   stage selected file",
        "u                   unstage selected file",
        "a                   stage all changes",
        "d                   show diff for selected file",
        "p                   push",
        "P                   pull",
        "b                   switch branch",
        "S                   stash changes",
        "A                   pop stash",
        "I                   list issues (o:close r:reopen)",
        "M                   list PRs (c:checkout m:merge)",
        "Tab / Ctrl-G / Esc  focus the editor",
    ]),
    ("DIFF VIEWER", [
        "d / Space           page down",
        "u                   page up",
        "j / k               scroll one line",
        "g / G               jump to top / bottom",
        "q / Esc             close diff view",
    ]),
    ("SETTINGS (Ctrl-P panel)", [
        "Ctrl-P              open / close settings panel",
        "Up / Down           navigate settings",
        "Space               toggle selected setting",
        "q / Esc / Ctrl-P    close settings panel",
    ]),
    ("MOUSE", [
        "click               position cursor",
        "drag                select text",
    ]),
    ("TERMINAL & PROMPTS", [
        "terminal paste      bracketed paste inserts multi-line text",
        "typed prompts       Enter confirms, Esc cancels",
        "prompt Backspace    edits the text (new file/folder, open path)",
        "icons               Nerd Font glyphs (e.g. MesloLGS NF);",
        "                    disable with STDEDIT_ICONS=0",
        "",
        "(prompts appear for n / Ctrl-O and the O path fallback)",
    ]),
    ("HELP", [
        "Ctrl-H or F1        open / close this guide",
        "Up / Down, PgUp/Dn  scroll this guide",
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


_MIN_HELP_W = 50


def _draw_help_overlay(stdscr, lines, offset=0):
    """Paint a centered bordered help box over the current frame.

    `offset` scrolls through `lines` when they exceed the terminal
    height; ▲/▼ corner markers signal hidden content above/below.
    """
    height, width = stdscr.getmaxyx()
    content_w = max([len(l) for l in lines] or [20])
    inner_w = max(_MIN_HELP_W, min(content_w + 6, width * 70 // 100))
    inner_w = min(inner_w, width - 2)
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
    max_title_w = inner_w - 2
    if len(title) > max_title_w:
        title = title[:max_title_w - 3] + "... "
    fill = max(max_title_w - len(title), 0)
    left_fill = fill // 2
    right_fill = fill - left_fill
    put(top, left, "\u250c" + "\u2500" * left_fill + title + "\u2500" *
        right_fill + "\u2510", curses.A_REVERSE)
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


def _draw_settings_overlay(stdscr, selected_idx: int) -> None:
    """Paint a centered bordered settings box with toggleable options."""
    height, width = stdscr.getmaxyx()
    items = settings.LABELS
    body_h = len(items) + 1  # +1 for hint line
    content_w = max((len(f"[x] {label}") for _, label in items),
                    default=0)
    inner_w = max(40, min(content_w + 8, width * 70 // 100))
    inner_w = min(inner_w, width - 2)
    box_h = body_h + 2
    top = max(0, (height - box_h) // 2)
    left = max(0, (width - inner_w) // 2)

    def put(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, text[:width - col], attr)
        except curses.error:
            pass

    title = " Settings "
    max_title_w = inner_w - 2
    if len(title) > max_title_w:
        title = title[:max_title_w - 3] + "... "
    fill = max(max_title_w - len(title), 0)
    left_fill = fill // 2
    right_fill = fill - left_fill
    put(top, left, "\u250c" + "\u2500" * left_fill + title + "\u2500" *
        right_fill + "\u2510", curses.A_REVERSE)
    for i, (key, label) in enumerate(items):
        on = settings.get(key)
        if settings.is_radio_key(key):
            marker = "(x)" if on else "( )"
        else:
            marker = "[x]" if on else "[ ]"
        line = f" {marker} {label}"
        attr = curses.A_REVERSE if i == selected_idx else 0
        put(top + 1 + i, left, "\u2502" + " " * inner_w + "\u2502")
        put(top + 1 + i, left + 1, line[:inner_w - 2], attr)
    # Hint line
    hint = " \u2191\u2193 navigate  Space toggle  Esc close "
    put(top + 1 + len(items), left, "\u2502" + " " * inner_w + "\u2502")
    put(top + 1 + len(items), left + 1, hint[:inner_w - 2], curses.A_DIM)
    put(top + box_h - 1, left,
        "\u2514" + "\u2500" * (inner_w - 2) + "\u2518")


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
    if key == curses.KEY_MOUSE:
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return None
        return ("__mouse__", mx, my, bstate)
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


def _yes_no_prompt(read_key, render, message) -> bool:
    """Single-question confirm. y/Enter -> True; n/Esc -> False.

    Any other key re-prompts, mirroring the unsaved-changes flow.
    """
    if render is not None:
        render(message)
    while True:
        try:
            k = read_key()
        except curses.error:
            continue
        if isinstance(k, str):
            if k in ("y", "Y", "\n", "\r"):
                return True
            if k in ("n", "N", "\x1b"):
                return False


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
    icon="",
    width=0,
    git_branch=None,
    git_counts=None,
) -> str:
    """Build the status bar text.

    Pure function (no curses access) so it can be unit tested.  When
    *width* > 0 the bar is split into a left segment (file info and
    flags) and a right segment (position and scroll %), filled to the
    full terminal width so it always spans the bottom row.
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

    left = f"{name}  [{icon + ' ' if icon else ''}{label}]{sel_flag}{large_flag}{match_flag}"
    # Add git branch and status counts if available
    if git_branch:
        left += f"  {git_branch}"
    git_status = git.format_status_counts(git_counts or {})
    if git_status:
        left += f"  {git_status}"
    right = f"Ln {cursor_y + 1}, Col {cursor_x + 1}{pct_text}"

    extras = []
    if transient_status:
        extras.append(transient_status)
    if meter_label:
        extras.append(meter_label)
    if extension_status:
        extras.append(extension_status)
    extra_part = "  ".join(extras)

    if width <= 0:
        parts = [f"{left}  {right}"]
        if extra_part:
            parts.append(extra_part)
        return "   ".join(parts)

    sep = " \u2502 "  # thin vertical separator between left and right
    gap = max(1, width - len(left) - len(sep) - len(right))
    bar = f"{left}{' ' * gap}{sep}{right}"
    if extra_part:
        bar = f"{extra_part}   {bar}"
    return bar[:width - 1]


def _draw_explorer(stdscr, explorer: FileExplorer, height: int, width: int,
                   icons_on: bool = False) -> None:
    """Draw the file explorer panel on the left side."""
    # Draw vertical separator
    for row in range(height):
        try:
            stdscr.addstr(row, width - 1, "│", curses.A_DIM)
        except curses.error:
            pass

    # Search mode: 3-row area at the top (label, input, separator)
    if explorer.searching:
        # Row 0: label
        label = " Search "
        try:
            stdscr.addstr(0, 0, label.ljust(width - 2)[:width - 2],
                          curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass
        # Row 1: input field with cursor
        query_text = f" /{explorer.search_query}"
        cursor = "_"
        field = (query_text + cursor)[:width - 2]
        try:
            stdscr.addstr(1, 0, field.ljust(width - 2)[:width - 2],
                          curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass
        # Row 2: separator line
        sep = " " + "~" * (width - 3)
        try:
            stdscr.addstr(2, 0, sep[:width - 2], curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass
        # Offset items below the 3-row search area
        draw_height = height - 3
        item_offset = 3
    else:
        draw_height = height
        item_offset = 0

    # Draw explorer items
    visible_items = explorer.search_results if explorer.searching else explorer.items[:]
    start_idx = max(0, explorer.selected_idx - draw_height // 2)
    end_idx = min(len(visible_items), start_idx + draw_height)

    for i, row in enumerate(range(start_idx, end_idx)):
        if row >= len(visible_items):
            break
        depth, name, path, is_dir = visible_items[row]
        indent = "  " * depth
        prefix = "" if is_dir or path == ".." else (
            icons.icon_for_file(path, icons_on) + " " if icons_on else "")
        display = f"{indent}{prefix}{name}"[:width - 2]

        attr = curses.A_REVERSE if row == explorer.selected_idx else 0
        if is_dir and row != explorer.selected_idx:
            attr |= curses.A_BOLD
        elif not is_dir and path == explorer.current_path:
            # Highlight the file that is currently open in the editor.
            attr |= curses.A_BOLD | curses.A_UNDERLINE

        try:
            stdscr.addstr(item_offset + i, 0, display.ljust(width - 2)[:width - 2], attr)
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


def _highlight_find_match(stdscr, row, line_idx, width, scroll_x, x_offset) -> None:
    """Highlight the current find-match on this row, if any."""
    if not _search["query"] or not _search["matches"]:
        return
    m_line, m_start, m_end = _search["matches"][_search["idx"]]
    if m_line != line_idx:
        return
    col = m_start - scroll_x
    end_col = m_end - scroll_x
    if end_col <= 0 or col >= width:
        return
    vis_start = max(0, col)
    vis_end = min(end_col, width)
    if vis_start < vis_end:
        try:
            stdscr.addstr(row, x_offset + vis_start,
                          " " * (vis_end - vis_start),
                          curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass


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
