"""Native Bambu protocol regressions; no physical printer is accessed."""
import hashlib
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

from bambu_native import convert_native, prepare_native, summary_native, validate_native, _segments


PRINTER = {"id": "bambu_a1_mini", "name": "Bambu Lab A1 mini", "source": {"url": "https://github.com/bambulab/BambuStudio"}}


def song(notes=None, duration=10.003):
    if notes is None:
        notes = [(0, 1, 60), (0, 2, 48), (1, 3.016, 64), (5, duration, 67)]
    return {"filename": "example.mid", "bytes": 123, "notes": [SimpleNamespace(start=a, end=b, pitch=p) for a, b, p in notes],
            "duration": duration, "tracks": 3, "bpm": 120, "tempos": [{"time": 0, "bpm": 120}],
            "sha256": "source-sha", "percussion": 2, "bends": True,
            "library_source": {"license": "CC BY-SA 3.0", "attribution": "Example source"}}


class BambuNativeTests(unittest.TestCase):
    def test_full_test_and_z_muting(self):
        source = song()
        prepared = prepare_native(source, {}, PRINTER)
        result = convert_native(source, prepared, "BambuLabA1mini_example_Orta_Orta")
        self.assertEqual(result["output_mode"], "bambu_native")
        self.assertEqual(result["path"], [])
        self.assertIsNone(result["acceleration"])
        self.assertEqual(result["downloads"]["test"]["seconds"], 8)
        report = json.loads(result["downloads"]["report"]["text"])
        for kind in ("full", "test"):
            data = result["downloads"][kind]["text"]
            self.assertEqual(hashlib.sha256(data.encode("ascii")).hexdigest(), report["validation"][kind]["sha256"])
            commands = [line for line in data.splitlines() if line and not line.startswith(";")]
            self.assertTrue(all(line.split()[0] in {"M17", "M400", "M1006"} for line in commands))
            rows = [line for line in commands if line.startswith("M1006 A")]
            self.assertTrue(rows)
            self.assertTrue(all(" E0 F0 N0" in line for line in rows))
        self.assertEqual(report["library_source"]["license"], "CC BY-SA 3.0")
        self.assertFalse(result["checks"]["planner"])

    def test_note_off_sweep_preserves_held_voice_and_rest(self):
        prepared = prepare_native(song([(0, 1, 60), (0, 2, 48), (3, 4, 67)], duration=5), {}, PRINTER)
        self.assertEqual([(f["start"], f["end"], f["pitches"]) for f in prepared["frames"]],
                         [(0, 1, [60, 48]), (1, 2, [48, 36]), (2, 3, []), (3, 4, [67, 55]), (4, 5, [])])

    def test_tempo_and_register_are_independent(self):
        source = song([(0, 1, 60)], 1)
        medium = prepare_native(source, {}, PRINTER)
        fast_tempo = prepare_native(source, {"tempo": "fast"}, PRINTER)
        high = prepare_native(source, {"speed": "fast"}, PRINTER)
        self.assertEqual(medium["frames"][0]["pitches"], fast_tempo["frames"][0]["pitches"])
        self.assertEqual(fast_tempo["duration"], .8)
        self.assertEqual(high["frames"][0]["pitches"], [72, 60])
        self.assertEqual(high["duration"], medium["duration"])

    def test_repeated_note_attacks_remain_separate_commands(self):
        source = song([(0, .5, 60), (.5, 1, 60)], 1)
        prepared = prepare_native(source, {}, PRINTER)
        self.assertEqual(len(prepared["frames"]), 2)
        result = convert_native(source, prepared, "repeated")
        rows = [line for line in result["downloads"]["full"]["text"].splitlines() if line.startswith("M1006 A37")]
        self.assertEqual(len(rows), 2)

    def test_all_audible_notes_below_tick_resolution_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "10 ms"):
            prepare_native(song([(0, .001, 60)], 2), {}, PRINTER)

    def test_absolute_quantization_prevents_cumulative_drift(self):
        notes = [(i * .017, (i + 1) * .017, 60 + i % 2) for i in range(500)]
        source = song(notes, 8.5)
        prepared = prepare_native(source, {}, PRINTER)
        result = convert_native(source, prepared, "timeline")
        report = json.loads(result["downloads"]["report"]["text"])
        self.assertEqual(report["validation"]["full"]["music_duration_s"], 8.5)
        self.assertLessEqual(prepared["max_quantization_error_s"], .00500001)

    def test_long_notes_split_at_two_seconds_and_short_frames_explained(self):
        source = song([(0, .001, 60), (.001, .004, 61), (.004, 10.003, 67)])
        prepared = prepare_native(source, {}, PRINTER)
        self.assertGreater(prepared["dropped_short_frames"], 0)
        segments = _segments(prepared["frames"], prepared["duration_ticks"])
        self.assertTrue(all(1 <= row["ticks"] <= 200 for row in segments))
        self.assertEqual(sum(row["ticks"] for row in segments), prepared["duration_ticks"])
        self.assertTrue(any("10 ms" in warning for warning in prepared["warnings"]))

    def test_wide_input_is_documented_and_never_clips_pitch_class(self):
        prepared = prepare_native(song([(0, 1, 0), (1, 2, 127)], 2), {}, PRINTER)
        self.assertGreater(prepared["folded_voice_events"], 0)
        pitches = [p for frame in prepared["frames"] for p in frame["pitches"]]
        self.assertTrue(all(24 <= p <= 95 for p in pitches))
        self.assertEqual(prepared["frames"][0]["pitches"][0] % 12, 0)
        self.assertEqual(prepared["frames"][1]["pitches"][0] % 12, 127 % 12)

    def test_unsafe_or_changed_protocol_is_rejected(self):
        source = song()
        prepared = prepare_native(source, {}, PRINTER)
        text = convert_native(source, prepared, "test")["downloads"]["full"]["text"]
        segments = _segments(prepared["frames"], prepared["duration_ticks"])
        mutations = [text.replace("E0 F0 N0", "E30 F10 N70", 1),
                     text.replace("M1006 L70 M70 N0", "M1006 L70 M70 N99"),
                     text + "G1 Z10 F10000\n", text + "G28\n", text + "M18\n",
                     text.replace("M400 S1", "TURN_OFF_HEATERS"),
                     text.replace("L70 C", "L99 C", 1),
                     text.replace("M1006 A37", "M1006 A38", 1),
                     text.replace("M1006 A37", "M1006 Z37", 1)]
        for mutated in mutations:
            with self.subTest(change=mutated[-60:]), self.assertRaises(ValueError):
                validate_native(mutated, segments, prepared["duration_ticks"])

    def test_settings_validation_and_source_are_inert(self):
        for settings in ({"speed": []}, {"tempo": {}}, {"voice": []}, {"speed": "unknown"}):
            with self.assertRaises(ValueError):
                prepare_native(song(), settings, PRINTER)
        source = song()
        source["filename"] = "name\nG1 Z99.mid"
        result = convert_native(source, prepare_native(source, {}, PRINTER), "safe_name")
        self.assertNotIn("\nG1 Z99", result["downloads"]["full"]["text"])


if __name__ == "__main__":
    unittest.main()
