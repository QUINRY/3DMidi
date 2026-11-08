"""User-observed directional bands must constrain actual G-code, not just labels."""
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "tools")]
import engine
from foc_acoustic import make_y_scan, validate_y_scan
from printers import get_profile
from convert_poly_midi_u1 import plan
from motion_export import render_generic, validate_generic


class FocAcousticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "library/popular/popular_faithless_insomnia.mid").read_bytes(), "Insomnia.mid")

    def settings(self, **kwargs):
        return {"printer": "creality_k2_pro", "sound_mode": "foc_band", "speed": "medium", "tempo": "medium",
                "foc_x_min": 12, "foc_x_max": 16, "foc_y_min": .25, "foc_y_max": .5, **kwargs}

    def test_old_y_control_normalizes_to_observed_x_band_without_pitch_claims(self):
        legacy = engine.prepare(self.song, {"printer": "creality_k2_pro", "speed": "slow", "tempo": "medium"})
        self.assertEqual(legacy["axis_speed_ranges"]["y"], [0, 0])
        result = engine.convert(self.song, self.settings(foc_axis="y"))
        self.assertEqual(result["settings"]["foc_axis"], "x")
        self.assertEqual(result["axis_speed_ranges"]["x"], [12, 16])
        self.assertEqual(result["axis_speed_ranges"]["y"], [0, 0])
        report = json.loads(result["downloads"]["report"]["text"])
        for kind in ("full", "test"):
            check = report["validation"][kind]
            self.assertEqual(check["music_axes"], "x")
            self.assertEqual(check["y_speed_range_mm_s"], [0, 0])
            self.assertGreaterEqual(check["x_speed_range_mm_s"][0], 12 - 1e-7)
            self.assertLessEqual(check["x_speed_range_mm_s"][1], 16 + 1e-7)
            self.assertIsNone(check["max_cadence_model_error_cents"])
            self.assertFalse(check["audible_pitch_calibrated"])
            self.assertEqual(check["z_isolation"]["explicit_z_moves"], 0)
            self.assertLessEqual(abs(check["total_timing_error_ms"]), 1)
            text = result["downloads"][kind]["text"]
            self.assertEqual(text.splitlines().count("G28 X Y"), 1)
            self.assertNotIn("Z_HOP", text)
            self.assertNotIn("motor cadences are preserved", text)

    def test_editable_x_band_and_all_speeds_keep_the_selected_tempo(self):
        for speed in ("slow", "medium", "fast"):
            result = engine.convert(self.song, self.settings(speed=speed, tempo="fast", foc_x_min=10, foc_x_max=15,
                                                             foc_y_min=.1, foc_y_max=.3))
            self.assertEqual(result["output_bpm"], round(result["bpm"] * 1.25, 1))
            self.assertEqual((result["settings"]["speed"], result["settings"]["tempo"]), (speed, "fast"))
            report = json.loads(result["downloads"]["report"]["text"])
            for check in report["validation"].values():
                self.assertGreater(check["x_speed_range_mm_s"][1], 0)
                self.assertEqual(check["y_speed_range_mm_s"], [0, 0])
                self.assertLessEqual(check["x_speed_range_mm_s"][1], 15 + 1e-6)
                self.assertLessEqual(check["y_speed_range_mm_s"][1], .3 + 1e-6)
                self.assertLessEqual(abs(check["total_timing_error_ms"]), 1)

    def test_unsafe_ranges_and_unsupported_printers_are_rejected(self):
        for changes in ({"foc_x_min": 0}, {"foc_x_min": 18}, {"foc_x_max": float("inf")},
                        {"foc_x_max": 101}, {"foc_x_min": []}, {"printer": "snapmaker_u1"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                engine.prepare(self.song, self.settings(**changes))

    def test_matching_plan_and_emitted_feed_cannot_bypass_the_frame_band(self):
        p = engine.prepare(self.song, self.settings(foc_axis="y"))
        instructions, _ = plan(p["frames"], p["duration"], engine.PLANNER, p["profile"])
        instructions = [dict(i) for i in instructions]
        first = next(i for i in instructions if i["kind"] == "move")
        first["speed"] = 2
        text = render_generic("Insomnia.mid", p["frames"], instructions, p["duration"], p["profile"], p["printer"], 0,
                              startup_mode=p["startup"])
        with self.assertRaises(ValueError):
            validate_generic(text, instructions, p["frames"], p["duration"], p["profile"], p["printer"], engine.PLANNER,
                             startup_mode=p["startup"])

    def test_all_models_ignore_old_y_and_alternating_settings_in_music(self):
        for model in ("creality_k2", "creality_k2_pro", "creality_k2_plus"):
            reference = engine.convert(self.song, self.settings(printer=model, foc_axis="x"))
            for axis in ("y", "alternate"):
                result = engine.convert(self.song, self.settings(printer=model, foc_axis=axis,
                                                                 foc_y_min=-1, foc_y_max=[]))
                for kind in ("full", "test"):
                    self.assertEqual(result["downloads"][kind]["text"], reference["downloads"][kind]["text"])
                    music = result["downloads"][kind]["text"].split("; MELODY_BEGIN")[1].split("; MELODY_END")[0]
                    for move in (line for line in music.splitlines() if line.startswith("G1 ")):
                        self.assertEqual({word[0] for word in move.split()[1:]}, {"X", "F"})

    def test_unused_y_reference_does_not_limit_a_low_x_band(self):
        result = engine.convert(self.song, self.settings(foc_x_min=.05, foc_x_max=.1))
        self.assertEqual(result["axis_speed_ranges"]["x"], [.05, .1])
        self.assertEqual(result["axis_speed_ranges"]["y"], [0, 0])

    def test_listening_scan_is_bounded_labelled_and_rejects_unsafe_changes(self):
        for model in ("creality_k2", "creality_k2_pro", "creality_k2_plus"):
            printer = get_profile(model)
            scan = make_y_scan(printer, engine.PLANNER)
            self.assertEqual(scan["validation"]["stages"], 11)
            self.assertEqual(scan["validation"]["moves"], 22)
            self.assertAlmostEqual(scan["validation"]["duration_s"], 48, places=6)
            self.assertEqual(scan["validation"]["explicit_z_moves"], 0)
            for bad in (scan["text"].replace("F7.5000000", "F6000"),
                        scan["text"].replace("F1800", "F99999", 1),
                        scan["text"].replace("MOVE=0", "MOVE=1"),
                        scan["text"].replace("M204 S600", "G28 X Y\nM204 S600")):
                with self.assertRaises(ValueError):
                    validate_y_scan(bad, scan["stages"], printer, engine.PLANNER)


if __name__ == "__main__":
    unittest.main()
