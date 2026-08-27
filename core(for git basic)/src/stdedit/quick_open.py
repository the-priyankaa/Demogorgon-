"""Quick Open — responsive fuzzy file search engine (stdlib only).

The index is built in a background thread so opening the picker never blocks
curses input.  Results are updated as files are discovered and a direct path
fallback lets an explicitly typed file open even before the background scan
finishes.
"""
from __future__ import annotations

import os
import threading
from typing import Iterable, List, Tuple

from . import recent


def _normalize_excludes(exclude_roots: list[str] | None) -> list[str]:
    return [os.path.abspath(os.path.expanduser(p)) for p in (exclude_roots or [])]


def _is_excluded(path: str, excluded: list[str]) -> bool:
    path = os.path.abspath(path)
    return any(path == ex or path.startswith(ex + os.sep) for ex in excluded)


def _iter_file_index(root_dir: str, exclude_roots: list[str] | None = None) -> Iterable[str]:
    """Yield searchable files under *root_dir* without blocking callers."""
    from .explorer import FileExplorer  # deferred to avoid circular imports

    ignore = FileExplorer.ALWAYS_IGNORED_NAMES
    ignore_suffixes = FileExplorer.ALWAYS_IGNORED_SUFFIXES
    root_dir = os.path.abspath(os.path.expanduser(root_dir))
    excluded = _normalize_excludes(exclude_roots)

    for dirpath, dirnames, filenames in os.walk(root_dir):
        if _is_excluded(dirpath, excluded):
            dirnames[:] = []
            continue

        kept_dirs = []
        for d in dirnames:
            if d in ignore or any(d.endswith(s) for s in ignore_suffixes):
                continue
            if d.startswith(".") and d not in {".config"}:
                continue
            full = os.path.join(dirpath, d)
            if _is_excluded(full, excluded):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fname in filenames:
            if any(fname.endswith(s) for s in ignore_suffixes):
                continue
            yield os.path.join(dirpath, fname)


def build_file_index(root_dir: str, exclude_roots: list[str] | None = None) -> List[str]:
    """Walk *root_dir* and return a sorted list of absolute file paths."""
    files = list(_iter_file_index(root_dir, exclude_roots))
    files.sort()
    return files


def _fuzzy_score(query: str, path: str) -> float:
    """Score how well *query* matches *path*.

    Returns a float >= 0 (higher is better) or -1 for no match.
    """
    if not query:
        return 0.0

    q_lower = query.lower()
    basename = os.path.basename(path).lower()
    full_lower = path.lower()

    qi = 0
    matches: list[int] = []
    for i, ch in enumerate(full_lower):
        if qi < len(q_lower) and ch == q_lower[qi]:
            matches.append(i)
            qi += 1
    if qi < len(q_lower):
        return -1.0

    score = 0.0
    max_run = 1
    cur_run = 1
    for j in range(1, len(matches)):
        if matches[j] == matches[j - 1] + 1:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1
    score += max_run * 10.0

    span = matches[-1] - matches[0] + 1
    score -= span * 0.5

    basename_start = path.rfind(os.sep) + 1
    in_basename = all(m >= basename_start for m in matches)
    if in_basename:
        score += 20.0

    if basename.startswith(q_lower):
        score += 30.0

    score -= len(path) * 0.01
    return score


def fuzzy_search(query: str, files: List[str], limit: int = 20) -> List[Tuple[float, str]]:
    """Return up to *limit* ``(score, path)`` tuples sorted best-first."""
    if not query:
        return []

    scored: list[tuple[float, str]] = []
    for path in files:
        s = _fuzzy_score(query, path)
        if s >= 0:
            scored.append((s, path))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:limit]


def get_recent_matches(query: str, limit: int = 5) -> List[Tuple[float, str]]:
    """Score recent files against *query* and return top matches."""
    if not query:
        return []
    existing = [p for p in recent.get_recent() if os.path.isfile(p)]
    return fuzzy_search(query, existing, limit=limit)


class QuickOpen:
    """Responsive Quick Open overlay state with asynchronous indexing."""

    BATCH_SIZE = 256

    def __init__(
        self,
        root_dir: str = ".",
        exclude_roots: list[str] | None = None,
        show_recent_on_empty: bool = False,
    ) -> None:
        self.root_dir: str = os.path.abspath(os.path.expanduser(root_dir))
        self.exclude_roots: list[str] = list(exclude_roots or [])
        self.files: list[str] = []
        self.query: str = ""
        self.results: list[tuple[float, str]] = []
        self.selected_idx: int = 0
        self.visible: bool = False
        self.show_recent_on_empty = show_recent_on_empty
        self.loading: bool = False
        self.scan_error: str | None = None
        self._scan_thread: threading.Thread | None = None
        self._scan_stop = threading.Event()
        self._generation = 0
        self._lock = threading.RLock()

    def _refresh_results_locked(self) -> None:
        if self.query:
            self.results = fuzzy_search(self.query, self.files)
            # Keep the current selection valid as results change in the
            # background.  Never let a disappearing result create a bogus path.
            self.selected_idx = min(self.selected_idx, max(0, len(self.results) - 1))
        else:
            self.results = []
            self.selected_idx = 0

    def _scan_worker(self, stop_event: threading.Event, generation: int) -> None:
        try:
            batch: list[str] = []
            for path in _iter_file_index(self.root_dir, self.exclude_roots):
                if stop_event.is_set():
                    return
                batch.append(path)
                if len(batch) >= self.BATCH_SIZE:
                    with self._lock:
                        if generation != self._generation or stop_event.is_set():
                            return
                        self.files.extend(batch)
                        self._refresh_results_locked()
                    batch.clear()
            if batch:
                with self._lock:
                    if generation != self._generation or stop_event.is_set():
                        return
                    self.files.extend(batch)
                    self.files.sort()
                    self._refresh_results_locked()
            with self._lock:
                if generation == self._generation and not stop_event.is_set():
                    self.loading = False
        except Exception as exc:  # defensive: search must never kill the TUI
            with self._lock:
                if generation == self._generation and not stop_event.is_set():
                    self.scan_error = str(exc)
                    self.loading = False

    def open(self, background_index: bool = True) -> None:
        """Show the overlay immediately; optionally index files in the background."""
        self._scan_stop.set()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self.files = []
            self.query = ""
            self.results = []
            self.selected_idx = 0
            self.scan_error = None
            self.visible = True
            self.loading = bool(background_index)
        self._scan_stop = threading.Event()
        if not background_index:
            return
        stop_event = self._scan_stop
        self._scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(stop_event, generation),
            name="stdedit-quick-open-index",
            daemon=True,
        )
        self._scan_thread.start()

    def close(self) -> None:
        """Hide the overlay and stop any outstanding scan."""
        self._scan_stop.set()
        with self._lock:
            self.visible = False
            self.query = ""
            self.results = []
            self.selected_idx = 0
            self.loading = False

    def update_query(self, query: str) -> None:
        """Re-score currently indexed files immediately."""
        with self._lock:
            self.query = query
            self._refresh_results_locked()

    def move_selection(self, dy: int) -> None:
        """Move cursor up/down, clamped to results."""
        with self._lock:
            total = len(self.results)
            if total:
                self.selected_idx = max(0, min(self.selected_idx + dy, total - 1))

    def _direct_candidate(self) -> str | None:
        """Resolve an explicitly typed existing path without waiting for indexing."""
        query = self.query.strip()
        if not query:
            return None

        candidates: list[str] = []
        if os.path.isabs(query):
            candidates.append(os.path.abspath(os.path.expanduser(query)))
        else:
            candidates.append(os.path.abspath(os.path.join(self.root_dir, query)))
            if os.sep not in query:
                candidates.append(os.path.abspath(os.path.expanduser("~") + os.sep + query))

        for path in candidates:
            if not os.path.isfile(path):
                continue
            if _is_excluded(path, _normalize_excludes(self.exclude_roots)):
                continue
            return path
        return None

    def selected_path(self) -> str | None:
        """Return selected result, or a directly typed existing path."""
        with self._lock:
            if 0 <= self.selected_idx < len(self.results):
                return self.results[self.selected_idx][1]
            direct = self._direct_candidate()
            return direct

    def get_display_items(self, limit: int = 20) -> list[tuple[str, bool]]:
        """Return display items without exposing a partially-written list."""
        with self._lock:
            if not self.query:
                if not self.show_recent_on_empty:
                    return []
                existing = [p for p in recent.get_recent() if os.path.isfile(p)][:limit]
                return [(p, False) for p in existing]

            return [
                (path, i == self.selected_idx)
                for i, (_, path) in enumerate(self.results[:limit])
            ]
