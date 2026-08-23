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
    # Creation
    # ------------------------------------------------------------------ #
    def selected_directory(self) -> str:
        """Directory where new entries created from the tree are placed.

        A selected directory receives the entry inside itself; a selected
        file gets it as a sibling; `<..>` or an empty tree falls back to
        the tree root.
        """
        selected = self.get_selected()
        if not selected:
            return self.root_dir
        _, _, path, is_dir = selected
        if path == PARENT:
            return self.root_dir
        if is_dir:
            return path
        return os.path.dirname(path)

    @staticmethod
    def _validate_entry_name(name: str) -> Optional[str]:
        """Return an error message for an invalid entry name, else None."""
        if not name:
            return "Name cannot be empty"
        if name in (".", ".."):
            return f"Invalid name: {name}"
        seps = {os.sep}
        if os.altsep:
            seps.add(os.altsep)
        if "/" in name or any(sep in name for sep in seps):
            return "Name must be a single path component"
        return None

    def _select_path(self, path: str) -> None:
        for i, item in enumerate(self.items):
            if item[2] == path:
                self.selected_idx = i
                return

    def create_file(self, name: str) -> Tuple[str, Optional[str]]:
        """Create an empty file in the target directory.

        Returns (path, error). On success the parent folder is expanded,
        the tree refreshed and the new file selected.
        """
        name = name.strip()
        error = self._validate_entry_name(name)
        if error:
            return "", error
        base = self.selected_directory()
        path = os.path.join(base, name)
        try:
            with open(path, "x"):
                pass
        except FileExistsError:
            return path, f"'{name}' already exists"
        except OSError as exc:
            return path, f"Cannot create file: {exc}"
        self.expanded_dirs.add(base)
        self.refresh()
        self._select_path(path)
        return path, None

    def create_folder(self, name: str) -> Tuple[str, Optional[str]]:
        """Create a directory in the target directory.

        Returns (path, error). On success the new folder is expanded and
        selected.
        """
        name = name.strip()
        error = self._validate_entry_name(name)
        if error:
            return "", error
        base = self.selected_directory()
        path = os.path.join(base, name)
        try:
            os.mkdir(path)
        except FileExistsError:
            return path, f"'{name}' already exists"
        except OSError as exc:
            return path, f"Cannot create folder: {exc}"
        self.expanded_dirs.add(path)
        self.refresh()
        self._select_path(path)
        return path, None

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
