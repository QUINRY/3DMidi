"""K2 exports home before positioning, independently of slow music settings."""
import configparser
import hashlib
import json
from pathlib import Path
import sys
import unittest

import jinja2

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / "tools")]
import engine
from convert_poly_midi_u1 import plan
from foc_acoustic import make_y_scan, validate_y_scan
from motion_export import render_generic, validate_generic
from printers import get_profile

MODELS = ("creality_k2", "creality_k2_pro", "creality_k2_plus")
MODE = "k2_xy_home"


def commands(text):
    return [code for line in text.splitlines() if (code := line.split(";", 1)[0].strip())]


class K2StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "mario.mid").read_bytes(), "Mario.mid")

    def assert_startup(self, text, printer, marker="; MELODY_BEGIN"):
        code = commands(text)
        self.assertEqual([line for line in code if line.startswith("G28")], ["G28 X Y"])
        home = code.index("G28 X Y")
        first_move = next(i for i, line in enumerate(code) if line.startswith("G1 "))
        self.assertLess(home, first_move)
        limits = {}
        for line in code[:home]:
            if line.startswith("SET_VELOCITY_LIMIT "):
                limits.update({k: float(v) for k, v in (word.split("=") for word in line.split()[1:])})
            elif line.startswith("M204 S"):
                limits["ACCEL"] = float(line.split()[1][1:])
        self.assertEqual(limits, {"VELOCITY": printer["max_velocity_mm_s"],
                                 "ACCEL": printer["max_accel_mm_s2"],
                                 "ACCEL_TO_DECEL": printer["max_accel_to_decel_mm_s2"],
                                 "SQUARE_CORNER_VELOCITY": printer["square_corner_velocity_mm_s"]})
        before = commands(text.split(marker)[0])
        self.assertEqual(before.count("BED_MESH_CLEAR"), 2)
        self.assertLess(before.index("BED_MESH_CLEAR"), home)
        self.assertIn("BED_MESH_CLEAR", before[home + 1:first_move])
        self.assertEqual(code[first_move].split()[-1], "F1800.000000" if marker == "; MELODY_BEGIN" else "F1800")
        self.assertTrue(code[-3].startswith("SET_VELOCITY_LIMIT VELOCITY="))
        for forbidden in ("Z_HOP", "FORCE_MOVE", "SET_KINEMATIC_POSITION", "M84", "M18"):
            self.assertNotIn(forbidden, "\n".join(code))
        self.assertFalse(any(word.startswith(("Z", "E")) for line in code if line.startswith("G1 ") for word in line.split()[1:]))

    def test_all_models_and_music_modes_home_in_full_and_short_exports(self):
        for model in MODELS:
            self.assertEqual(get_profile(model)["startup"], MODE)
            for sound_mode in ("step_cadence", "foc_band"):
                with self.subTest(model=model, sound_mode=sound_mode):
                    # Old browser tabs still send the formerly mandatory manual startup.
                    result = engine.convert(self.song, {"printer": model, "sound_mode": sound_mode,
                                                       "startup": "prepared_no_z", "speed": "slow", "tempo": "slow"})
                    self.assertEqual(result["settings"]["startup"], MODE)
                    self.assertFalse(any("Önceden home" in warning for warning in result["warnings"]))
                    report = json.loads(result["downloads"]["report"]["text"])
                    for kind in ("full", "test"):
                        self.assert_startup(result["downloads"][kind]["text"], result["printer"])
                        checked = report["validation"][kind]
                        self.assertEqual(checked["startup_mode"], MODE)
                        self.assertTrue(checked["startup"]["automatic_homing"])
                        self.assertEqual(checked["startup"]["homing_axes"], ["x", "y"])
                        self.assertFalse(checked["startup"]["native_homing_physical_tested"])
                        z = checked["z_isolation"]
                        self.assertEqual((z["explicit_z_moves"], z["music_z_moves"], z["full_xyz_homing_commands"]), (0, 0, 0))
                        self.assertIsNone(z["startup_z_target_mm"])
                        self.assertIsNone(z["required_clearance_mm"])
                        self.assertTrue(z["clearance_managed_by_firmware"])
                        self.assertLessEqual(abs(checked["total_timing_error_ms"]), 1)

    def test_export_validator_rejects_missing_full_late_or_slow_limit_home(self):
        p = engine.prepare(self.song, {"printer": "creality_k2_pro"})
        instructions, _ = plan(p["frames"], p["duration"], engine.PLANNER, p["profile"])
        text = render_generic("Mario.mid", p["frames"], instructions, p["duration"],
                              p["profile"], p["printer"], 0, startup_mode=MODE)
        bad_files = [text.replace("G28 X Y\n", "", 1),
                     text.replace("\nG28 X Y\n", "\nG28\n", 1),
                     text.replace("\nG28 X Y\n", "\nG28 X Y Z_HOP=0\n", 1),
                     text.replace("\nG28 X Y\n", "\nG28 X Y\nG28 X Y\n", 1),
                     text.replace("VELOCITY=800", "VELOCITY=3", 1),
                     text.replace("G28 X Y\n", "", 1).replace("; MELODY_BEGIN", "; MELODY_BEGIN\nG28 X Y", 1)]
        for bad in bad_files:
            with self.subTest(change=bad[:80]), self.assertRaises(ValueError):
                validate_generic(bad, instructions, p["frames"], p["duration"], p["profile"],
                                 p["printer"], engine.PLANNER, startup_mode=MODE)

    def test_listening_scans_use_the_same_automatic_startup(self):
        for model in MODELS:
            with self.subTest(model=model):
                printer = get_profile(model)
                scan = make_y_scan(printer, engine.PLANNER)
                self.assert_startup(scan["text"], printer, "; SOUND_SCAN_BEGIN")
                self.assertEqual(scan["validation"]["home_commands"], 1)
                self.assertAlmostEqual(scan["validation"]["duration_s"], 48, places=6)
                for bad in (scan["text"].replace("G28 X Y\n", "", 1),
                            scan["text"].replace("\nG28 X Y\n", "\nG28\n", 1),
                            scan["text"].replace("; SOUND_SCAN_BEGIN", "; SOUND_SCAN_BEGIN\nG28 X Y", 1)):
                    with self.assertRaises(ValueError):
                        validate_y_scan(bad, scan["stages"], printer, engine.PLANNER)

    def test_pinned_native_xy_homing_skips_full_z_and_nozzle_clean_routes(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "reference/k2-startup/manifest.json").read_text())
        self.assertEqual({row["printer"] for row in manifest["snapshots"]}, set(MODELS))
        environment = jinja2.Environment(variable_start_string="{", variable_end_string="}",
                                        undefined=jinja2.StrictUndefined)
        for row in manifest["snapshots"]:
            source = root / row["snapshot"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), row["snapshot_sha256"])
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read(source, encoding="utf-8")
            macro = environment.from_string(config["homing_override"]["gcode"])
            for homed in ("", "x", "y", "xy", "xyz"):
                with self.subTest(model=row["printer"], homed=homed):
                    actual = commands(macro.render(params={"X": "", "Y": ""},
                                      printer={"toolhead": {"homed_axes": homed, "max_accel": 20000}},
                                      action_respond_info=lambda *_: ""))
                    actual = [line for line in actual if not line.startswith("#")]
                    self.assertIn("_HOME_X", actual)
                    self.assertIn("_HOME_Y", actual)
                    self.assertNotIn("_HOME_Z", actual)
                    self.assertFalse(any(line.startswith(("BOX_", "PRES_CHECK")) for line in actual))


if __name__ == "__main__":
    unittest.main()
