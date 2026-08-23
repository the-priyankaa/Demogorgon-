"""
explorer.py — file tree explorer panel. stdlib only.
"""

from __future__ import annotations

import os
import pathlib
from typing import List, Tuple, Set, Optional


class FileExplorer:
    def __init__(self, root_dir: str = ".") -> None:
        self.root_dir = os.path.abspath(root_dir)
        self.expanded_dirs: Set[str] = set()
        # Flattened visible items: list of (depth, display_name, absolute_path, is_dir)
        self.items: List[Tuple[int, str, str, bool]] = []
        self.selected_idx = 0
        self.visible = False
        self.active = False

        # Expand the root directory by default
        self.expanded_dirs.add(self.root_dir)
        self.refresh()

    def refresh(self) -> None:
        """Walk the directory tree and rebuild the flat list of visible items."""
        self.items = []
        self._build_tree(self.root_dir, 0)
        # Handle bounds
        if not self.items:
            self.selected_idx = 0
        else:
            self.selected_idx = min(self.selected_idx, len(self.items) - 1)

    def _build_tree(self, current_dir: str, depth: int) -> None:
        """Recursively list contents of a directory if it is expanded."""
        try:
            entries = os.listdir(current_dir)
        except OSError:
            return

        # Sort: directories first, then files
        dirs = []
        files = []
        for name in entries:
            # Ignore hidden files/dirs and typical python/git/env caches
            if name.startswith("."):
                if name in (".git", ".idea", ".DS_Store", ".vscode"):
                    continue
            if name in ("__pycache__", "venv", ".venv", "node_modules"):
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

    def toggle_expand(self, idx: int) -> None:
        """Toggle expansion of directory at given index."""
        if 0 <= idx < len(self.items):
            depth, name, path, is_dir = self.items[idx]
            if is_dir:
                if path in self.expanded_dirs:
                    self.expanded_dirs.remove(path)
                else:
                    self.expanded_dirs.add(path)
                self.refresh()

    def get_selected(self) -> Optional[Tuple[int, str, str, bool]]:
        """Return the currently selected item."""
        if 0 <= self.selected_idx < len(self.items):
            return self.items[self.selected_idx]
        return None

    def move_selection(self, dy: int) -> None:
        """Move cursor selection up or down."""
        if self.items:
            self.selected_idx = max(0, min(len(self.items) - 1, self.selected_idx + dy))
