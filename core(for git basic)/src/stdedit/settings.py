"""Editor settings — simple in-memory toggle store."""

from __future__ import annotations

_settings: dict[str, bool] = {
    "auto_save_idle": False,
    "auto_save_periodic": False,
    "auto_save_on_edit": False,
}

LABELS: list[tuple[str, str]] = [
    ("auto_save_idle", "Auto-save: on idle (5s)"),
    ("auto_save_periodic", "Auto-save: every 30s"),
    ("auto_save_on_edit", "Auto-save: on every edit"),
]


def get(key: str) -> bool:
    return _settings.get(key, False)


def set(key: str, value: bool) -> None:
    _settings[key] = value


def toggle(key: str) -> bool:
    _settings[key] = not _settings.get(key, False)
    return _settings[key]


def any_auto_save() -> bool:
    return any(_settings.values())
