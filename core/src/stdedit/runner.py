"""runner.py — run the current file in an external terminal.

``run_file()`` picks a terminal emulator the way ``filemanager.py`` picks a
folder picker (first installed wins), builds a language-appropriate command
from the file extension, and launches a detached ``bash -c`` script in that
terminal.  Only the Python standard library is imported (shutil, subprocess,
shlex, tempfile); the runtimes and the terminal are optional binaries that
must already be on the system.

The spawned terminal is decorated: the window title is set to
``stdedit — run <file>`` and the output is framed by a boxed banner naming
the interpreter, file, and command, plus a colored ``finished — exit N``
footer.  Decoration can be tuned per run:

  ``STDEDIT_RUN_RAW=1``  plain script, no title/banner/colors (test hook)
  ``NO_COLOR``           keep the frame and title, drop ANSI colors
  ``STDEDIT_ICONS=0``    omit the file icon (matches the editor)

``STDEDIT_TERMINAL`` overrides terminal detection (a command name),
mirroring the ``STDEDIT_FAKE_GHOST`` / ``STDEDIT_PICK_FOLDER`` test hooks:
point it at a script that records argv for end-to-end checks.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from typing import Callable, List, Optional, Tuple

from . import icons

# Fixed frame width in terminal cells.  Content is laid out in Python so the
# border stays pixel-exact regardless of multibyte glyphs.
_STDEDIT_RUN_WIDTH = 70

_STDEDIT_TERMINAL_ENV = "STDEDIT_TERMINAL"
_STDEDIT_RUN_RAW_ENV = "STDEDIT_RUN_RAW"
_NO_COLOR_ENV = "NO_COLOR"

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

# Display names for the frame banner, keyed by the runtime executable.
_RUNTIME_LABELS = {
    "python": "Python",
    "python3": "Python 3",
    "node": "Node.js",
    "npx": "TypeScript (tsx)",
    "java": "Java",
    "gcc": "C (gcc)",
    "g++": "C++ (g++)",
    "rustc": "Rust",
    "go": "Go",
    "bash": "Shell (bash)",
    "sh": "Shell (sh)",
    "zsh": "Shell (zsh)",
    "perl": "Perl",
    "ruby": "Ruby",
    "php": "PHP",
    "lua": "Lua",
    "luajit": "Lua (luajit)",
    "Rscript": "R",
    "dotnet": ".NET",
    "mono": "C# (mono)",
    "kotlin": "Kotlin",
    "swift": "Swift",
}


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
    command, display = run_command_for(path, _which=_which)
    if command is None:
        return False, display
    environ = env if env is not None else os.environ
    raw = environ.get(_STDEDIT_RUN_RAW_ENV) == "1"
    colors = not raw and _NO_COLOR_ENV not in environ
    runtime = display.split(None, 1)[0] if display else ""
    glyph = icons.icon_for_file(path, icons.enabled_from_env(environ))
    script = _build_script(path, command, runtime=runtime, icon=glyph,
                           raw=raw, colors=colors)
    argv = launcher + ["bash", "-c", script]
    try:
        _popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               start_new_session=True)
    except OSError as exc:
        return False, f"Could not launch terminal: {exc}"
    emulator = launcher[0].split("/")[-1]
    return True, f"Running: {display} ({emulator})"


def _runtime_label(runtime: str) -> str:
    return _RUNTIME_LABELS.get(runtime, runtime)


def _sanitize(text: str) -> str:
    """Strip control characters from a window title."""
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f")


def _fit(text: str, width: int) -> str:
    """Truncate *text* to *width* display cells, marking cuts with a '…'."""
    if width < 1:
        return ""
    text = text.replace("\n", " ").replace("\t", " ")
    if len(text) > width:
        return text[: width - 1] + "…"
    return text


def _pad_line(inner: str, width: int) -> str:
    inner = _fit(inner, max(width - 4, 0))
    pad = max(width - 4 - len(inner), 0)
    return "│ " + inner + " " * pad + " │"


def _bash_squote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _frame_lines(path: str, runtime_label: str, icon: str,
                 command: str, width: int) -> List[str]:
    base = os.path.basename(path) or path
    head = f"▶ {runtime_label}  {icon} {base}" if icon else f"▶ {runtime_label}  {base}"
    return [
        "┌" + "─" * (width - 2) + "┐",
        _pad_line(head, width),
        _pad_line(f"file: {os.path.abspath(path)}", width),
        _pad_line(f"cmd: {command}", width),
        "├" + "─" * (width - 2) + "┤",
    ]


def _emit_frame(lines: List[str]) -> str:
    return "".join(f"printf '%s\\n' {_bash_squote(line)}\n" for line in lines)


def _footer_block(width: int, colors: bool) -> str:
    """Bash lines that render the closing frame after ``$rc`` is set."""
    pad = (
        f"_pad() {{ local -i n=$(( _w - ${{#1}} - 4 )); "
        f"[ \"$n\" -lt 0 ] && n=0; printf '│ %s%*s │\\n' \"$1\" \"$n\" \"\"; }}\n"
    )
    ok = (f"printf '\\x1b[32m'; "
          f"_pad '✔ finished — exit '\"$rc\"; "
          f"printf '\\x1b[0m'"
          if colors else "_pad '✔ finished — exit '\"$rc\"")
    fail = (f"printf '\\x1b[31m'; "
            f"_pad '✖ finished — exit '\"$rc\"; "
            f"printf '\\x1b[0m'"
            if colors else "_pad '✖ finished — exit '\"$rc\"")
    return (
        pad
        + f"_w={width}\n"
        + "if [ \"$rc\" -eq 0 ]; then\n"
        + f"  {ok}\n"
        + "else\n"
        + f"  {fail}\n"
        + "fi\n"
        + "_pad '[stdedit] press Enter to close'\n"
        + f"printf '└'; printf '─%.0s' $(seq 1 $(( _w - 2 ))); printf '┘\\n'\n"
        + "read -r _\n"
    )


def _build_script(path: str, command: str, runtime: str = "", icon: str = "",
                  raw: bool = False, colors: bool = True,
                  width: int = _STDEDIT_RUN_WIDTH) -> str:
    """Build the ``bash -c`` payload for *path* and *command*.

    With ``raw=False`` the script sets the terminal window title and frames
    the run in a boxed banner + colored exit footer.  ``raw=True`` returns
    the plain script (no decoration); ``colors=False`` keeps the frame and
    title but emits no ANSI SGR codes.
    """
    quoted = shlex.quote(os.path.abspath(path))
    out = _temp_out()
    plain = (
        f'cd "$(dirname -- {quoted})" 2>/dev/null\n'
        f"{command}\n"
        "rc=$?\n"
        f"trap 'rm -f {out} 2>/dev/null' EXIT\n"
        "echo\n"
        'echo "[stdedit] finished (exit $rc) — press Enter to close"\n'
        "read -r _\n"
    )
    if raw:
        return plain
    label = _runtime_label(runtime)
    base = _sanitize(os.path.basename(path) or path)
    title_text = f"stdedit — run {base}"
    if runtime:
        title_text += f" ({label})"
    title = ("printf '\\033]0;%s\\007' '"
             + title_text.replace("'", "'\\''") + "'\n")
    return (
        title
        + _emit_frame(_frame_lines(path, label, icon, command, width))
        + f'cd "$(dirname -- {quoted})" 2>/dev/null\n'
        + f"trap 'rm -f {out} 2>/dev/null' EXIT\n"
        + f"{command}\n"
        + "rc=$?\n"
        + _footer_block(width, colors=colors)
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