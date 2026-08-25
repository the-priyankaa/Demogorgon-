import os
import tempfile
import unittest
from pathlib import Path

from stdedit.extensions import ExtensionAPI, discover, load_extensions


class _Editor:
    def __init__(self):
        self.value = 0


class TestExtensionAPI(unittest.TestCase):
    def test_command_key_event_status(self):
        editor = _Editor()
        api = ExtensionAPI(editor)
        api.extension("demo", "1.0", "test")
        api.add_command("inc", lambda e: setattr(e, "value", e.value + 1))
        api.bind_key("x", lambda e, k: setattr(e, "value", e.value + 10) or True)
        api.add_status(lambda e: f"v={e.value}")
        api.commands["inc"](editor)
        self.assertTrue(api.dispatch_key("x"))
        self.assertEqual(editor.value, 11)
        self.assertEqual(api.status(), "v=11")
        self.assertEqual(api.loaded[0].name, "demo")

    def test_loader_isolates_bad_extension(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "good.py").write_text("def setup(api):\n    api.extension('good')\n", encoding="utf-8")
            (root / "bad.py").write_text("def setup(api):\n    raise RuntimeError('boom')\n", encoding="utf-8")
            os.environ["STDEDIT_EXTENSIONS"] = d
            try:
                api = ExtensionAPI(_Editor())
                loaded, errors = load_extensions(api)
            finally:
                os.environ.pop("STDEDIT_EXTENSIONS", None)
            self.assertEqual(loaded, ["good"])
            self.assertEqual(len(errors), 1)
            self.assertEqual(api.loaded[0].name, "good")

class TestExternalExtensionDiscovery(unittest.TestCase):
    def test_requested_extension_loads_only_selected_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "one.py").write_text(
                "def setup(api):\n    api.extension('one')\n",
                encoding="utf-8",
            )
            (root / "two.py").write_text(
                "raise RuntimeError('two must not be imported')\n",
                encoding="utf-8",
            )
            os.environ["STDEDIT_EXTENSIONS"] = d
            try:
                api = ExtensionAPI(_Editor())
                loaded, errors = __import__("stdedit.extensions", fromlist=["load_requested_extensions"]).load_requested_extensions(api, ["one"], [])
            finally:
                os.environ.pop("STDEDIT_EXTENSIONS", None)
            self.assertEqual(loaded, ["one"])
            self.assertEqual(errors, [])
            self.assertEqual(api.loaded[0].name, "one")

    def test_direct_external_extension_file_loads(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "direct.py"
            path.write_text(
                "def setup(api):\n    api.extension('direct')\n",
                encoding="utf-8",
            )
            api = ExtensionAPI(_Editor())
            from stdedit.extensions import load_requested_extensions
            loaded, errors = load_requested_extensions(api, [], [str(path)])
            self.assertEqual(loaded, ["direct"])
            self.assertEqual(errors, [])

    def test_list_discovery_does_not_import_extension(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            marker = root / "imported.txt"
            (root / "probe.py").write_text(
                "from pathlib import Path\nPath(%r).write_text('yes')\ndef setup(api): pass\n" % str(marker),
                encoding="utf-8",
            )
            os.environ["STDEDIT_EXTENSIONS"] = d
            try:
                from stdedit.extensions import discover
                found = discover()
            finally:
                os.environ.pop("STDEDIT_EXTENSIONS", None)
            self.assertEqual([p.stem for p in found], ["probe"])
            self.assertFalse(marker.exists())
