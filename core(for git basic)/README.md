# stdedit

A terminal text editor with **zero runtime dependencies** — everything is
Python standard library. Built for [hackathon] Track A.

- Reimplements the core of `nano`/`micro`-style editing: open, navigate,
  edit, undo/redo, select/copy/cut/paste, save.
- Regex-based syntax highlighting infrastructure; the current core ships Python and leaves additional language packs to the language layer.
- Full substitution log: see [`STDLIB.md`](./STDLIB.md).

## Install

`carl` sets the editor up on a machine in one shot — venv, editable
install, and global launchers (`stdedit`, `yuki`, `carl`) in
`~/.local/bin`:

```bash
make install        # or: PYTHONPATH=src python3 -m stdedit.install install
```

Rerunning it is safe: it repairs/refreshes the links and picks up code
changes. Inspect the installation with `carl status`; remove it again
with `make uninstall` (add `--purge` to also delete `.venv`).

### Dependencies

There are **no Python packages to install** — the editor is standard
library only. The only hard requirement is Python ≥ 3.9. Optional OS
helpers (zenity/kdialog for the folder picker, xdg-open for file-manager
reveal) are checked and can be auto-installed:

```bash
make deps          # or: carl deps    - report what's present/missing
make deps-fix      # or: carl deps --fix - install missing helpers
```

## Quick start

The editor is available as the `stdedit` command — and as the `yuki`
alias launcher:

```bash
stdedit path/to/file.py        # edit a file (tree roots at its folder)
stdedit path/to/project        # open a whole project (positional dir)
stdedit --project ~/myapp x.py # project root + file, explicitly
```

Without a global install, run it from this folder:

```bash
make run FILE=path/to/file.py
# or directly:
PYTHONPATH=src python3 -m stdedit.main path/to/file.py
```

Open a whole project folder — the file tree is rooted there:

```bash
make run ARGS="--project /path/to/project"
# or combined with a file:
PYTHONPATH=src python3 -m stdedit.main --project /path/to/project src/x.py
```

Inside the editor the tree keys **O** / **R** pick a project root via the
system folder picker (zenity/kdialog) and reveal the current root in the
desktop's file manager (xdg-open), falling back gracefully when absent.

## Keys

Press **Ctrl-H** (or **F1**) inside the editor for the built-in guide —
every keybinding with descriptions, grouped by area; scroll with
arrow keys / PgUp / PgDn; close it with `q`, `Esc`, or `Enter`. On
terminals that merge Ctrl-H with Backspace, F1 always works, and
Backspace opens the guide while the file tree is focused.

**Quick-create:** pressing `n` in the file tree creates the file and
opens it immediately in the editor for editing (unsaved-changes guard
still applies). **Ctrl-O** with a nonexistent path offers to create
the file before opening it.

## Font (optional — icons)

The status bar and file tree use **Nerd Font** language icons (Python,
JavaScript, Rust …).  Icons are on by default and need a Nerd Font to
render; without one, disable them:

```bash
STDEDIT_ICONS=0 yuki <file>
```

Recommended font: **MesloLGS NF** — set it in your terminal:

| Terminal          | How                                                          |
|-------------------|--------------------------------------------------------------|
| GNOME Terminal    | Preferences → Custom font → MesloLGS NF                     |
| kitty             | `font_family MesloLGS NF` in `~/.config/kitty/kitty.conf`   |
| iTerm2            | Profiles → Text → Font → MesloLGS NF                        |
| Windows Terminal  | `fontFace` → `"MesloLGS NF"` in settings.json               |
| Alacritty         | `font.family` → `"MesloLGS NF"` in alacritty.toml           |

## Run tests

```bash
make test
```

## Prove zero dependencies

```bash
make proof
cat deps-proof.txt
```

## Project layout

```
src/stdedit/
  buffer.py         # line buffer, cursor, undo/redo, selection, clipboard, indent
  compact.py        # compact bytearray line storage for large documents
  mapped.py         # memory-mapped read-mostly line store for huge files
  undo.py           # snapshot-based undo/redo manager
  perf.py           # RSS / frame-time instrumentation
  tui.py            # curses front end (keymap, rendering, status bar)
  explorer.py       # file tree explorer panel (Ctrl-E)
  search.py         # incremental search + find/replace-all (stub)
  extensions/       # extension API + loader
    api.py
    loader.py
  languages/
    schema.py        # token-rule schema + per-language definitions
examples/
  extensions/        # example extensions (word count, vim demo, ...)
tools/
  bench_memory.py    # core Buffer RSS benchmark
tests/
  test_buffer.py     # unit tests for the buffer core
  test_languages.py  # language detection + tokenizer tests
```

## Team split

| Area | Owner | Covers |
|---|---|---|
| TUI / rendering | Person A | curses loop, keymap, status bar, tabs, resize handling |
| Buffer / undo    | Person B | line buffer, cursor, undo/redo, selection, clipboard, indent, file I/O |
| Languages / search | Person C | tokenizer schema, syntax highlighting, incremental search, replace-all |

See `.zero-dep.toml` for the dependency pledge and `STDLIB.md` for the
substitution rationale.

## Known limitations

- `curses` is Unix-only (not tested on native Windows; WSL/macOS/Linux work).
- Syntax highlighting is regex-based, not a full parser — good enough for
  editing, not for semantic analysis.

## Status

The Person-B core is implemented and tested: open/save, cursor/scrolling,
undo/redo, selection/copy/cut/paste, auto-indent, tabs↔spaces, bracket
matching/auto-close, bracketed-paste handling, large-file undo protection,
RAM/performance instrumentation, and a stdlib-only extension API.

## Core memory/performance

- The TUI includes a low-frequency Linux RSS meter and frame-time indicator without third-party dependencies.
- Undo/redo history is bounded by both operation count (500) and a conservative 32 MiB history-memory budget.
- A single snapshot larger than the history budget is not retained, so very large files do not create another full-buffer history copy.
- `tools/bench_memory.py` measures the core Buffer RSS for representative file sizes.


## Extensions

stdedit has a small optional Python extension API. Extensions are loaded from:

1. `STDEDIT_EXTENSIONS` (one or more directories separated by `:` on Linux)
2. `.stdedit/extensions/` in the current project
3. `~/.config/stdedit/extensions/`

An extension is a normal Python file exposing `setup(api)` (or `register(api)`).
It can add commands, key handlers, lifecycle callbacks, and status-bar text.
Extension import failures are isolated so a broken plugin cannot prevent the core
editor from starting.

Example files are in `examples/extensions/`.

Use `--no-extensions` to start the editor without loading user extensions.

## External extensions

Extensions are normal Python files; they are **not imported by default** so the
base editor keeps its RSS low. Put them in `.stdedit/extensions/` in a project
or `~/.config/stdedit/extensions/`, or point `STDEDIT_EXTENSIONS` at a directory.

Load one by name:

```sh
make run FILE=MARK1.py ARGS="--extension vim_command"
```

or directly:

```sh
python -m stdedit.main MARK1.py --extension vim_command
python -m stdedit.main MARK1.py --extension-file /path/to/my_extension.py
```

See what is available without importing anything:

```sh
python -m stdedit.main --list-extensions
```

To deliberately load every discovered extension:

```sh
python -m stdedit.main MARK1.py --all-extensions
```

The extension API supports commands, key bindings, lifecycle hooks and status
providers. Extension code is isolated so a broken extension does not crash the
core editor.
