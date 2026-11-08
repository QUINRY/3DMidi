"""The FOC lock remains for profiles without the user's K2 series exception."""
import itertools
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
from printers import _derive, get_profile, public_profiles


FOC_MODELS = ("creality_hi",)


class FocMusicLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "mario.mid").read_bytes(), "Mario.mid")

    def test_all_requested_speed_and_tempo_pairs_use_slow_slow(self):
        for model in FOC_MODELS:
            for speed, tempo in itertools.product(("slow", "medium", "fast"), repeat=2):
                with self.subTest(model=model, speed=speed, tempo=tempo):
                    prepared = engine.prepare(self.song, {"printer": model, "speed": speed, "tempo": tempo})
                    self.assertEqual((prepared["settings"]["speed"], prepared["settings"]["tempo"]), ("slow", "slow"))
                    self.assertEqual(prepared["profile"].tempo_ratio, .75)

    def test_rule_follows_motor_capability_for_future_models_but_not_extruder_only(self):
        for axes in (["x", "y"], ["x"], ["extruder"]):
            profile = get_profile("creality_k1_40")
            profile.update(id="future_foc_model", motor_control={"type": "foc_step_servo", "axes": axes})
            profile = _derive(profile)
            with patch.object(engine, "get_profile", return_value=profile):
                p = engine.prepare(self.song, {"printer": profile["id"], "speed": "fast", "tempo": "fast"})
            expected = "fast" if axes == ["extruder"] else "slow"
            self.assertEqual((p["settings"]["speed"], p["settings"]["tempo"]), (expected, expected))

    def test_export_preview_filenames_bpm_and_actual_motion_use_locked_settings(self):
        for model in FOC_MODELS:
            with self.subTest(model=model):
                result = engine.convert(self.song, {"printer": model, "speed": "fast", "tempo": "fast"})
                expected = engine.convert(self.song, {"printer": model, "speed": "slow", "tempo": "slow"})
                self.assertEqual(result["settings"], expected["settings"])
                self.assertEqual(result["output_bpm"], round(self.song["bpm"] * .75, 1))
                report = json.loads(result["downloads"]["report"]["text"])
                for kind in ("full", "test"):
                    actual = result["downloads"][kind]
                    self.assertTrue(actual["name"].endswith("_Yavas_Yavas" + ("_test" if kind == "test" else "") + ".gcode"))
                    self.assertEqual(actual["text"], expected["downloads"][kind]["text"])
                    checked = report["validation"][kind]
                    self.assertLessEqual(checked["xy_speed_range_mm_s"][1], 100)
                    self.assertLessEqual(abs(checked["total_timing_error_ms"]), 1)
                    self.assertEqual(checked["z_isolation"]["explicit_z_moves"], 0)

    def test_capability_metadata_is_public_and_unavailable_models_stay_unavailable(self):
        profiles = {p["id"]: p for p in public_profiles()}
        for model in (*FOC_MODELS, "qidi_max4"):
            self.assertEqual(profiles[model]["music_settings_lock"]["speed"], "slow")
            self.assertTrue(profiles[model]["motor_control"]["source_urls"])
        self.assertFalse(profiles["qidi_max4"]["selectable"])
        self.assertNotIn("music_settings_lock", profiles["snapmaker_u1"])
        self.assertNotIn("music_settings_lock", profiles["creality_ender3_v3_ke"])


if __name__ == "__main__":
    unittest.main()
