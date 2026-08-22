"""Small zero-dependency extension API for stdedit.

Extensions are optional Python modules. A module may expose ``setup(api)`` or
``register(api)``. The API intentionally exposes only stable, useful hooks:
commands, key handlers, lifecycle callbacks, and status providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Any

Command = Callable[[Any], Optional[str]]
KeyHandler = Callable[[Any, Any], bool]
Callback = Callable[[Any], None]
StatusProvider = Callable[[Any], str]


@dataclass
class Extension:
    name: str
    version: str = "0.1"
    description: str = ""


class ExtensionAPI:
    def __init__(self, editor: Any):
        self.editor = editor
        self.commands: Dict[str, Command] = {}
        self.key_handlers: Dict[Any, List[KeyHandler]] = {}
        self.on_startup: List[Callback] = []
        self.on_shutdown: List[Callback] = []
        self.status_providers: List[StatusProvider] = []
        self.loaded: List[Extension] = []

    def add_command(self, name: str, callback: Command) -> None:
        if not name or not callable(callback):
            raise ValueError("command name and callback are required")
        self.commands[name] = callback

    register_command = add_command

    def bind_key(self, key: Any, callback: KeyHandler) -> None:
        if not callable(callback):
            raise ValueError("key callback must be callable")
        self.key_handlers.setdefault(key, []).append(callback)

    register_key = bind_key

    def on(self, event: str, callback: Callback) -> None:
        if event == "startup":
            self.on_startup.append(callback)
        elif event == "shutdown":
            self.on_shutdown.append(callback)
        else:
            raise ValueError(f"unsupported event: {event}")

    def add_status(self, callback: StatusProvider) -> None:
        self.status_providers.append(callback)

    register_status = add_status

    def extension(self, name: str, version: str = "0.1", description: str = "") -> Extension:
        ext = Extension(name, version, description)
        self.loaded.append(ext)
        return ext

    def execute(self, name: str) -> Optional[str]:
        callback = self.commands.get(name)
        if callback is None:
            return None
        return callback(self.editor)

    def dispatch_key(self, key: Any) -> bool:
        handled = False
        for callback in self.key_handlers.get(key, ()):
            handled = bool(callback(self.editor, key)) or handled
        return handled

    def startup(self) -> None:
        for callback in self.on_startup:
            callback(self.editor)

    def shutdown(self) -> None:
        for callback in reversed(self.on_shutdown):
            callback(self.editor)

    def status(self) -> str:
        parts = []
        for callback in self.status_providers:
            value = callback(self.editor)
            if value:
                parts.append(value)
        return "  ".join(parts)
