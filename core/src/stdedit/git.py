"""Git operations via subprocess (no Python git library).

All functions shell out to the ``git`` CLI with a short timeout and
return safe defaults when git is unavailable or the directory is not
a repository.  No third-party dependencies — stdlib only.
"""
from __future__ import annotations

import subprocess
from typing import Optional

_TIMEOUT = 2  # seconds


def _run(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess | None:
    """Run a git command with a timeout.  Returns None on any failure."""
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def is_git_repo(path: str) -> bool:
    """Return True if *path* is inside a git working tree."""
    r = _run(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return r is not None and r.returncode == 0 and "true" in r.stdout.lower()


def get_branch(path: str) -> Optional[str]:
    """Return the current branch name, or None on failure.

    Detached HEAD returns ``None`` rather than a raw hash so the status
    bar can fall back cleanly.
    """
    r = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    if r is None or r.returncode != 0:
        return None
    branch = r.stdout.strip()
    return branch if branch and branch != "HEAD" else None


def get_ahead_behind(path: str) -> tuple[int, int]:
    """Return ``(ahead, behind)`` counts vs upstream, or ``(0, 0)``."""
    r = _run(["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
             cwd=path)
    if r is None or r.returncode != 0:
        return (0, 0)
    parts = r.stdout.strip().split()
    if len(parts) >= 2:
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            pass
    return (0, 0)


def get_status_counts(path: str) -> dict[str, int]:
    """Return counts of modified, added, deleted, and untracked files.

    Returns ``{"modified": 0, "added": 0, "deleted": 0, "untracked": 0}``
    on any failure or when *path* is not a git repo.
    """
    defaults = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0}
    r = _run(["status", "--porcelain"], cwd=path)
    if r is None or r.returncode != 0:
        return defaults
    counts = dict(defaults)
    for line in r.stdout.splitlines():
        if not line:
            continue
        code = line[:2].strip()
        if code in ("M", " m"):
            counts["modified"] += 1
        elif code in ("A", "A "):
            counts["added"] += 1
        elif code in ("D", " D"):
            counts["deleted"] += 1
        elif code == "??":
            counts["untracked"] += 1
        elif code in ("R", "C"):
            counts["modified"] += 1
        elif code in ("U", "UU", "AA", "DD"):
            counts["modified"] += 1
    return counts


def format_status_counts(counts: dict[str, int]) -> str:
    """Format status counts into a compact string like ``+3 ~1 -0 !2``.

    Zero-count segments are omitted for brevity.  Empty string when
    everything is clean.
    """
    parts = []
    if counts.get("added"):
        parts.append(f"+{counts['added']}")
    if counts.get("modified"):
        parts.append(f"~{counts['modified']}")
    if counts.get("deleted"):
        parts.append(f"-{counts['deleted']}")
    if counts.get("untracked"):
        parts.append(f"!{counts['untracked']}")
    return " ".join(parts)


# ------------------------------------------------------------------ #
# Status file list (for the source control panel)
# ------------------------------------------------------------------ #

class GitFile:
    """A single file entry from ``git status --porcelain``."""
    __slots__ = ("status", "path", "staged")

    def __init__(self, status: str, path: str, staged: bool) -> None:
        self.status = status   # "M", "A", "D", "?", "R", "C", "U", etc.
        self.path = path
        self.staged = staged

    def display_status(self) -> str:
        """Human-readable short status for the panel."""
        return self.status


def get_status_files(path: str) -> list[GitFile]:
    """Return the list of changed files from ``git status --porcelain``.

    Each entry carries a status letter, path, and whether it is staged
    (index) vs. unstaged (worktree).
    """
    r = _run(["status", "--porcelain"], cwd=path)
    if r is None or r.returncode != 0:
        return []
    files: list[GitFile] = []
    for line in r.stdout.splitlines():
        if not line:
            continue
        index_code = line[0]
        work_code = line[1]
        filepath = line[3:]
        # Index (staged) changes
        if index_code != " " and index_code != "?":
            files.append(GitFile(index_code, filepath, staged=True))
        # Worktree (unstaged) changes
        if work_code != " " and work_code != "?":
            files.append(GitFile(work_code, filepath, staged=False))
        # Untracked
        if index_code == "?" and work_code == "?":
            files.append(GitFile("?", filepath, staged=False))
    return files


# ------------------------------------------------------------------ #
# Diff
# ------------------------------------------------------------------ #

def get_diff(path: str, filepath: str | None = None) -> str:
    """Return unified diff of unstaged changes."""
    args = ["diff"]
    if filepath:
        args += ["--", filepath]
    r = _run(args, cwd=path)
    return r.stdout if r is not None else ""


def get_staged_diff(path: str, filepath: str | None = None) -> str:
    """Return unified diff of staged changes."""
    args = ["diff", "--cached"]
    if filepath:
        args += ["--", filepath]
    r = _run(args, cwd=path)
    return r.stdout if r is not None else ""


# ------------------------------------------------------------------ #
# Stage / unstage
# ------------------------------------------------------------------ #

def stage_file(path: str, filepath: str) -> bool:
    """Stage a single file (``git add <file>``)."""
    r = _run(["add", filepath], cwd=path)
    return r is not None and r.returncode == 0


def unstage_file(path: str, filepath: str) -> bool:
    """Unstage a single file (``git reset HEAD <file>``)."""
    r = _run(["reset", "HEAD", "--", filepath], cwd=path)
    return r is not None and r.returncode == 0


def stage_all(path: str) -> bool:
    """Stage all changes (``git add -A``)."""
    r = _run(["add", "-A"], cwd=path)
    return r is not None and r.returncode == 0


def unstage_all(path: str) -> bool:
    """Unstage all files (``git reset HEAD``)."""
    r = _run(["reset", "HEAD"], cwd=path)
    return r is not None and r.returncode == 0


# ------------------------------------------------------------------ #
# Commit / push / pull
# ------------------------------------------------------------------ #

def commit(path: str, message: str) -> bool:
    """Commit all staged changes."""
    r = _run(["commit", "-m", message], cwd=path)
    return r is not None and r.returncode == 0


def push(path: str) -> tuple[bool, str]:
    """Push current branch. Returns (success, output)."""
    r = _run(["push"], cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def pull(path: str) -> tuple[bool, str]:
    """Pull from remote. Returns (success, output)."""
    r = _run(["pull"], cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


# ------------------------------------------------------------------ #
# Branches
# ------------------------------------------------------------------ #

def get_branches(path: str) -> list[str]:
    """Return list of local branch names."""
    r = _run(["branch", "--format=%(refname:short)"], cwd=path)
    if r is None or r.returncode != 0:
        return []
    return [b.strip() for b in r.stdout.splitlines() if b.strip()]


def switch_branch(path: str, branch: str) -> tuple[bool, str]:
    """Switch to a branch. Returns (success, output)."""
    r = _run(["checkout", branch], cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def create_branch(path: str, branch: str) -> bool:
    """Create a new branch from HEAD."""
    r = _run(["checkout", "-b", branch], cwd=path)
    return r is not None and r.returncode == 0


# ------------------------------------------------------------------ #
# Stash
# ------------------------------------------------------------------ #

def stash(path: str) -> bool:
    """Stash all changes."""
    r = _run(["stash"], cwd=path)
    return r is not None and r.returncode == 0


def stash_pop(path: str) -> bool:
    """Pop the most recent stash."""
    r = _run(["stash", "pop"], cwd=path)
    return r is not None and r.returncode == 0


# ------------------------------------------------------------------ #
# Log
# ------------------------------------------------------------------ #

def get_log(path: str, count: int = 10) -> list[dict[str, str]]:
    """Return recent commits as ``[{hash, message, author}]``."""
    r = _run(
        ["log", f"-{count}", "--format=%h|%s|%an"],
        cwd=path,
    )
    if r is None or r.returncode != 0:
        return []
    result = []
    for line in r.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            result.append({"hash": parts[0], "message": parts[1], "author": parts[2]})
    return result
