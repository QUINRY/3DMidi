"""KE music uses the audible X motor, with Y and Z held during the tune."""
import json
from pathlib import Path
import re
import statistics
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / "tools")]
import engine
from convert_poly_midi_u1 import plan
from motion_export import validate_generic


class KeXOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "mario.mid").read_bytes(), "Super Mario Theme.mid")

    def test_default_ke_music_is_fast_x_only_with_one_real_voice(self):
        result = engine.convert(self.song, {"printer": "creality_ender3_v3_ke"})
        self.assertEqual(result["settings"]["speed"], "fast")
        self.assertEqual(result["settings"]["voice"], "x_melody")
        self.assertTrue(all(len(f["pitches"]) == 1 for f in result["frames"]))
        self.assertEqual(result["transpose"], 9)
        self.assertAlmostEqual(result["duration"], self.song["duration"])
        for kind in ("full", "test"):
            text = result["downloads"][kind]["text"]
            music = text.split("; MELODY_BEGIN", 1)[1].split("; MELODY_END", 1)[0]
            moves = [line for line in music.splitlines() if line.startswith("G1 ")]
            self.assertTrue(moves)
            self.assertTrue(all(re.fullmatch(r"G1 X[-0-9.]+ F[0-9.]+", line) for line in moves))
            speeds = [float(line.split()[-1][1:]) / 60 for line in moves]
            self.assertGreater(statistics.median(speeds), 150)
            self.assertNotIn("Z_HOP", text)
            self.assertIn("G1 Z20.0000000 F180.000000", text)
            check = json.loads(result["downloads"]["report"]["text"])["validation"][kind]
            self.assertAlmostEqual(check["y_range_mm"][0], check["y_range_mm"][1])
            self.assertLessEqual(abs(check["total_timing_error_ms"]), 1)

    def test_y_word_inside_music_is_rejected_even_at_a_constant_coordinate(self):
        settings = {"printer": "creality_ender3_v3_ke", "speed": "fast"}
        prepared = engine.prepare(self.song, settings)
        result = engine.convert(self.song, settings)
        text = result["downloads"]["full"]["text"]
        before, rest = text.split("; MELODY_BEGIN", 1)
        rest = re.sub(r"(?m)^(G1 X[-0-9.]+) ", r"\1 Y110.0000000 ", rest, count=1)
        instructions, _ = plan(prepared["frames"], prepared["duration"], engine.PLANNER, prepared["profile"])
        with self.assertRaises(ValueError):
            validate_generic(before + "; MELODY_BEGIN" + rest, instructions, prepared["frames"],
                             prepared["duration"], prepared["profile"], prepared["printer"],
                             engine.PLANNER, startup_mode=prepared["startup"])


if __name__ == "__main__":
    unittest.main()
