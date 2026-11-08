"""Persistence and locale contracts independent of UI rendering."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]
from desktop import preferences


class PreferencesTests(unittest.TestCase):
    def test_default_and_saved_language_survive_a_new_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "3DMidi/preferences.json"
            with patch.object(preferences, "preferences_path", return_value=path):
                self.assertEqual(preferences.get_preferences(), {"language": "en"})
                preferences.set_preferences({"language": "tr", "untrusted": "ignored"})
                self.assertEqual(json.loads(path.read_text()), {"language": "tr"})
                self.assertEqual(preferences.get_preferences(), {"language": "tr"})
                self.assertFalse(path.with_suffix(".tmp").exists())
                for invalid in ({"language": "unknown"}, {"language": []}, None):
                    with self.assertRaises(ValueError):
                        preferences.set_preferences(invalid)
                self.assertEqual(preferences.get_preferences()["language"], "tr")

    def test_corrupt_preferences_fall_back_to_english(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            with patch.object(preferences, "preferences_path", return_value=path):
                for broken in ("not-json", "[]", '{"language": []}', '{"language": "xx"}'):
                    path.write_text(broken)
                    self.assertEqual(preferences.get_preferences(), {"language": "en"})

    def test_core_catalog_has_ten_languages_and_preserves_placeholders(self):
        catalog = json.loads((ROOT / "app/static/locales.json").read_text(encoding="utf-8"))
        self.assertEqual(set(catalog["languages"]), preferences.LANGUAGES)
        for key in ("Settings", "Language", "Generate G-code", "Save full G-code", "File saved: {name}",
                    "Turn notes into printer music.", "Before starting, clear the bed, let the printer cool and leave at least 20 mm between nozzle and bed. This file does not create that clearance."):
            self.assertEqual(set(catalog["messages"][key]), preferences.LANGUAGES)
        for key, variants in catalog["messages"].items():
            placeholders = set(re.findall(r"\{(\w+)\}", key))
            for language, message in variants.items():
                self.assertTrue(message.strip(), (key, language))
                self.assertEqual(set(re.findall(r"\{(\w+)\}", message)), placeholders, (key, language))

    def test_native_save_filters_parse_in_every_language(self):
        from webview.util import parse_file_type
        for language in preferences.LANGUAGES:
            for label, extension in (("Gcode files", "gcode"), ("JSON report", "json")):
                value = preferences.text(label, language) + f" (*.{extension})"
                self.assertEqual(parse_file_type(value)[1], f"*.{extension}")


if __name__ == "__main__":
    unittest.main()
