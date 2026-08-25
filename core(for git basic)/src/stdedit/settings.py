"""Editor settings — persistent JSON-backed toggle store.

Settings are saved to ``~/.config/stdedit/settings.json`` so they survive
restarts.  If the file is missing or corrupt, sensible defaults are used.
Write failures (read-only filesystem, etc.) are silently ignored so the
editor always works — it just won't remember across sessions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULTS: dict[str, bool] = {
    "auto_save_idle": False,
    "auto_save_periodic": False,
    "auto_save_on_edit": False,
}

CONFIG_DIR = Path.home() / ".config" / "stdedit"
CONFIG_FILE = CONFIG_DIR / "settings.json"

LABELS: list[tuple[str, str]] = [
    ("auto_save_idle", "Auto-save: on idle (5s)"),
    ("auto_save_periodic", "Auto-save: every 30s"),
    ("auto_save_on_edit", "Auto-save: on every edit"),
]

_settings: dict[str, bool] = dict(_DEFAULTS)


def _load() -> None:
    """Load settings from disk, falling back to defaults."""
    global _settings
    _settings = dict(_DEFAULTS)
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in _DEFAULTS:
                if key in data:
                    _settings[key] = bool(data[key])
    except (OSError, json.JSONDecodeError, ValueError):
        pass


def _save() -> None:
    """Persist current settings to disk (best-effort)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(_settings, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def get(key: str) -> bool:
    return _settings.get(key, False)


def set(key: str, value: bool) -> None:
    _settings[key] = value
    _save()


def toggle(key: str) -> bool:
    _settings[key] = not _settings.get(key, False)
    _save()
    return _settings[key]


def any_auto_save() -> bool:
    return any(_settings.values())


# Load on import so the module is ready immediately.
_load()
