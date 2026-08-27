<!-- Update this file after every feature/keybind change -->

# YUKI

Zero-dependency terminal text editor. Python stdlib only.

![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)
![Zero Deps](https://img.shields.io/badge/deps-zero-brightgreen)
![Tests](https://img.shields.io/badge/tests-440-passing)
![Version](https://img.shields.io/badge/version-0.1.0-orange)

## Quick Start

```bash
git clone <repo-url> && cd "core(for git basic)"
make install          # creates venv + symlinks to ~/.local/bin
stdedit myfile.py     # or: yuki myfile.py
```

Run without installing:

```bash
PYTHONPATH=src python3 -m stdedit.main myfile.py
```

## Features

**Core Editing**
- Line-based text buffer with cursor movement and scrolling
- Undo / redo (memory-bounded: 500 snapshots / 32 MB cap)
- Selection (character, word, line, select-all, shift-click, drag)
- Clipboard (internal + system via `wl-copy` / `xclip` / `pbcopy`)
- Auto-close brackets `(` `{` `[` and quotes `"` `'`
- Smart auto-indent per language
- Tab / space conversion with configurable width
- Find (`Ctrl-F`) and Replace All (`Ctrl-R`) with live highlighting
- Large file support (8 MB+): memory-mapped reads, compact byte-array storage

**Syntax Highlighting** — 17 languages: Python, JavaScript, TypeScript, HTML, CSS, C, C++, Java, Rust, Go, JSON, YAML, Markdown, Shell, SQL, XML, plaintext

**Panels & Overlays**
- File Explorer (`Ctrl-E`): tree view, search, create, delete, rename, copy path
- Source Control (`Ctrl-G`): stage, unstage, commit, push, pull, branch switch, stash
- Quick Open (`Ctrl-O`): fuzzy file search
- Diff Viewer: scrollable unified diff with syntax colors
- Settings (`Ctrl-P`): auto-save mode, font family selection
- Help (`Ctrl-H` / `F1`): scrollable keybinding reference

**Git & GitHub**
- Branch detection, status counts, ahead/behind upstream
- Stage / unstage / commit / push / pull / stash
- Branch listing and switching
- Issues (list / close / reopen) via `gh` CLI
- Pull requests (list / checkout / merge) via `gh` CLI

**AI Completions** — Codeium inline ghost-text suggestions (opt-in via API key)

**Extensions** — Plugin system with `setup(api)` / `register(api)` lifecycle, 3 search paths, isolated error handling

**Zero Dependencies** — Every import is Python stdlib. Verified by `make proof`.

## Keyboard Shortcuts

### Editing

```
characters          type to insert text at the cursor
Enter               new line (auto-indents per language)
Tab                 indent (width adapts to the language)
Backspace / Del     delete character
< > ^ v             move cursor
Home / End          jump to line start / end
( { [               auto-close bracket pairs
) } ]               skip closer / dedent on block close
" '                 auto-close quotes
Ctrl-F              find text in the file
Ctrl-R              replace all occurrences
```

### Selection & Clipboard

```
Ctrl-A              select all
Ctrl-Space          start / stop selection ([SELECT] in status)
                    (arrow keys extend the selection while it is active)
Ctrl-C              copy selection
Ctrl-X              cut selection
Ctrl-V              paste (system + internal clipboard)
```

### History & Files

```
Ctrl-Z              undo
Ctrl-Y              redo
Ctrl-S              save current file
Ctrl-P              settings / preferences
Ctrl-O              quick open — fuzzy file search
Ctrl-Q              quit (press again to force with changes)
```

### File Tree (Ctrl-E panel)

```
Ctrl-E              open / focus the file tree
^ v                 move selection
< >                 collapse / expand folder (<..> climbs up)
Enter               open file / expand folder / go up on <..>
/                   search files and folders (Esc to cancel)
Esc                 close the file tree
h                   show / hide dotfiles
n                   new file (opens it for editing)
N                   new folder in selected folder
d                   delete file / folder (with confirmation)
r                   rename file / folder
y                   copy absolute path to clipboard
Y                   copy relative path to clipboard
O                   pick project root via system dialog
R                   reveal root in system file manager
Tab / Esc           focus the editor
```

### Git Status

```
status bar          shows branch name and change counts
                    +N added  ~N modified  -N deleted  !N untracked
automatic           refreshes every 2 seconds (no manual trigger)
```

### Source Control (Ctrl-G panel)

```
Ctrl-G              open / close source control panel
Up / Down           move selection
c                   focus commit message box
Enter               commit (when message box focused)
Esc                 cancel commit / defocus panel
s                   stage selected file
u                   unstage selected file
S                   stage all changes
U                   unstage all changes
d                   show diff for selected file
p                   push
P                   pull
R                   refresh status
b                   switch branch
I                   list issues (o:close r:reopen)
M                   list PRs (c:checkout m:merge)
Tab / Ctrl-G / Esc  focus the editor
```

### Diff Viewer

```
d / Space           page down
u                   page up
Up / Down           scroll one line
g / G               jump to top / bottom
q / Esc             close diff view
```

### Quick Open (Ctrl-O overlay)

```
type to filter      fuzzy search across project files
Up / Down           move selection
Enter               open selected file
Esc / Ctrl-O        close quick open
Backspace           delete last query character
```

### Settings (Ctrl-P panel)

```
Ctrl-P              open / close settings panel
Up / Down           navigate settings
Space               toggle selected setting
q / Esc / Ctrl-P    close settings panel
```

### Mouse

```
click               position cursor
double-click        select word
triple-click        select line
drag                select text
Shift+click         extend selection
scroll wheel        scroll up / down
```

### Terminal & Prompts

```
terminal paste      bracketed paste inserts multi-line text
typed prompts       Enter confirms, Esc cancels
prompt Tab          autocomplete file paths
prompt Backspace    edits the text (new file/folder, O fallback)
icons               Nerd Font glyphs (e.g. MesloLGS NF);
                    disable with STDEDIT_ICONS=0

(prompts appear for n / O and the O path fallback)
```

### Help

```
Ctrl-H or F1        open / close this guide
Up / Down, PgUp/Dn  scroll this guide
q / Esc / Enter     close this guide
```

## CLI Usage

```
stdedit [file] [options]
```

| Option | Description |
|--------|-------------|
| `file` | File to open (or directory to open as project) |
| `--project DIR` | Folder the file tree is rooted at |
| `--tab-size INT` | Tab width in spaces (default: 4) |
| `--tabs` | Use literal tab characters instead of spaces |
| `--large-file-mb INT` | Disable undo snapshots at this size (default: 8 MB) |
| `--extension NAME` | Load one external extension by name (repeatable) |
| `--extension-file PATH` | Load one external extension file (repeatable) |
| `--all-extensions` | Load every discovered extension |
| `--list-extensions` | List discovered extensions and exit |

## Install with carl

```bash
make install        # create venv, pip install editable, symlink to ~/.local/bin
make uninstall      # remove symlinks
make deps           # check optional OS helpers (zenity, xdg-open, etc.)
make deps-fix       # auto-install missing helpers via detected package manager
```

`carl` supports: apt-get, dnf, yum, pacman, zypper, apk, brew.

## Configuration

| File | Purpose |
|------|---------|
| `~/.config/stdedit/settings.json` | Editor settings (auto-save mode, font family) |
| `~/.config/stdedit/recent.json` | Recently opened files (max 50) |

**Auto-save modes:** off (default), on idle (5s), periodic (30s), on every edit

**Font family:** Detects installed monospace fonts via `fc-list` and tries to switch terminal font via OSC 50 escape sequences (works in xterm, Konsole, iTerm2; best-effort in other terminals).

## Extensions

### Write an extension

Create a `.py` file in any of these paths:
- `$STDEDIT_EXTENSIONS/`
- `.stdedit/extensions/`
- `~/.config/stdedit/extensions/`

```python
# my_extension.py
def setup(api):
    api.extension("my-ext", "1.0", "Does something cool")

    def on_save(editor):
        # your logic here
        pass

    api.bind_key("\x12", lambda editor: print("Ctrl-R pressed"))  # Ctrl-R
    api.add_status(lambda editor: "custom status text")
```

### API methods

| Method | Description |
|--------|-------------|
| `api.extension(name, version, description)` | Register extension metadata |
| `api.bind_key(key, callback)` | Bind a key to a callback |
| `api.add_command(name, callback)` | Register a named command |
| `api.add_status(callback)` | Add text to the status bar |
| `api.on_startup(callback)` | Run code when editor starts |
| `api.on_shutdown(callback)` | Run code when editor exits |

### Example extensions

| Extension | Key | Description |
|-----------|-----|-------------|
| `word_count.py` | (status only) | Live word/char count in status bar |
| `reverse_line.py` | Ctrl-R | Reverses the current line |
| `vim_command.py` | Ctrl-B | Toggles Vim-mode status indicator |

## Development

### Makefile commands

| Command | Description |
|---------|-------------|
| `make run FILE=file.py` | Run the editor |
| `make test` | Run all tests (440 tests) |
| `make proof` | Verify zero dependencies |
| `make clean` | Remove `__pycache__` and artifacts |

### Architecture

- **UI-agnostic core** — `Buffer` has no curses dependency, fully unit-testable
- **Graceful degradation** — All external tools (clipboard, git, gh, fc-list, zenity) timeout and return safe defaults
- **Bounded memory** — Undo capped at 500 snapshots / 32 MB; large files use mmap-backed reads
- **Extension isolation** — Each extension imported in its own namespace; failures don't crash the editor
- **Subprocess-only integration** — git, gh, clipboard tools, font detection all use `subprocess.run` with short timeouts

## Project Structure

```
src/stdedit/
├── main.py              CLI entry point (argparse)
├── buffer.py            Core text buffer engine (UI-agnostic)
├── tui.py               Curses front-end (main event loop)
├── undo.py              Memory-bounded snapshot undo/redo
├── clipboard.py         System clipboard (wl-copy, xclip, pbcopy)
├── completion.py        Path tab-completion
├── diff_viewer.py       Scrollable unified-diff overlay
├── explorer.py          File tree explorer panel
├── filemanager.py       System file-manager integration
├── font_detect.py       Monospace font detection (fc-list)
├── git.py               Git operations via subprocess
├── git_panel.py         Source control panel (VS Code-style)
├── github_api.py        GitHub CLI (gh) integration
├── codeium.py           Codeium AI inline-completion
├── icons.py             Nerd Font glyph mapping
├── install.py           'carl' installer (venv + symlinks)
├── perf.py              RSS memory + frame timing
├── quick_open.py        Fuzzy file search
├── recent.py            Recently opened files (JSON)
├── settings.py          Persistent editor settings (JSON)
├── languages/
│   └── schema.py        Regex tokenizer + language detection (17 languages)
├── extensions/
│   ├── api.py           Extension API (commands, keybinds, lifecycle)
│   └── loader.py        Extension discovery & lazy loading
└── storage/
    ├── compact.py       Compact byte-array line store
    └── mapped.py        Memory-mapped read-mostly line store
```
