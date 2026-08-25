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

# Keys in the same group are mutually exclusive (radio-button behaviour).
RADIO_GROUPS: dict[str, list[str]] = {
    "auto_save": ["auto_save_idle", "auto_save_periodic", "auto_save_on_edit"],
}

# Build reverse lookup: key -> group name
_KEY_TO_GROUP: dict[str, str] = {}
for _gname, _gkeys in RADIO_GROUPS.items():
    for _k in _gkeys:
        _KEY_TO_GROUP[_k] = _gname

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
    _enforce_radio_groups()


def _enforce_radio_groups() -> None:
    """If multiple keys in a radio group are ON, keep only the first."""
    for _gname, _gkeys in RADIO_GROUPS.items():
        active = [k for k in _gkeys if _settings.get(k)]
        if len(active) > 1:
            for k in active[1:]:
                _settings[k] = False


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


def toggle_radio(key: str) -> bool:
    """Toggle *key* as a radio button within its group.

    If *key* is in a :data:`RADIO_GROUP`:
      - If it is OFF, turn it ON and turn every other key in the group OFF.
      - If it is already ON, turn it OFF (no selection in the group).

    If *key* is not in any radio group, falls back to plain :func:`toggle`.
    """
    group_name = _KEY_TO_GROUP.get(key)
    if group_name is None:
        return toggle(key)

    group_keys = RADIO_GROUPS[group_name]
    was_on = _settings.get(key, False)

    # Turn everything in the group OFF.
    for k in group_keys:
        _settings[k] = False

    # If it was off, turn it on (if it was on, everything stays off).
    if not was_on:
        _settings[key] = True

    _save()
    return _settings[key]


def is_radio_key(key: str) -> bool:
    """Return True if *key* belongs to a radio group."""
    return key in _KEY_TO_GROUP


def any_auto_save() -> bool:
    return any(_settings[k] for k in RADIO_GROUPS.get("auto_save", []))


# Load on import so the module is ready immediately.
_load()
