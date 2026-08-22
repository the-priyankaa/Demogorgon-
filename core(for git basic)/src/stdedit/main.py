"""
main.py — CLI entry point. argparse only (stdlib), per STDLIB.md
substitution: click/typer -> argparse.

Phase 1 gate: `python -m stdedit.main somefile.py` opens the file into a
Buffer and hands it to the TUI. This alone proves open -> move -> edit ->
save -> exit end to end.
"""

from __future__ import annotations

import argparse
import sys

from .buffer import Buffer
from . import tui
from .extensions import discover, extension_dirs, load_requested_extensions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stdedit",
        description="A zero-dependency terminal text editor (stdlib only).",
    )
    parser.add_argument("file", nargs="?", default=None, help="File to open")
    parser.add_argument(
        "--tab-size", type=int, default=4, help="Tab width in spaces (default: 4)"
    )
    parser.add_argument(
        "--tabs",
        action="store_true",
        help="Use literal tab characters instead of spaces",
    )
    parser.add_argument(
        "--large-file-mb",
        type=int,
        default=8,
        help="Disable undo snapshots at this file size (default: 8 MB; 0 disables the safety mode)",
    )
    parser.add_argument(
        "--extension",
        action="append",
        default=[],
        metavar="NAME",
        help="Load one external extension by name (repeatable)",
    )
    parser.add_argument(
        "--extension-file",
        action="append",
        default=[],
        metavar="PATH",
        help="Load one external extension file (repeatable)",
    )
    parser.add_argument(
        "--all-extensions",
        action="store_true",
        help="Load every discovered extension (higher startup RSS)",
    )
    parser.add_argument(
        "--list-extensions",
        action="store_true",
        help="List discovered extension files and exit",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_extensions:
        dirs = extension_dirs()
        print("Extension directories:")
        for directory in dirs:
            print(f"  {directory}")
        print("Discovered extensions:")
        for path in discover():
            print(f"  {path}")
        return 0

    buf = Buffer(
        tab_size=args.tab_size,
        use_spaces=not args.tabs,
        large_file_threshold=max(0, args.large_file_mb) * 1024 * 1024,
    )
    if args.file:
        try:
            buf.load(args.file)
        except FileNotFoundError:
            # New file — that's fine, just remember the intended name.
            buf.filename = args.file

    # Extensions are opt-in so the bare editor stays lean.
    # --all-extensions keeps the old eager behavior for power users.
    if args.all_extensions:
        extension_names = None
        extension_files = None
    else:
        extension_names = args.extension
        extension_files = args.extension_file

    tui.run(
        buf,
        load_user_extensions=False,
        extension_names=extension_names,
        extension_files=extension_files,
        load_all_extensions=args.all_extensions,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
