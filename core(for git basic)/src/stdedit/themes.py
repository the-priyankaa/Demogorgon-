"""Built-in color themes for stdedit.

Each theme maps semantic roles to ``(fg, bg)`` color indices.  Colors use
the xterm-256 palette where possible and are gracefully clamped to the 8
base curses colors on terminals that report fewer than 256 colors.

Roles:

- ``syntax``: the 10 token types from the language tokenizer.
- ``git``: git panel staged/unstaged/header pairs plus the 7 status
  letters (M/A/D/?/R/C/U).
- ``diff``: diff viewer add/del/hunk/header pairs.
"""

from __future__ import annotations

import curses

# Pair numbers must stay in sync with tui / git_panel / diff_viewer.
_PAIR_SYNTAX = {
    "keyword": 1,
    "string": 2,
    "comment": 3,
    "number": 4,
    "function": 5,
    "type": 6,
    "operator": 7,
    "tag": 8,
    "attribute": 9,
    "property": 10,
}

_PAIR_GIT = {
    "staged": 11,
    "unstaged": 12,
    "header": 13,
}

_PAIR_DIFF = {
    "add": 20,
    "del": 21,
    "hunk": 22,
    "header": 23,
}

_16_COLOR_MAP = {
    0: curses.COLOR_BLACK,
    1: curses.COLOR_RED,
    2: curses.COLOR_GREEN,
    3: curses.COLOR_YELLOW,
    4: curses.COLOR_BLUE,
    5: curses.COLOR_MAGENTA,
    6: curses.COLOR_CYAN,
    7: curses.COLOR_WHITE,
    8: curses.COLOR_BLACK,
    9: curses.COLOR_RED,
    10: curses.COLOR_GREEN,
    11: curses.COLOR_YELLOW,
    12: curses.COLOR_BLUE,
    13: curses.COLOR_MAGENTA,
    14: curses.COLOR_CYAN,
    15: curses.COLOR_WHITE,
}

# curses base colors encode RGB as bit flags: R=1, G=2, B=4.
_BASE_BY_RGB = {
    (0, 0, 0): curses.COLOR_BLACK,
    (1, 0, 0): curses.COLOR_RED,
    (0, 1, 0): curses.COLOR_GREEN,
    (1, 1, 0): curses.COLOR_YELLOW,
    (0, 0, 1): curses.COLOR_BLUE,
    (1, 0, 1): curses.COLOR_MAGENTA,
    (0, 1, 1): curses.COLOR_CYAN,
    (1, 1, 1): curses.COLOR_WHITE,
}


def _fold_color(color: int) -> int:
    """Fold an xterm-256 palette index onto the nearest base color."""
    if 0 <= color <= 15:
        return _16_COLOR_MAP[color]
    if 16 <= color <= 231:
        idx = color - 16
        r, g, b = idx // 36, (idx % 36) // 6, idx % 6
        bit = lambda c: 1 if c >= 3 else 0
        return _BASE_BY_RGB[(bit(r), bit(g), bit(b))]
    if 232 <= color <= 255:
        return curses.COLOR_WHITE if color >= 244 else curses.COLOR_BLACK
    return curses.COLOR_WHITE


def _resolve(fg: int, bg: int, colors: int | None = None) -> tuple[int, int]:
    """Map a (fg, bg) pair to what the running terminal can display.

    When fewer than 256 colors are available the xterm palette indices
    (16-255) are folded onto the nearest base color.  ``colors`` is
    normally read from ``curses.COLORS``; pass it explicitly in tests.
    """
    if colors is None:
        colors = getattr(curses, "COLORS", 256)
    if colors >= 256:
        return fg, bg
    if fg >= 0:
        fg = _fold_color(fg)
    if bg >= 0:
        bg = _fold_color(bg)
    return fg, bg


THEMES: dict[str, dict] = {
    "default": {
        "name": "default",
        "syntax": {
            "keyword": (5, -1),
            "string": (2, -1),
            "comment": (6, -1),
            "number": (3, -1),
            "function": (4, -1),
            "type": (3, -1),
            "operator": (1, -1),
            "tag": (5, -1),
            "attribute": (6, -1),
            "property": (4, -1),
        },
        "git": {
            "staged": (3, -1),
            "unstaged": (7, -1),
            "header": (6, -1),
            "M": (3, -1),
            "A": (2, -1),
            "D": (1, -1),
            "?": (7, -1),
            "R": (6, -1),
            "C": (6, -1),
            "U": (1, -1),
        },
        "diff": {
            "add": (2, -1),
            "del": (1, -1),
            "hunk": (6, -1),
            "header": (3, -1),
        },
    },
    "monokai": {
        "name": "Monokai",
        "syntax": {
            "keyword": (197, -1),
            "string": (148, -1),
            "comment": (244, -1),
            "number": (215, -1),
            "function": (221, -1),
            "type": (81, -1),
            "operator": (231, -1),
            "tag": (141, -1),
            "attribute": (80, -1),
            "property": (208, -1),
        },
        "git": {
            "staged": (148, -1),
            "unstaged": (231, -1),
            "header": (222, -1),
            "M": (221, -1),
            "A": (148, -1),
            "D": (197, -1),
            "?": (245, -1),
            "R": (81, -1),
            "C": (81, -1),
            "U": (197, -1),
        },
        "diff": {
            "add": (148, -1),
            "del": (197, -1),
            "hunk": (81, -1),
            "header": (221, -1),
        },
    },
    "dracula": {
        "name": "Dracula",
        "syntax": {
            "keyword": (141, -1),
            "string": (150, -1),
            "comment": (95, -1),
            "number": (215, -1),
            "function": (117, -1),
            "type": (215, -1),
            "operator": (249, -1),
            "tag": (212, -1),
            "attribute": (117, -1),
            "property": (229, -1),
        },
        "git": {
            "staged": (150, -1),
            "unstaged": (249, -1),
            "header": (117, -1),
            "M": (221, -1),
            "A": (150, -1),
            "D": (203, -1),
            "?": (245, -1),
            "R": (117, -1),
            "C": (117, -1),
            "U": (203, -1),
        },
        "diff": {
            "add": (150, -1),
            "del": (203, -1),
            "hunk": (117, -1),
            "header": (221, -1),
        },
    },
    "solarized_dark": {
        "name": "Solarized Dark",
        "syntax": {
            "keyword": (155, -1),
            "string": (142, -1),
            "comment": (60, -1),
            "number": (215, -1),
            "function": (33, -1),
            "type": (73, -1),
            "operator": (145, -1),
            "tag": (116, -1),
            "attribute": (66, -1),
            "property": (108, -1),
        },
        "git": {
            "staged": (108, -1),
            "unstaged": (145, -1),
            "header": (116, -1),
            "M": (215, -1),
            "A": (108, -1),
            "D": (161, -1),
            "?": (145, -1),
            "R": (116, -1),
            "C": (116, -1),
            "U": (161, -1),
        },
        "diff": {
            "add": (108, -1),
            "del": (161, -1),
            "hunk": (116, -1),
            "header": (215, -1),
        },
    },
    "solarized_light": {
        "name": "Solarized Light",
        "syntax": {
            "keyword": (155, -1),
            "string": (142, -1),
            "comment": (102, -1),
            "number": (130, -1),
            "function": (31, -1),
            "type": (37, -1),
            "operator": (60, -1),
            "tag": (61, -1),
            "attribute": (66, -1),
            "property": (96, -1),
        },
        "git": {
            "staged": (64, -1),
            "unstaged": (60, -1),
            "header": (31, -1),
            "M": (130, -1),
            "A": (64, -1),
            "D": (160, -1),
            "?": (60, -1),
            "R": (31, -1),
            "C": (31, -1),
            "U": (160, -1),
        },
        "diff": {
            "add": (64, -1),
            "del": (160, -1),
            "hunk": (31, -1),
            "header": (130, -1),
        },
    },
    "nord": {
        "name": "Nord",
        "syntax": {
            "keyword": (141, -1),
            "string": (108, -1),
            "comment": (102, -1),
            "number": (180, -1),
            "function": (110, -1),
            "type": (180, -1),
            "operator": (145, -1),
            "tag": (173, -1),
            "attribute": (111, -1),
            "property": (208, -1),
        },
        "git": {
            "staged": (108, -1),
            "unstaged": (145, -1),
            "header": (110, -1),
            "M": (180, -1),
            "A": (108, -1),
            "D": (167, -1),
            "?": (145, -1),
            "R": (110, -1),
            "C": (110, -1),
            "U": (167, -1),
        },
        "diff": {
            "add": (108, -1),
            "del": (167, -1),
            "hunk": (110, -1),
            "header": (180, -1),
        },
    },
    "one_dark": {
        "name": "One Dark",
        "syntax": {
            "keyword": (203, -1),
            "string": (149, -1),
            "comment": (243, -1),
            "number": (185, -1),
            "function": (68, -1),
            "type": (220, -1),
            "operator": (175, -1),
            "tag": (208, -1),
            "attribute": (110, -1),
            "property": (38, -1),
        },
        "git": {
            "staged": (149, -1),
            "unstaged": (252, -1),
            "header": (110, -1),
            "M": (215, -1),
            "A": (149, -1),
            "D": (203, -1),
            "?": (245, -1),
            "R": (110, -1),
            "C": (110, -1),
            "U": (203, -1),
        },
        "diff": {
            "add": (149, -1),
            "del": (203, -1),
            "hunk": (110, -1),
            "header": (215, -1),
        },
    },
}

# Guarantee a stable ordering for the settings panel.
THEME_ORDER = [
    "default",
    "monokai",
    "dracula",
    "solarized_dark",
    "solarized_light",
    "nord",
    "one_dark",
]

_MISSING_ROLES = []


def theme_names() -> list[str]:
    """Return theme display names in stable order."""
    return [THEMES[t]["name"] for t in THEME_ORDER]


def theme_keys() -> list[str]:
    """Return settings keys for each theme."""
    return [sanitize_theme_key(t) for t in THEME_ORDER]


def resolve_theme_id(display_or_key: str | None) -> str:
    """Map a theme display name or settings key to its internal id.

    Accepts ``"Monokai"`` (display), ``"monokai"`` (id), or
    ``"theme_monokai"`` (settings key).  Falls back to ``"default"``.
    """
    if not display_or_key:
        return "default"
    for tid in THEME_ORDER:
        key = sanitize_theme_key(tid)
        if (display_or_key == tid
                or display_or_key == THEMES[tid]["name"]
                or display_or_key == key):
            return tid
    return "default"


def sanitize_theme_key(name: str) -> str:
    """Convert a theme name to a valid settings key.

    ``"Solarized Dark"`` → ``"theme_solarized_dark"``
    """
    safe = name.lower().replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c == "_")
    return f"theme_{safe}"


def active_theme_name() -> str:
    """Return display name of the current theme (without importing isolated
    internals, reads straight from the settings radio state via callers)."""
    from . import settings
    return settings.get_active_theme_name() or "default"


def apply_theme(name: str = "default") -> None:
    """(Re)initialize every color pair from *name*'s palette."""
    if not curses.has_colors():
        return
    theme = THEMES[resolve_theme_id(name)]
    syntax = theme.get("syntax", {})
    git = theme.get("git", {})
    diff = theme.get("diff", {})

    for role, pair in _PAIR_SYNTAX.items():
        fg, bg = _resolve(*syntax.get(role, (curses.COLOR_WHITE, -1)))
        curses.init_pair(pair, fg, bg)
    for role, pair in _PAIR_GIT.items():
        fg, bg = _resolve(*git.get(role, (curses.COLOR_WHITE, -1)))
        curses.init_pair(pair, fg, bg)
    for role, pair in _PAIR_DIFF.items():
        fg, bg = _resolve(*diff.get(role, (curses.COLOR_WHITE, -1)))
        curses.init_pair(pair, fg, bg)


def syntax_color(theme_name: str, role: str) -> tuple[int, int]:
    """Return the raw (fg, bg) for a syntax role in a theme."""
    theme = THEMES[resolve_theme_id(theme_name)]
    return tuple(theme.get("syntax", {}).get(role, (curses.COLOR_WHITE, -1)))


def git_color(theme_name: str, role: str) -> int:
    """Return the raw fg index for a git status letter in a theme."""
    theme = THEMES[resolve_theme_id(theme_name)]
    color = theme.get("git", {}).get(role, (curses.COLOR_WHITE, -1))
    if isinstance(color, (tuple, list)):
        return color[0]
    return color


def validate_themes() -> list[str]:
    """Return a list of missing role names across all themes (empty = OK)."""
    missing = []
    required = set(_PAIR_SYNTAX) | set(_PAIR_GIT) | set(_PAIR_DIFF)
    for name in THEME_ORDER:
        theme = THEMES[name]
        roles = set(theme.get("syntax", {})) | set(theme.get("git", {})) | set(theme.get("diff", {}))
        for role in required - roles:
            missing.append(f"{name}:{role}")
    return missing