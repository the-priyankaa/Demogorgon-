# Demogorgon-

A **zero-runtime-dependency terminal text editor** — every line is Python
standard library (`.zero-dep.toml` is the pledge). Built for [hackathon]
Track A.

## Repository layout

```
core(for git basic)/        # the editor package ("stdedit"): src, tests, packaging
IMPLEMENTATION_PROGRESS.md  # feature log + keybinding reference
```

## Highlights

- **nano/micro-style editing**: open/save, cursor & scrolling, undo/redo,
  selection/copy/cut/paste, auto-indent, tabs↔spaces, bracket
  matching/auto-close, bracketed paste.
- **File explorer sidebar** (Ctrl-E): project tree rooted at the opened
  file's parent, `<..>` navigation, create files/folders (**n**/**N**),
  dotfile toggle (**h**), IDE/build artifacts hidden automatically.
- **System integration**: pick a project root via zenity/kdialog (**O**),
  reveal it in your desktop file manager (**R**).
- **Status bar**: filename + dirty marker, human-readable language label,
  cursor position, scroll percentage.
- **Regex syntax highlighting** driven by a small token-rule schema;
  several languages ship out of the box.
- **Large files**: compact bytearray storage, memory-mapped read-mostly
  mode, and undo history bounded by count *and* memory budget.
- **Extension API**: optional Python plugins (commands, keybindings,
  lifecycle hooks, status-bar text) loaded from well-known directories;
  broken plugins can't crash the editor.

## Install

`carl` sets everything up on a machine in one shot — venv, editable
install, and global launchers (`stdedit`, `yuki`, `carl`) in
`~/.local/bin`:

```bash
cd "core(for git basic)"
make install       # or: PYTHONPATH=src python3 -m stdedit.install install
carl status        # inspect what was installed where
```

Rerunning is safe: it repairs links and picks up code changes.
Uninstall with `make uninstall` (`--purge` also deletes `.venv`).

## Quick start

```bash
stdedit path/to/file.py         # edit a file (tree roots at its folder)
stdedit path/to/project         # open a whole project
stdedit --project ~/myapp x.py  # explicit root + file together
```

Without installing, run straight from the source folder:

```bash
make run FILE=path/to/file.py
```

## Development

```bash
make test    # full unit suite
make proof   # prove no site-packages imports (zero-dependency check)
```

More documentation: [`core(for git basic)/README.md`](./core(for git basic)/README.md),
[`IMPLEMENTATION_PROGRESS.md`](./IMPLEMENTATION_PROGRESS.md),
[`core(for git basic)/STDLIB.md`](./core(for git basic)/STDLIB.md).
