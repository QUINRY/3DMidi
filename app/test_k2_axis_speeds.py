"""K2 music uses X only, with editable speed/tempo and native XY homing."""
import itertools
import json
import re
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / "tools")]
import engine
from convert_poly_midi_u1 import plan
from motion_export import render_generic, validate_generic
from printers import get_profile


K2_MODELS = ("creality_k2", "creality_k2_pro", "creality_k2_plus")


class K2AxisSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "mario.mid").read_bytes(), "Mario.mid")

    def test_speed_and_tempo_are_unlocked(self):
        for model in K2_MODELS:
            with self.subTest(model=model):
                self.assertNotIn("music_settings_lock", get_profile(model))
                self.assertEqual(get_profile(model)["music_axes"], "x")
                for speed, tempo in itertools.product(("slow", "medium", "fast"), repeat=2):
                    p = engine.prepare(self.song, {"printer": model, "speed": speed, "tempo": tempo})
                    self.assertEqual((p["settings"]["speed"], p["settings"]["tempo"]), (speed, tempo))
                default = engine.prepare(self.song, {"printer": model})
                self.assertEqual((default["settings"]["speed"], default["settings"]["tempo"]), ("slow", "slow"))

    def test_every_emitted_music_move_uses_x_only_with_correct_note_timing(self):
        for model in K2_MODELS:
            for speed, tempo in (("slow", "slow"), ("fast", "medium")):
                with self.subTest(model=model, speed=speed, tempo=tempo):
                    result = engine.convert(self.song, {"printer": model, "speed": speed, "tempo": tempo})
                    report = json.loads(result["downloads"]["report"]["text"])
                    for kind in ("full", "test"):
                        output = result["downloads"][kind]["text"]
                        before, rest = output.split("; MELODY_BEGIN", 1)
                        music, after = rest.split("; MELODY_END", 1)
                        x_speeds = []
                        for line in music.splitlines():
                            if not line.startswith("G1 "):
                                continue
                            self.assertRegex(line, r"^G1 X[-0-9.]+ F[0-9.]+$")
                            values = {word[0]: float(word[1:]) for word in line.split()[1:]}
                            x_speeds.append(values["F"] / 60)
                        checked = report["validation"][kind]
                        self.assertEqual(checked["music_axes"], "x")
                        self.assertEqual(checked["music_voice_count"], 1)
                        self.assertEqual(checked["y_speed_range_mm_s"], [0, 0])
                        self.assertEqual(checked["y_range_mm"], [result["printer"]["start_xy"][1]] * 2)
                        for actual, expected in zip((min(x_speeds), max(x_speeds)), checked["x_speed_range_mm_s"]):
                            self.assertAlmostEqual(actual, expected, places=5)
                        self.assertLessEqual(checked["max_cadence_model_error_cents"], .01)
                        self.assertLessEqual(abs(checked["total_timing_error_ms"]), 1)
                        self.assertNotIn("Z_HOP", output)
                        self.assertEqual(before.splitlines().count("G28 X Y"), 1)
                        self.assertIn("M204 S300", before)
                        self.assertIn("M204 S300", after)

    def test_validator_rejects_y_in_music_even_with_a_matching_changed_plan(self):
        p = engine.prepare(self.song, {"printer": "creality_k2_pro"})
        instructions, _ = plan(p["frames"], p["duration"], engine.PLANNER, p["profile"])
        transposed = []
        for move in instructions:
            if move["kind"] == "move":
                move = {**move, "x": move["y"], "y": move["x"]}
            transposed.append(move)
        text = render_generic(self.song["filename"], p["frames"], transposed, p["duration"],
                              p["profile"], p["printer"], p["transpose"], startup_mode=p["startup"])
        with self.assertRaisesRegex(ValueError, "trajectory"):
            validate_generic(text, transposed, p["frames"], p["duration"], p["profile"],
                             p["printer"], engine.PLANNER, startup_mode=p["startup"])

    def test_old_voice_selections_normalize_to_one_x_melody(self):
        for voice in ("duet", "melody", "x_melody"):
            p = engine.prepare(self.song, {"printer": "creality_k2_pro", "voice": voice})
            self.assertEqual(p["settings"]["voice"], "x_melody")
            self.assertTrue(all(len(frame["target_pitches"]) == 1 for frame in p["frames"]))

    def test_constant_y_word_is_also_forbidden_in_the_music_block(self):
        p = engine.prepare(self.song, {"printer": "creality_k2_pro"})
        instructions, _ = plan(p["frames"], p["duration"], engine.PLANNER, p["profile"])
        text = render_generic(self.song["filename"], p["frames"], instructions, p["duration"],
                              p["profile"], p["printer"], 0, startup_mode=p["startup"])
        before, body = text.split("; MELODY_BEGIN", 1)
        body = re.sub(r"(?m)^(G1 X[-0-9.]+) ", r"\1 Y150.0000000 ", body, count=1)
        with self.assertRaises(ValueError):
            validate_generic(before + "; MELODY_BEGIN" + body, instructions, p["frames"], p["duration"],
                             p["profile"], p["printer"], engine.PLANNER, startup_mode=p["startup"])


if __name__ == "__main__":
    unittest.main()
