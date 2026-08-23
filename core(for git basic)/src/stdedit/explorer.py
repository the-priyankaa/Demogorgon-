"""
explorer.py — file tree explorer panel. stdlib only.

Features:
  - Tree rooted at any directory (set_root), normally the opened file's
    parent folder.
  - "<..>" entry to climb to the parent directory while keeping the
    expansion state of previously visited subdirectories.
  - Hidden files/dirs are filtered by default; `show_hidden` flips that.
  - Tracks the currently open file so the TUI can highlight it.
"""

from __future__ import annotations

import os
from typing import List, Optional, Set, Tuple

# Sentinel path used for the parent-directory pseudo entry.
PARENT = ".."

Item = Tuple[int, str, str, bool]  # depth, display_name, absolute_path, is_dir


class FileExplorer:
    IGNORED_NAMES = {"__pycache__", "venv", ".venv", "node_modules"}

    def __init__(self, root_dir: str = ".") -> None:
        self.root_dir = os.path.abspath(root_dir)
        self.expanded_dirs: Set[str] = {self.root_dir}
        # Flattened visible items: (depth, display_name, absolute_path, is_dir).
        # The parent pseudo entry uses the literal ".." path.
        self.items: List[Item] = []
        self.selected_idx = 0
        # The tree is part of the default layout: shown and focused on
        # launch. Esc/Tab moves focus to the editor; Ctrl-E hides the panel.
        self.visible = True
        self.active = True
        self.show_hidden = False
        self.current_path: Optional[str] = None
        self.refresh()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_root(self, path: str) -> None:
        """Re-root the tree (e.g. at the opened file's parent folder)."""
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
        self.root_dir = path
        self.expanded_dirs.add(path)
        self.selected_idx = 0
        self.refresh()

    def can_go_up(self) -> bool:
        """True unless we are already at the filesystem root."""
        return os.path.dirname(self.root_dir) != self.root_dir

    def go_up(self) -> None:
        """Climb one directory level, selecting the folder we came from."""
        if not self.can_go_up():
            return
        old_root = self.root_dir
        self.root_dir = os.path.dirname(old_root)
        self.expanded_dirs.add(self.root_dir)
        self.refresh()
        # Put the cursor on the directory we just climbed out of.
        for i, (_, _, path, is_dir) in enumerate(self.items):
            if is_dir and path == old_root:
                self.selected_idx = i
                break

    def toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.refresh()

    def refresh(self) -> None:
        """Walk the directory tree and rebuild the flat list of visible items."""
        self.items = []
        if self.can_go_up():
            self.items.append((0, PARENT, PARENT, False))
        self._build_tree(self.root_dir, 0)
        if not self.items:
            self.selected_idx = 0
        else:
            self.selected_idx = min(self.selected_idx, len(self.items) - 1)

    def toggle_expand(self, idx: int) -> None:
        """Toggle expansion of the directory at the given index."""
        if 0 <= idx < len(self.items):
            _, _, path, is_dir = self.items[idx]
            if is_dir:
                if path in self.expanded_dirs:
                    self.expanded_dirs.remove(path)
                else:
                    self.expanded_dirs.add(path)
                self.refresh()

    def get_selected(self) -> Optional[Item]:
        """Return the currently selected item."""
        if 0 <= self.selected_idx < len(self.items):
            return self.items[self.selected_idx]
        return None

    def move_selection(self, dy: int) -> None:
        """Move the selection up or down, clamped to the list bounds."""
        if self.items:
            self.selected_idx = max(0, min(len(self.items) - 1, self.selected_idx + dy))

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _is_visible(self, name: str) -> bool:
        if name in self.IGNORED_NAMES:
            return False
        if name.startswith("."):
            return self.show_hidden
        return True

    def _build_tree(self, current_dir: str, depth: int) -> None:
        """Recursively list contents of a directory if it is expanded."""
        try:
            entries = os.listdir(current_dir)
        except OSError:
            return

        dirs, files = [], []
        for name in entries:
            if not self._is_visible(name):
                continue
            full_path = os.path.join(current_dir, name)
            if os.path.isdir(full_path):
                dirs.append((name, full_path))
            else:
                files.append((name, full_path))

        dirs.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[0].lower())

        for name, path in dirs:
            is_expanded = path in self.expanded_dirs
            marker = "▼" if is_expanded else "▶"
            self.items.append((depth, f"{marker} {name}", path, True))
            if is_expanded:
                self._build_tree(path, depth + 1)

        for name, path in files:
            self.items.append((depth, f"  {name}", path, False))
