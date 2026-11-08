"""Regression for the KE fast preset collapsing to the slow register."""
import json
import math
from pathlib import Path
import statistics
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / "tools")]
import engine
from convert_poly_midi_u1 import frame_vector
from convert_poly_midi_u1 import plan
from motion_export import validate_generic


class KeMusicRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "mario.mid").read_bytes(), "Super Mario Theme.mid")

    def test_speed_presets_keep_distinct_registers_and_preserve_melody_intervals(self):
        prepared = [engine.prepare(self.song, {"printer": "creality_ender3_v3_ke", "speed": speed})
                    for speed in ("slow", "medium", "fast")]
        self.assertEqual([p["transpose"] for p in prepared], [-13, -3, 9])
        medians = [statistics.median(math.hypot(*frame_vector(f["target_pitches"], p["profile"])[:2])
                                     for f in p["frames"]) for p in prepared]
        self.assertAlmostEqual(medians[1] / medians[0], 2 ** (10 / 12))
        self.assertAlmostEqual(medians[2] / medians[1], 2)
        for p in prepared:
            self.assertLessEqual(p["profile"].acceleration, p["printer"]["max_accel_mm_s2"])
            self.assertLessEqual(p["speed_range"][1], p["printer"]["max_velocity_mm_s"])
            self.assertAlmostEqual(p["duration"], self.song["duration"])
        self.assertEqual(len(prepared[-1]["frames"]), 393)

    def test_fast_export_reaches_notes_and_restores_limits_in_both_startup_modes(self):
        for startup in ("ke_auto_home_slow_z", "prepared_no_z"):
            with self.subTest(startup=startup):
                result = engine.convert(self.song, {"printer": "creality_ender3_v3_ke", "speed": "fast",
                                                    "tempo": "medium", "startup": startup})
                self.assertEqual(result["transpose"], 9)
                self.assertGreater(result["speed_range"][1], 290)
                report = json.loads(result["downloads"]["report"]["text"])
                for kind in ("full", "test"):
                    text = result["downloads"][kind]["text"]
                    before, rest = text.split("; MELODY_BEGIN", 1)
                    music, after = rest.split("; MELODY_END", 1)
                    self.assertIn("M204 S8000.000000\nSET_VELOCITY_LIMIT ACCEL_TO_DECEL=8000", before)
                    self.assertNotIn("VELOCITY=3 ", text)
                    self.assertIn("VELOCITY=500 ACCEL=8000 ACCEL_TO_DECEL=2500", after)
                    self.assertFalse(any(any(w.startswith(("Y", "Z")) for w in line.split()[1:])
                                         for line in music.splitlines() if line and not line.startswith(";")))
                    validation = report["validation"][kind]
                    self.assertLessEqual(abs(validation["total_timing_error_ms"]), 1)
                    self.assertLessEqual(validation["max_cadence_model_error_cents"], .01)

    def test_music_dynamics_cannot_be_omitted_increased_or_applied_to_z(self):
        settings = {"printer": "creality_ender3_v3_ke", "speed": "fast", "tempo": "medium"}
        prepared = engine.prepare(self.song, settings)
        result = engine.convert(self.song, settings)
        text = result["downloads"]["full"]["text"]
        instructions, _ = plan(prepared["frames"], prepared["duration"], engine.PLANNER, prepared["profile"])
        setup = "SET_VELOCITY_LIMIT ACCEL_TO_DECEL=8000\n"
        altered = [text.replace(setup, "", 1),
                   text.replace(setup, "SET_VELOCITY_LIMIT ACCEL_TO_DECEL=9000\n", 1),
                   text.replace(setup, "", 1).replace("M204 S100\nG1 Z20", setup + "M204 S8000\nG1 Z20", 1)]
        for value in altered:
            with self.assertRaises(ValueError):
                validate_generic(value, instructions, prepared["frames"], prepared["duration"],
                                 prepared["profile"], prepared["printer"], engine.PLANNER,
                                 startup_mode=prepared["startup"])


if __name__ == "__main__":
    unittest.main()
