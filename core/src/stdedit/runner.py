"""runner.py — run the current file in an external terminal.

``run_file()`` picks a terminal emulator the way ``filemanager.py`` picks a
folder picker (first installed wins), builds a language-appropriate command
from the file extension, and launches a detached ``bash -c`` script in that
terminal.  Only the Python standard library is imported (shutil, subprocess,
shlex, tempfile); the runtimes and the terminal are optional binaries that
must already be on the system.

The spawned terminal is decorated: the window title is set to
``stdedit — run <file>``, the program output is indented two cells so it
aligns inside a boxed banner naming the interpreter, file, and command, and
the run ends on a full-width bottom bar showing the exit code plus further
actions (``r`` rerun, ``e`` edit, ``Enter`` close).  Decoration can be tuned
per run:

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


def _wrap(text: str, width: int) -> List[str]:
    """Wrap *text* to *width* cells at word boundaries (no mid-token cuts).

    Continuation rows keep their text intact so shell paths are never split
    in a misleading spot; the caller indents them as needed.  A single
    unbreakable token longer than *width* is hard-split into width-wide
    pieces.
    """
    if width < 1:
        return []
    text = text.replace("\n", " ").replace("\t", " ")
    rows: List[str] = []
    current = ""
    for word in text.split(" "):
        if len(word) > width:
            if current:
                rows.append(current)
                current = ""
            while len(word) > width:
                rows.append(word[:width])
                word = word[width:]
        candidate = word if not current else current + " " + word
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                rows.append(current)
            current = word
    if current:
        rows.append(current)
    return rows if rows else [""]


def _pad_line(inner: str, width: int) -> List[str]:
    """Frame *inner* as one or more ``│ … │`` rows of exactly *width* cells.

    Additional rows wrap long content and are indented two cells inside the
    box so ``file:`` / ``cmd:`` continuations keep a clean visual indent.
    """
    inner_width = max(width - 4, 0)
    rows = []
    for idx, piece in enumerate(_wrap(inner, inner_width)):
        body = ("  " if idx else "") + piece
        body = body[:inner_width]
        rows.append("│ " + body + " " * (inner_width - len(body)) + " │")
    return rows


def _bash_squote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _frame_lines(path: str, runtime_label: str, icon: str,
                 command: str, width: int) -> List[str]:
    base = os.path.basename(path) or path
    head = f"▶ {runtime_label}  {icon} {base}" if icon else f"▶ {runtime_label}  {base}"
    return [
        "┌" + "─" * (width - 2) + "┐",
        *_pad_line(head, width),
        *_pad_line(f"file: {os.path.abspath(path)}", width),
        *_pad_line(f"cmd: {command}", width),
        "├" + "─" * (width - 2) + "┤",
    ]


def _emit_frame(lines: List[str]) -> str:
    return "".join(f"printf '%s\\n' {_bash_squote(line)}\n" for line in lines)


def _helper_block(width: int) -> str:
    """Bash helper definitions shared by the rerun loop."""
    return (
        f"_w={width}\n"
        f"_pad() {{ local -i n=$(( _w - ${{#1}} - 4 )); "
        f"[ \"$n\" -lt 0 ] && n=0; printf '│ %s%*s │\\n' \"$1\" \"$n\" \"\"; }}\n"
        "_clear() { printf '\\033[2J\\033[H'; }\n"
    )


def _status_block(colors: bool) -> str:
    """Color-coded ``✔ / ✖ finished — exit N`` detail plus the box border."""
    if colors:
        ok = ("printf '\\x1b[32m'; _pad '✔ finished — exit '\"$rc\"; "
              "printf '\\x1b[0m'\n")
        fail = ("printf '\\x1b[31m'; _pad '✖ finished — exit '\"$rc\"; "
                "printf '\\x1b[0m'\n")
    else:
        ok = "_pad '✔ finished — exit '\"$rc\"\n"
        fail = "_pad '✖ finished — exit '\"$rc\"\n"
    return (
        "  if [ \"$rc\" -eq 0 ]; then\n"
        f"    {ok}"
        "  else\n"
        f"    {fail}"
        "  fi\n"
        "  printf '└'; printf '─%.0s' $(seq 1 $(( _w - 2 ))); printf '┘\\n'\n"
    )


def _bar_block(colors: bool) -> str:
    """Full-width bottom bar: exit code + available key actions."""
    bar = (
        "  local bar=\" exit: $rc  │  [r] rerun  [e] edit  [Enter] close \"\n"
        "  while [ \"${#bar}\" -lt $(( _w )) ]; do bar=\"$bar \"; done\n"
    )
    render = (f"  printf '\\x1b[7m%s\\x1b[0m\\n' \"$bar\"\n"
              if colors else "  printf '%s\\n' \"$bar\"\n")
    return bar + render


def _loop_block(quoted: str) -> str:
    """Loop body: rerun on ``r``, edit-then-rerun on ``e``, close otherwise."""
    return (
        "while true; do\n"
        "  run_once\n"
        "  read -n 1 -s -r k || break\n"
        '  case "$k" in\n'
        "    r|R) continue ;;\n"
        f"    e|E) if command -v stdedit >/dev/null 2>&1; then stdedit {quoted}; fi; continue ;;\n"
        "    *) break ;;\n"
        "  esac\n"
        "done\n"
    )


def _build_script(path: str, command: str, runtime: str = "", icon: str = "",
                  raw: bool = False, colors: bool = True,
                  width: int = _STDEDIT_RUN_WIDTH) -> str:
    """Build the ``bash -c`` payload for *path* and *command*.

    With ``raw=False`` the script sets the terminal window title, frames the
    run in a boxed banner, feeds the program output through a 2-space indenter
    so it lines up inside the box, and finishes on a full-width bottom bar
    carrying the exit code and further actions (``r`` rerun, ``e`` edit in
    stdedit, ``Enter`` close).  ``raw=True`` returns the plain script (no
    decoration); ``colors=False`` keeps the frame and title but emits no ANSI
    SGR codes.
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
    run_once = (
        "run_once() {\n"
        + "  _clear\n"
        + _emit_frame(_frame_lines(path, label, icon, command, width))
        + f"  {{ {command}; }} 2>&1 | sed 's/^/  /'\n"
        + "  rc=${PIPESTATUS[0]}\n"
        + "  echo\n"
        + _status_block(colors)
        + _bar_block(colors)
        + "}\n"
    )
    return (
        title
        + _helper_block(width)
        + f'cd "$(dirname -- {quoted})" 2>/dev/null\n'
        + f"trap 'rm -f {out} 2>/dev/null' EXIT\n"
        + run_once
        + _loop_block(quoted)
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