"""Quick Open — fuzzy file search engine (no curses dependency).

Builds a flat index of all files in the project tree and scores them
against a typed query.  Pure stdlib, no third-party dependencies.
"""
from __future__ import annotations

import os
from typing import List, Tuple

from . import recent


def build_file_index(root_dir: str) -> List[str]:
    """Walk *root_dir* and return a sorted list of absolute file paths.

    Directories listed in ``FileExplorer.ALWAYS_IGNORED_NAMES`` are
    skipped.  The result is suitable for fuzzy matching.
    """
    from .explorer import FileExplorer  # deferred to avoid circular

    ignore = FileExplorer.ALWAYS_IGNORED_NAMES
    ignore_suffixes = FileExplorer.ALWAYS_IGNORED_SUFFIXES
    files: list[str] = []
    root_dir = os.path.abspath(root_dir)

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Prune ignored directories in-place so os.walk skips them.
        dirnames[:] = [
            d for d in dirnames
            if d not in ignore and not any(d.endswith(s) for s in ignore_suffixes)
        ]
        for fname in filenames:
            if any(fname.endswith(s) for s in ignore_suffixes):
                continue
            files.append(os.path.join(dirpath, fname))

    files.sort()
    return files


def _fuzzy_score(query: str, path: str) -> float:
    """Score how well *query* matches *path*.

    Returns a float >= 0 (higher is better) or -1 for no match.
    Scoring bonuses:
      - Exact basename prefix match
      - Contiguous character runs
      - Fewer gaps between matched chars
      - Shorter paths preferred (less penalty for deep paths)
    """
    if not query:
        return 0.0

    q_lower = query.lower()
    basename = os.path.basename(path).lower()
    full_lower = path.lower()

    # --- phase 1: check if all query chars appear in order ---------------
    qi = 0
    matches: list[int] = []  # indices in full_lower that matched
    for i, ch in enumerate(full_lower):
        if qi < len(q_lower) and ch == q_lower[qi]:
            matches.append(i)
            qi += 1
    if qi < len(q_lower):
        return -1.0  # not all query chars found

    # --- phase 2: score --------------------------------------------------
    score = 0.0

    # Contiguous runs bonus: longer contiguous runs score higher.
    max_run = 1
    cur_run = 1
    for j in range(1, len(matches)):
        if matches[j] == matches[j - 1] + 1:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1
    score += max_run * 10.0

    # Gaps penalty: distance between first and last match character.
    span = matches[-1] - matches[0] + 1
    score -= span * 0.5

    # Basename bonus: prefer matches in the filename over deep paths.
    basename_start = path.rfind("/") + 1
    in_basename = all(m >= basename_start for m in matches)
    if in_basename:
        score += 20.0

    # Exact basename prefix bonus.
    if basename.startswith(q_lower):
        score += 30.0

    # Shorter path bonus.
    score -= len(path) * 0.01

    return score


def fuzzy_search(
    query: str,
    files: List[str],
    limit: int = 20,
) -> List[Tuple[float, str]]:
    """Return up to *limit* ``(score, path)`` tuples sorted best-first.

    Empty query returns an empty list (caller should show recent files
    or a hint instead).
    """
    if not query:
        return []

    scored: list[tuple[float, str]] = []
    for path in files:
        s = _fuzzy_score(query, path)
        if s >= 0:
            scored.append((s, path))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:limit]


def get_recent_matches(
    query: str,
    limit: int = 5,
) -> List[Tuple[float, str]]:
    """Score recent files against *query* and return top matches."""
    if not query:
        return []
    recent_files = recent.get_recent()
    # Filter to files that still exist on disk.
    existing = [p for p in recent_files if os.path.isfile(p)]
    return fuzzy_search(query, existing, limit=limit)


class QuickOpen:
    """Quick Open overlay state — builds index, searches, navigates."""

    def __init__(self, root_dir: str = ".") -> None:
        self.root_dir: str = os.path.abspath(root_dir)
        self.files: list[str] = []
        self.query: str = ""
        self.results: list[tuple[float, str]] = []
        self.selected_idx: int = 0
        self.visible: bool = False

    def open(self) -> None:
        """Show the overlay and build the file index."""
        self.files = build_file_index(self.root_dir)
        self.query = ""
        self.results = []
        self.selected_idx = 0
        self.visible = True

    def close(self) -> None:
        """Hide the overlay."""
        self.visible = False
        self.query = ""
        self.results = []

    def update_query(self, query: str) -> None:
        """Re-score results for the new query string."""
        self.query = query
        self.results = fuzzy_search(query, self.files)
        self.selected_idx = 0

    def move_selection(self, dy: int) -> None:
        """Move cursor up/down, clamped to results."""
        total = len(self.results)
        if total:
            self.selected_idx = max(0, min(self.selected_idx + dy, total - 1))

    def selected_path(self) -> str | None:
        """Return the absolute path of the selected result, or None."""
        if 0 <= self.selected_idx < len(self.results):
            return self.results[self.selected_idx][1]
        return None

    def get_display_items(self, limit: int = 20) -> list[tuple[str, bool]]:
        """Return ``(display_path, is_selected)`` pairs for rendering.

        If the query is empty, recent files are shown instead.
        """
        if not self.query:
            recent_items = recent.get_recent()
            existing = [p for p in recent_items if os.path.isfile(p)][:limit]
            return [(p, i == self.selected_idx) for i, p in enumerate(existing)]

        return [
            (path, i == self.selected_idx)
            for i, (_, path) in enumerate(self.results[:limit])
        ]
