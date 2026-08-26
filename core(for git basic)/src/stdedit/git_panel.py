"""Source control panel for the git integration.

UI-agnostic panel state.  The curses drawing helper ``draw_git_panel``
lives here too since it only depends on curses (stdlib).
"""
from __future__ import annotations

import curses
import os
from typing import Optional

from . import git
from . import github_api


# ------------------------------------------------------------------ #
# Panel state (no curses dependency)
# ------------------------------------------------------------------ #

class GitPanel:
    """Source control panel — shows modified/staged/untracked files.

    Follows the same pattern as ``FileExplorer``: a flat list of items,
    a selection index, and visibility/focus flags.
    """
    # Git status letters mapped to short labels
    STATUS_LABELS = {
        "M": "M", "m": "M", "A": "A", "D": "D",
        "?": "?", "R": "R", "C": "C", "U": "!",
    }

    def __init__(self, root_dir: str) -> None:
        self.root_dir: str = os.path.abspath(root_dir)
        self.visible: bool = False
        self.active: bool = False
        self.items: list[git.GitFile] = []
        self.selected_idx: int = 0
        self.scroll_offset: int = 0
        # Mode: "normal" | "commit" | "branch_select" | "diff" | "issues" | "prs"
        self.mode: str = "normal"
        self.commit_message: str = ""
        self.branches: list[str] = []
        self.branch_idx: int = 0
        self.last_result: str = ""
        # Issues / PRs
        self.issues: list[github_api.GitHubIssue] = []
        self.prs: list[github_api.GitHubPR] = []
        self.issue_idx: int = 0
        self.pr_idx: int = 0

    # -- refresh ---------------------------------------------------- #

    def refresh(self) -> None:
        """Re-read ``git status`` and rebuild the file list."""
        if not git.is_git_repo(self.root_dir):
            self.items = []
            return
        self.items = git.get_status_files(self.root_dir)
        # Clamp selection
        if self.items and self.selected_idx >= len(self.items):
            self.selected_idx = len(self.items) - 1
        elif not self.items:
            self.selected_idx = 0

    # -- navigation ------------------------------------------------- #

    def move_selection(self, dy: int) -> None:
        if not self.items:
            self.selected_idx = 0
            return
        self.selected_idx = max(0, min(self.selected_idx + dy, len(self.items) - 1))

    def selected_file(self) -> Optional[git.GitFile]:
        if 0 <= self.selected_idx < len(self.items):
            return self.items[self.selected_idx]
        return None

    # -- stage / unstage -------------------------------------------- #

    def stage_selected(self) -> None:
        f = self.selected_file()
        if f and not f.staged:
            git.stage_file(self.root_dir, f.path)
            self.refresh()

    def unstage_selected(self) -> None:
        f = self.selected_file()
        if f and f.staged:
            git.unstage_file(self.root_dir, f.path)
            self.refresh()

    def stage_all(self) -> None:
        git.stage_all(self.root_dir)
        self.refresh()

    def unstage_all(self) -> None:
        git.unstage_all(self.root_dir)
        self.refresh()

    # -- commit ----------------------------------------------------- #

    def begin_commit(self) -> None:
        """Enter commit mode (type message, Enter to commit)."""
        self.mode = "commit"
        self.commit_message = ""

    def cancel_commit(self) -> None:
        self.mode = "normal"
        self.commit_message = ""

    def commit_char(self, ch: str) -> None:
        self.commit_message += ch

    def commit_backspace(self) -> None:
        self.commit_message = self.commit_message[:-1]

    def do_commit(self) -> str:
        """Commit with the current message.  Returns status text."""
        msg = self.commit_message.strip()
        if not msg:
            self.last_result = "Empty message"
            self.mode = "normal"
            return self.last_result
        ok = git.commit(self.root_dir, msg)
        self.mode = "normal"
        self.commit_message = ""
        self.refresh()
        self.last_result = "Committed" if ok else "Commit failed"
        return self.last_result

    # -- push / pull ------------------------------------------------ #

    def do_push(self) -> str:
        ok, out = git.push(self.root_dir)
        self.last_result = "Pushed" if ok else f"Push: {out}"
        return self.last_result

    def do_pull(self) -> str:
        ok, out = git.pull(self.root_dir)
        self.last_result = "Pulled" if ok else f"Pull: {out}"
        self.refresh()
        return self.last_result

    # -- branches --------------------------------------------------- #

    def begin_branch_select(self) -> None:
        self.branches = git.get_branches(self.root_dir)
        current = git.get_branch(self.root_dir)
        self.branch_idx = self.branches.index(current) if current in self.branches else 0
        self.mode = "branch_select"

    def cancel_branch_select(self) -> None:
        self.mode = "normal"

    def move_branch(self, dy: int) -> None:
        if self.branches:
            self.branch_idx = max(0, min(self.branch_idx + dy, len(self.branches) - 1))

    def do_switch_branch(self) -> str:
        if not self.branches:
            self.mode = "normal"
            return "No branches"
        branch = self.branches[self.branch_idx]
        ok, out = git.switch_branch(self.root_dir, branch)
        self.mode = "normal"
        self.refresh()
        self.last_result = f"Switched to {branch}" if ok else f"Switch: {out}"
        return self.last_result

    # -- diff ------------------------------------------------------- #

    def begin_diff(self) -> None:
        self.mode = "diff"

    def end_diff(self) -> None:
        self.mode = "normal"

    def get_selected_diff(self) -> str:
        f = self.selected_file()
        if not f:
            return ""
        if f.staged:
            return git.get_staged_diff(self.root_dir, f.path)
        return git.get_diff(self.root_dir, f.path)

    # -- stash ------------------------------------------------------ #

    def do_stash(self) -> str:
        ok = git.stash(self.root_dir)
        self.last_result = "Stashed" if ok else "Stash failed"
        self.refresh()
        return self.last_result

    def do_stash_pop(self) -> str:
        ok = git.stash_pop(self.root_dir)
        self.last_result = "Stash popped" if ok else "Stash pop failed"
        self.refresh()
        return self.last_result

    # -- issues ----------------------------------------------------- #

    def begin_issues(self) -> None:
        self.issues = github_api.list_issues(cwd=self.root_dir)
        self.issue_idx = 0
        self.mode = "issues"

    def cancel_issues(self) -> None:
        self.mode = "normal"

    def move_issue(self, dy: int) -> None:
        if self.issues:
            self.issue_idx = max(0, min(self.issue_idx + dy, len(self.issues) - 1))

    def selected_issue(self) -> github_api.GitHubIssue | None:
        if 0 <= self.issue_idx < len(self.issues):
            return self.issues[self.issue_idx]
        return None

    def do_close_issue(self) -> str:
        issue = self.selected_issue()
        if not issue:
            return "No issue selected"
        ok, out = github_api.close_issue(issue.number, cwd=self.root_dir)
        self.last_result = f"Closed #{issue.number}" if ok else f"Close: {out}"
        self.issues = github_api.list_issues(cwd=self.root_dir)
        if self.issue_idx >= len(self.issues):
            self.issue_idx = max(0, len(self.issues) - 1)
        return self.last_result

    def do_reopen_issue(self) -> str:
        issue = self.selected_issue()
        if not issue:
            return "No issue selected"
        ok, out = github_api.reopen_issue(issue.number, cwd=self.root_dir)
        self.last_result = f"Reopened #{issue.number}" if ok else f"Reopen: {out}"
        self.issues = github_api.list_issues(cwd=self.root_dir)
        return self.last_result

    # -- pull requests ----------------------------------------------- #

    def begin_prs(self) -> None:
        self.prs = github_api.list_prs(cwd=self.root_dir)
        self.pr_idx = 0
        self.mode = "prs"

    def cancel_prs(self) -> None:
        self.mode = "normal"

    def move_pr(self, dy: int) -> None:
        if self.prs:
            self.pr_idx = max(0, min(self.pr_idx + dy, len(self.prs) - 1))

    def selected_pr(self) -> github_api.GitHubPR | None:
        if 0 <= self.pr_idx < len(self.prs):
            return self.prs[self.pr_idx]
        return None

    def do_checkout_pr(self) -> str:
        pr = self.selected_pr()
        if not pr:
            return "No PR selected"
        ok, out = github_api.checkout_pr(pr.number, cwd=self.root_dir)
        self.last_result = f"Checked out PR #{pr.number}" if ok else f"Checkout: {out}"
        self.refresh()
        return self.last_result

    def do_merge_pr(self) -> str:
        pr = self.selected_pr()
        if not pr:
            return "No PR selected"
        ok, out = github_api.merge_pr(pr.number, cwd=self.root_dir)
        self.last_result = f"Merged PR #{pr.number}" if ok else f"Merge: {out}"
        self.prs = github_api.list_prs(cwd=self.root_dir)
        if self.pr_idx >= len(self.prs):
            self.pr_idx = max(0, len(self.prs) - 1)
        return self.last_result

    def do_close_pr(self) -> str:
        pr = self.selected_pr()
        if not pr:
            return "No PR selected"
        ok, out = github_api.close_pr(pr.number, cwd=self.root_dir)
        self.last_result = f"Closed PR #{pr.number}" if ok else f"Close: {out}"
        self.prs = github_api.list_prs(cwd=self.root_dir)
        if self.pr_idx >= len(self.prs):
            self.pr_idx = max(0, len(self.prs) - 1)
        return self.last_result


# ------------------------------------------------------------------ #
# Curses drawing
# ------------------------------------------------------------------ #

_STATUS_COLORS = {
    "M": curses.COLOR_YELLOW,
    "A": curses.COLOR_GREEN,
    "D": curses.COLOR_RED,
    "?": curses.COLOR_WHITE,
    "R": curses.COLOR_CYAN,
    "C": curses.COLOR_CYAN,
    "U": curses.COLOR_RED,
}

# Will be initialized once the curses color pair is set up
_PAIR_STAGED = 11
_PAIR_UNSTAGED = 12
_PAIR_HEADER = 13


def init_panel_colors() -> None:
    """Register color pairs for the git panel."""
    if not curses.has_colors():
        return
    curses.init_pair(_PAIR_STAGED, curses.COLOR_YELLOW, -1)
    curses.init_pair(_PAIR_UNSTAGED, curses.COLOR_WHITE, -1)
    curses.init_pair(_PAIR_HEADER, curses.COLOR_CYAN, -1)


def draw_git_panel(stdscr, panel: GitPanel, height: int, width: int) -> None:
    """Draw the source control panel on the left side."""
    if panel.mode == "diff":
        return  # diff is drawn as an overlay elsewhere

    # Draw vertical separator on the right edge
    for row in range(height):
        try:
            stdscr.addstr(row, width - 1, "\u2502", curses.A_DIM)
        except curses.error:
            pass

    row = 0

    # -- Header ----------------------------------------------------- #
    header = " SOURCE CONTROL "
    try:
        stdscr.addstr(row, 0, header.center(width - 1)[:width - 1],
                      curses.A_REVERSE | curses.A_BOLD)
    except curses.error:
        pass
    row += 1

    # -- Branch info ------------------------------------------------ #
    branch = git.get_branch(panel.root_dir)
    if branch:
        branch_text = f" \u25b6 {branch} "
        try:
            stdscr.addstr(row, 0, branch_text[:width - 1],
                          curses.color_pair(_PAIR_HEADER) | curses.A_BOLD)
        except curses.error:
            pass
        row += 1

    # -- Separator -------------------------------------------------- #
    try:
        stdscr.addstr(row, 0, "\u2500" * (width - 1), curses.A_DIM)
    except curses.error:
        pass
    row += 1

    # -- Commit mode ------------------------------------------------ #
    if panel.mode == "commit":
        try:
            stdscr.addstr(row, 0, " Commit message:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        try:
            msg_display = panel.commit_message[:width - 3]
            stdscr.addstr(row, 0, f" {msg_display}_", curses.A_UNDERLINE)
        except curses.error:
            pass
        row += 1
        try:
            stdscr.addstr(row, 0, " Enter=commit  Esc=cancel", curses.A_DIM)
        except curses.error:
            pass
        row += 1
        # Separator
        try:
            stdscr.addstr(row, 0, "\u2500" * (width - 1), curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Branch select mode ----------------------------------------- #
    if panel.mode == "branch_select":
        try:
            stdscr.addstr(row, 0, " Switch branch:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        visible_branches = panel.branches[:max(0, height - row - 3)]
        for i, b in enumerate(visible_branches):
            if row >= height - 1:
                break
            marker = "\u25b6 " if i == panel.branch_idx else "  "
            try:
                attr = curses.A_REVERSE if i == panel.branch_idx else 0
                stdscr.addstr(row, 0, f"{marker}{b}"[:width - 1], attr)
            except curses.error:
                pass
            row += 1
        try:
            stdscr.addstr(row, 0, " Enter=switch  Esc=cancel", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Issues mode ------------------------------------------------ #
    if panel.mode == "issues":
        try:
            stdscr.addstr(row, 0, " Issues:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        if not panel.issues:
            try:
                stdscr.addstr(row, 0, " No open issues", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            for i, issue in enumerate(panel.issues):
                if row >= height - 1:
                    break
                label = f"#{issue.number} {issue.title}"
                marker = " \u25cf " if i == panel.issue_idx else "   "
                display = f"{marker}{label}"
                try:
                    attr = curses.A_REVERSE if i == panel.issue_idx else 0
                    stdscr.addstr(row, 0, display[:width - 1], attr)
                except curses.error:
                    pass
                row += 1
        try:
            stdscr.addstr(row, 0, " o:close  r:reopen  Esc:back", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- PRs mode --------------------------------------------------- #
    if panel.mode == "prs":
        try:
            stdscr.addstr(row, 0, " Pull Requests:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        if not panel.prs:
            try:
                stdscr.addstr(row, 0, " No open PRs", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            for i, pr in enumerate(panel.prs):
                if row >= height - 1:
                    break
                label = f"PR #{pr.number} {pr.title}"
                marker = " \u25cf " if i == panel.pr_idx else "   "
                display = f"{marker}{label}"
                try:
                    attr = curses.A_REVERSE if i == panel.pr_idx else 0
                    stdscr.addstr(row, 0, display[:width - 1], attr)
                except curses.error:
                    pass
                row += 1
        try:
            stdscr.addstr(row, 0, " c:checkout  m:merge  Esc:back", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- File list -------------------------------------------------- #
    # Compute staging sections
    staged = [f for f in panel.items if f.staged]
    unstaged = [f for f in panel.items if not f.staged]

    # Section headers
    def _draw_section(label: str, count: int) -> None:
        nonlocal row
        if row >= height - 1:
            return
        text = f" {label} ({count})" if count else f" {label}"
        try:
            stdscr.addstr(row, 0, text[:width - 1],
                          curses.color_pair(_PAIR_HEADER) | curses.A_BOLD)
        except curses.error:
            pass
        row += 1

    def _draw_file(f: git.GitFile, is_selected: bool) -> None:
        nonlocal row
        if row >= height - 1:
            return
        status_char = panel.STATUS_LABELS.get(f.status, f.status)
        prefix = " \u25cf " if is_selected else "   "
        # Truncate path to fit
        avail = width - len(prefix) - 4  # status + space
        display_path = f.path
        if len(display_path) > avail:
            display_path = "..." + display_path[-(avail - 3):]
        text = f"{prefix}{status_char} {display_path}"
        try:
            attr = curses.A_REVERSE if is_selected else 0
            stdscr.addstr(row, 0, text[:width - 1], attr)
        except curses.error:
            pass
        row += 1

    _draw_section("Staged", len(staged))
    for f in staged:
        if row >= height - 1:
            break
        _draw_file(f, panel.items.index(f) == panel.selected_idx)

    _draw_section("Changes", len(unstaged))
    for f in unstaged:
        if row >= height - 1:
            break
        _draw_file(f, panel.items.index(f) == panel.selected_idx)

    if not panel.items:
        try:
            stdscr.addstr(row, 0, " No changes", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Bottom separator + hints ----------------------------------- #
    bottom = height - 1
    try:
        stdscr.addstr(bottom - 1, 0, "\u2500" * (width - 1), curses.A_DIM)
    except curses.error:
        pass
    hints = "c:commit s:stage u:unstage a:stage all d:diff p:push P:pull b:branch S:stash A:pop I:issues M:PRs"
    try:
        stdscr.addstr(bottom, 0, hints[:width - 1], curses.A_DIM)
    except curses.error:
        pass


# ------------------------------------------------------------------ #
# Key dispatch (returns True if the key was consumed)
# ------------------------------------------------------------------ #

def _is_up(key: str | int) -> bool:
    return key == "up" or key == "k" or key == curses.KEY_UP


def _is_down(key: str | int) -> bool:
    return key == "down" or key == "j" or key == curses.KEY_DOWN


def git_panel_key(panel: GitPanel, key: str | int) -> bool:
    """Handle a keypress when the git panel is active.

    Returns True if the key was consumed.
    """
    # Commit mode — any key
    if panel.mode == "commit":
        if key == "\n":
            panel.do_commit()
        elif key == "\x1b":
            panel.cancel_commit()
        elif key == curses.KEY_BACKSPACE or key == "\x7f":
            panel.commit_backspace()
        elif isinstance(key, str) and len(key) == 1 and key.isprintable():
            panel.commit_char(key)
        return True

    # Branch select mode
    if panel.mode == "branch_select":
        if key == "\n":
            panel.do_switch_branch()
        elif key == "\x1b":
            panel.cancel_branch_select()
        elif _is_up(key):
            panel.move_branch(-1)
        elif _is_down(key):
            panel.move_branch(1)
        return True

    # Diff mode
    if panel.mode == "diff":
        if key == "\x1b" or key == "q":
            panel.end_diff()
            return True
        return False  # let scroll keys pass through to diff viewer

    # Issues mode
    if panel.mode == "issues":
        if key == "\x1b":
            panel.cancel_issues()
        elif _is_up(key):
            panel.move_issue(-1)
        elif _is_down(key):
            panel.move_issue(1)
        elif key == "o":
            panel.do_close_issue()
        elif key == "r":
            panel.do_reopen_issue()
        else:
            return True
        return True

    # PRs mode
    if panel.mode == "prs":
        if key == "\x1b":
            panel.cancel_prs()
        elif _is_up(key):
            panel.move_pr(-1)
        elif _is_down(key):
            panel.move_pr(1)
        elif key == "c":
            panel.do_checkout_pr()
        elif key == "m":
            panel.do_merge_pr()
        else:
            return True
        return True

    # Normal mode
    if _is_up(key):
        panel.move_selection(-1)
    elif _is_down(key):
        panel.move_selection(1)
    elif key == "c":
        panel.begin_commit()
    elif key == "s":
        panel.stage_selected()
    elif key == "u":
        panel.unstage_selected()
    elif key == "a":
        panel.stage_all()
    elif key == "d":
        panel.begin_diff()
    elif key == "p":
        panel.do_push()
    elif key == "P":
        panel.do_pull()
    elif key == "b":
        panel.begin_branch_select()
    elif key == "S":
        panel.do_stash()
    elif key == "A":
        panel.do_stash_pop()
    elif key == "I":
        panel.begin_issues()
    elif key == "M":
        panel.begin_prs()
    else:
        return False
    return True
