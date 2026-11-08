"""The U1 fast preset must produce faster notes, with the selected MIDI timing."""
import json
import math
from pathlib import Path
import statistics
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
from convert_poly_midi_u1 import frame_vector


class U1MusicSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "mario.mid").read_bytes(), "Super Mario Theme.mid")

    def test_fast_really_moves_faster_than_medium(self):
        prepared = [engine.prepare(self.song, {"printer": "snapmaker_u1", "speed": speed, "tempo": "medium"})
                    for speed in ("medium", "fast")]
        medians = [statistics.median(math.hypot(*frame_vector(f["target_pitches"], p["profile"])[:2])
                                     for f in p["frames"]) for p in prepared]
        self.assertGreater(medians[1] / medians[0], 1.8, f"Medium/fast actual speeds: {medians}")

    def test_tempo_follows_speed_by_default_and_explicit_tempo_is_respected(self):
        for speed in ("slow", "medium", "fast"):
            with self.subTest(speed=speed):
                p = engine.prepare(self.song, {"printer": "snapmaker_u1", "speed": speed})
                self.assertEqual(p["settings"]["tempo"], speed)
                ratio = engine.TEMPOS[speed]["ratio"]
                self.assertAlmostEqual(p["duration"] * ratio, self.song["duration"])
                self.assertEqual(engine.summary(self.song, p)["output_bpm"], round(self.song["bpm"] * ratio, 1))
        p = engine.prepare(self.song, {"printer": "snapmaker_u1", "speed": "fast", "tempo": "slow"})
        self.assertEqual(p["settings"]["tempo"], "slow")
        self.assertAlmostEqual(p["profile"].tempo_ratio, .75)
        self.assertEqual(p["transpose"], 12)

    def test_fast_exports_reach_notes_at_all_tempos_without_fast_z_or_homing(self):
        for tempo in ("slow", "medium", "fast"):
            for startup in ("xy_home", "prepared_no_z"):
                with self.subTest(tempo=tempo, startup=startup):
                    result = engine.convert(self.song, {"printer": "snapmaker_u1", "speed": "fast",
                                                        "tempo": tempo, "startup": startup})
                    self.assertEqual(result["transpose"], 12)
                    ratio = engine.TEMPOS[tempo]["ratio"]
                    self.assertAlmostEqual(result["duration"] * ratio, self.song["duration"])
                    report = json.loads(result["downloads"]["report"]["text"])
                    for kind in ("full", "test"):
                        output = result["downloads"][kind]
                        before, body = output["text"].split("; MELODY_BEGIN", 1)
                        music, after = body.split("; MELODY_END", 1)
                        self.assertIn("M204 S300\n", before)
                        self.assertIn("M204 S300\n", after)
                        self.assertNotIn("Z_HOP", output["text"])
                        commands = [line.split(";", 1)[0].strip() for line in output["text"].splitlines()]
                        self.assertFalse(any(word.startswith("Z") for line in commands for word in line.split()[1:]))
                        self.assertEqual([line for line in commands if line.startswith("G28")],
                                         ["G28 X Y"] if startup == "xy_home" else [])
                        self.assertTrue(any(line.startswith("G1 X") and " Y" in line for line in music.splitlines()))
                        checked = report["validation"][kind]
                        self.assertGreater(checked["xy_speed_range_mm_s"][1], 350 if kind == "full" else 260)
                        self.assertLessEqual(checked["xy_acceleration_mm_s2"], 20000)
                        self.assertLessEqual(abs(checked["total_timing_error_ms"]), 1)
                        self.assertLessEqual(checked["max_cadence_model_error_cents"], .01)
                        self.assertEqual(checked["z_isolation"]["explicit_z_moves"], 0)


if __name__ == "__main__":
    unittest.main()
