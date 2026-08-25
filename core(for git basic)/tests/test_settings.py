"""Tests for stdedit.settings — persistence, defaults, and toggle behaviour."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import stdedit.settings as settings


class TestDefaults(unittest.TestCase):
    """Verify the module provides sane defaults when no config file exists."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_all_auto_save_off_by_default(self):
        with mock.patch.object(settings, "CONFIG_FILE", Path("/nonexistent")):
            settings._load()
            self.assertFalse(settings.get("auto_save_idle"))
            self.assertFalse(settings.get("auto_save_periodic"))
            self.assertFalse(settings.get("auto_save_on_edit"))

    def test_any_auto_save_false_by_default(self):
        with mock.patch.object(settings, "CONFIG_FILE", Path("/nonexistent")):
            settings._load()
            self.assertFalse(settings.any_auto_save())

    def test_unknown_key_returns_false(self):
        self.assertFalse(settings.get("no_such_key"))


class TestRoundTrip(unittest.TestCase):
    """Toggle, persist, re-load — verify the value survives."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._file = self._dir / "settings.json"
        self._patch_config = mock.patch.object(
            settings, "CONFIG_DIR", self._dir
        )
        self._patch_file = mock.patch.object(
            settings, "CONFIG_FILE", self._file
        )
        self._patch_config.start()
        self._patch_file.start()

    def tearDown(self):
        self._patch_file.stop()
        self._patch_config.stop()
        self._tmp.cleanup()

    def test_toggle_persists_and_reloads(self):
        settings._load()
        self.assertFalse(settings.get("auto_save_idle"))
        settings.toggle("auto_save_idle")
        self.assertTrue(settings.get("auto_save_idle"))
        # Re-load from disk
        settings._load()
        self.assertTrue(settings.get("auto_save_idle"))

    def test_set_persists(self):
        settings._load()
        settings.set("auto_save_periodic", True)
        self.assertTrue(self._file.exists())
        settings._load()
        self.assertTrue(settings.get("auto_save_periodic"))

    def test_toggle_back_to_false(self):
        settings._load()
        settings.toggle("auto_save_on_edit")   # True
        settings.toggle("auto_save_on_edit")   # False
        settings._load()
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_json_file_is_valid(self):
        settings._load()
        settings.toggle("auto_save_idle")
        data = json.loads(self._file.read_text())
        self.assertIsInstance(data, dict)
        self.assertIn("auto_save_idle", data)

    def test_unrelated_keys_ignored_on_load(self):
        self._file.write_text('{"auto_save_idle": true, "junk": 42}\n')
        settings._load()
        self.assertTrue(settings.get("auto_save_idle"))
        # junk should not cause an error


class TestCorruptFile(unittest.TestCase):
    """Corrupt or unreadable config files should not crash the editor."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._file = self._dir / "settings.json"
        self._patch_config = mock.patch.object(
            settings, "CONFIG_DIR", self._dir
        )
        self._patch_file = mock.patch.object(
            settings, "CONFIG_FILE", self._file
        )
        self._patch_config.start()
        self._patch_file.start()

    def tearDown(self):
        self._patch_file.stop()
        self._patch_config.stop()
        self._tmp.cleanup()

    def test_corrupt_json_uses_defaults(self):
        self._file.write_text("{bad json!!!")
        settings._load()
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_non_dict_json_uses_defaults(self):
        self._file.write_text('[1, 2, 3]')
        settings._load()
        self.assertFalse(settings.get("auto_save_idle"))

    def test_missing_file_uses_defaults(self):
        # No file written
        settings._load()
        self.assertFalse(settings.get("auto_save_idle"))


class TestWriteFailure(unittest.TestCase):
    """Write errors should be silently ignored (read-only fs, etc.)."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_toggle_succeeds_even_if_write_fails(self):
        with mock.patch("pathlib.Path.mkdir", side_effect=OSError):
            result = settings.toggle("auto_save_idle")
            self.assertTrue(result)
            self.assertTrue(settings.get("auto_save_idle"))

    def test_set_succeeds_even_if_write_fails(self):
        with mock.patch("pathlib.Path.mkdir", side_effect=OSError):
            settings.set("auto_save_idle", True)
            self.assertTrue(settings.get("auto_save_idle"))


class TestLabels(unittest.TestCase):
    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_labels_match_defaults(self):
        keys = {k for k, _ in settings.LABELS}
        self.assertEqual(keys, set(settings._DEFAULTS.keys()))


class TestRadioGroup(unittest.TestCase):
    """toggle_radio: mutual exclusion within radio groups."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_toggle_radio_turns_on_and_clears_others(self):
        settings.toggle_radio("auto_save_idle")
        self.assertTrue(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_already_active_turns_off(self):
        settings.toggle_radio("auto_save_idle")   # ON
        settings.toggle_radio("auto_save_idle")   # OFF
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_cross_activation(self):
        settings.toggle_radio("auto_save_idle")    # idle ON
        settings.toggle_radio("auto_save_periodic")  # periodic ON, idle OFF
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertTrue(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_non_radio_key_uses_plain_toggle(self):
        settings.toggle_radio("no_such_key")
        self.assertTrue(settings.get("no_such_key"))

    def test_is_radio_key(self):
        self.assertTrue(settings.is_radio_key("auto_save_idle"))
        self.assertTrue(settings.is_radio_key("auto_save_periodic"))
        self.assertTrue(settings.is_radio_key("auto_save_on_edit"))
        self.assertFalse(settings.is_radio_key("no_such_key"))

    def test_enforce_on_load_fixes_legacy_multi(self):
        """Legacy config with multiple ON → load keeps only the first."""
        settings._settings["auto_save_idle"] = True
        settings._settings["auto_save_periodic"] = True
        settings._settings["auto_save_on_edit"] = True
        settings._enforce_radio_groups()
        self.assertTrue(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_persists_and_reloads(self):
        settings.toggle_radio("auto_save_on_edit")
        settings._save()
        settings._load()
        self.assertTrue(settings.get("auto_save_on_edit"))
        self.assertFalse(settings.get("auto_save_idle"))

    def test_any_auto_save_only_checks_radio_group(self):
        settings.toggle_radio("auto_save_periodic")
        self.assertTrue(settings.any_auto_save())
        settings.toggle_radio("auto_save_periodic")  # OFF
        self.assertFalse(settings.any_auto_save())


if __name__ == "__main__":
    unittest.main()
