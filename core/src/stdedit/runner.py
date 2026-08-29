"""runner.py — run the current file in an external terminal.

``run_file()`` picks a terminal emulator the way ``filemanager.py`` picks a
folder picker (first installed wins), builds a language-appropriate command
from the file extension, and launches a detached ``bash -c`` script in that
terminal.  Only the Python standard library is imported (shutil, subprocess,
shlex, tempfile); the runtimes and the terminal are optional binaries that
must already be on the system.

The ``STDEDIT_TERMINAL`` env var overrides terminal detection (a command
name), mirroring the ``STDEDIT_FAKE_GHOST`` / ``STDEDIT_PICK_FOLDER`` test
hooks: point it at a script that records argv for end-to-end checks.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from typing import Callable, List, Optional, Tuple

# Terminal emulators, most specific first.  Each entry is (name, argv prefix);
# ``bash -c <script>`` is appended to run the program and keep the window open.
_STDEDIT_TERMINAL_ENV = "STDEDIT_TERMINAL"

_TERMINAL_LAUNCHERS: List[Tuple[str, List[str]]] = [
    ("kitty", ["kitty", "-e"]),
    ("gnome-terminal", ["gnome-terminal", "--"]),
    ("konsole", ["konsole", "-e"]),
    ("xfce4-terminal", ["xfce4-terminal", "-x"]),
    ("alacritty", ["alacritty", "-e"]),
    ("foot", ["foot", "-e"]),
    ("wezterm", ["wezterm", "start", "--"]),
    ("mate-terminal", ["mate-terminal", "-x"]),
    ("tilix", ["tilix", "-e"]),
    ("terminator", ["terminator", "-x"]),
    ("xterm", ["xterm", "-e"]),
    ("uxterm", ["uxterm", "-e"]),
    ("urxvt", ["urxvt", "-e"]),
    ("x-terminal-emulator", ["x-terminal-emulator", "-e"]),
]

# Extension -> (runtime executable, command template).
# "{path}" is the quoted absolute file path; "{out}" is a per-run temp binary
# (used by compiled languages, removed by the wrapper script).
_RUNTIMES = {
    ".py":    ("python3", "python3 {path}"),
    ".pyw":   ("python3", "python3 {path}"),
    ".js":    ("node", "node {path}"),
    ".mjs":   ("node", "node {path}"),
    ".jsx":   ("npx", "npx --yes tsx {path}"),
    ".ts":    ("npx", "npx --yes tsx {path}"),
    ".tsx":   ("npx", "npx --yes tsx {path}"),
    ".java":  ("java", "java {path}"),
    ".c":     ("gcc", "gcc {path} -o {out} && {out}"),
    ".h":     ("gcc", "gcc {path} -o {out} && {out}"),
    ".cpp":   ("g++", "g++ {path} -o {out} && {out}"),
    ".cc":    ("g++", "g++ {path} -o {out} && {out}"),
    ".cxx":   ("g++", "g++ {path} -o {out} && {out}"),
    ".C":     ("g++", "g++ {path} -o {out} && {out}"),
    ".rs":    ("rustc", "rustc {path} -o {out} && {out}"),
    ".go":    ("go", "go run {path}"),
    ".sh":    ("bash", "bash {path}"),
    ".bash":  ("bash", "bash {path}"),
    ".zsh":   ("zsh", "zsh {path}"),
    ".pl":    ("perl", "perl {path}"),
    ".rb":    ("ruby", "ruby {path}"),
    ".php":   ("php", "php {path}"),
    ".lua":   ("lua", "lua {path}"),
    ".r":     ("Rscript", "Rscript {path}"),
    ".R":     ("Rscript", "Rscript {path}"),
}

# Fallback: run with whatever POSIX shell is available.
_SHELL_FALLBACKS = ("bash", "zsh", "sh")

# Extensions with no executable to run.
_NON_RUNNABLE = frozenset({".md", ".markdown", ".html", ".htm", ".css", ".scss",
                           ".sass", ".json", ".yaml", ".yml", ".sql", ".xml",
                           ".svg", ".xhtml", ".txt"})


def terminal_launcher(
    _which: Callable[[str], Optional[str]] = shutil.which,
    env: dict | None = None,
) -> Optional[List[str]]:
    """Return the argv prefix for the best available terminal, or None."""
    environ = env if env is not None else os.environ
    forced = environ.get(_STDEDIT_TERMINAL_ENV)
    if forced:
        name = forced.split()[0]
        rest = forced.split()[1:]
        candidate = [name] + rest
        if _which(name):
            return candidate
        return None
    for name, prefix in _TERMINAL_LAUNCHERS:
        if _which(name):
            return list(prefix)
    return None


def _runtime_for(ext: str) -> Optional[Tuple[str, str]]:
    return _RUNTIMES.get(ext)


def run_command_for(
    path: str,
    _which: Callable[[str], Optional[str]] = shutil.which,
) -> Tuple[Optional[str], str]:
    """Return (shell_command, display) or (None, reason) for *path*."""
    ext = _os_ext(path)
    if not ext:
        return None, f"No runner for {ext_label(path)}"
    if ext in _NON_RUNNABLE:
        return None, f"No run command for {ext}"
    spec = _runtime_for(ext)
    if spec is None:
        return None, f"No runner for {ext}"
    runtime, template = spec
    if runtime == "bash" and not _which("bash"):
        chosen = next((s for s in _SHELL_FALLBACKS if _which(s)), None)
        if chosen is None:
            return None, f"Runtime '{runtime}' not found for {ext}"
        runtime = chosen
        spec = (runtime, f"{runtime} {{path}}")
        template = spec[1]
    if not _which(runtime):
        return None, f"Runtime '{runtime}' not found for {ext}"
    quoted = shlex.quote(os.path.abspath(path))
    return (template.format(path=quoted, out=_temp_out()),
            f"{runtime} {path}")


def run_file(
    path: str,
    _which: Callable[[str], Optional[str]] = shutil.which,
    _popen: Callable[..., object] = subprocess.Popen,
    env: dict | None = None,
) -> Tuple[bool, str]:
    """Open *path* in an external terminal and run it.

    Returns (ok, status): on success status names the interpreter and the
    terminal used; on failure it explains why (no terminal, no runtime, no
    runner, launch error).
    """
    if not path:
        return False, "Nothing to run"
    launcher = terminal_launcher(_which=_which, env=env)
    if launcher is None:
        return False, "No terminal emulator found (install kitty, gnome-terminal, ...)"
    command, reason = run_command_for(path, _which=_which)
    if command is None:
        return False, reason
    script = _build_script(path, command)
    argv = launcher + ["bash", "-c", script]
    try:
        _popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               start_new_session=True)
    except OSError as exc:
        return False, f"Could not launch terminal: {exc}"
    emulator = launcher[0].split("/")[-1]
    return True, f"Running: {reason_display(command, path)} ({emulator})"


def reason_display(command: str, path: str) -> str:
    """Short human label for the status bar, e.g. 'python3 …/sample.py'."""
    first = command.split(";")[0].strip()
    head = first.split()[0] if first else ""
    return f"{head} {path}"


def _build_script(path: str, command: str) -> str:
    quoted = shlex.quote(os.path.abspath(path))
    out = _temp_out()
    return (
        f'cd "$(dirname -- {quoted})" 2>/dev/null\n'
        f"{command}\n"
        f"rc=$?\n"
        f"trap 'rm -f {out} 2>/dev/null' EXIT\n"
        f'echo\n'
        f'echo "[stdedit] finished (exit $rc) — press Enter to close"\n'
        f"read -r _\n"
    )


def _temp_out() -> str:
    return os.path.join(tempfile.gettempdir(), f"stdedit-run-{os.getpid()}")


def _os_ext(path: str) -> str:
    base = os.path.basename(path)
    dot = base.rfind(".")
    if dot <= 0:
        return ""
    return base[dot:]


def ext_label(path: str) -> str:
    ext = _os_ext(path)
    return ext if ext else path