"""KE automatic startup export contract: slow setup Z and XY-only music."""
from __future__ import annotations

import ast
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app")]

from convert_poly_midi_u1 import PolyProfile, plan
from motion_export import render_generic, validate_generic
from printers import get_profile
from validate_u1_gcode import load_planner


MODE = "ke_auto_home_slow_z"


class KeAutomaticExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.printer = get_profile("creality_ender3_v3_ke")
        cls.printer["startup"] = MODE
        bounds, route = cls.printer["music_bounds"], cls.printer["route_bounds"]
        cls.profile = PolyProfile(
            "test", 3000, 100, 120, 1, True,
            cadence_per_mm=cls.printer["x"]["fullsteps_per_mm"],
            cadence_y_per_mm=cls.printer["y"]["fullsteps_per_mm"],
            kinematics="cartesian", start_xy=tuple(cls.printer["start_xy"]),
            route_bounds=tuple(route["x"] + route["y"]),
            physical_bounds=tuple(bounds["x"] + bounds["y"]),
            firmware_max_velocity=500, square_corner_velocity=5, smoothing_accel=2500,
            music_axes="x",
        )
        cls.frames = [{"index": 0, "start": 0., "end": .7, "target_pitches": [48]},
                      {"index": 1, "start": .9, "end": 1.7, "target_pitches": [50]}]
        cls.planner = load_planner(ROOT / "app/assets/u1_toolhead.py")
        cls.instructions, _ = plan(cls.frames, 2., cls.planner, cls.profile)

    def render(self, mode=MODE, printer=None):
        return render_generic("ke.mid", self.frames, self.instructions, 2., self.profile,
                              self.printer if printer is None else printer, 0, startup_mode=mode)

    def validate(self, text, mode=MODE):
        return validate_generic(text, self.instructions, self.frames, 2., self.profile,
                                self.printer, self.planner, startup_mode=mode)

    def test_generated_file_restores_normal_limits_before_homing_and_at_end(self):
        # A preceding aborted file may have left a 3 mm/s global limit.
        # Replay the emitted limit commands at the actual G28 call site.
        limits = {"VELOCITY": 3., "ACCEL": 100., "ACCEL_TO_DECEL": 50.}
        homing_limits = None
        text = self.render()
        for line in text.splitlines():
            code = line.split(";", 1)[0].strip()
            if code.startswith("SET_VELOCITY_LIMIT "):
                limits.update({key: float(value) for key, value in
                               (word.split("=", 1) for word in code.split()[1:])})
            elif code.startswith("M204 S"):
                limits["ACCEL"] = float(code.split()[1][1:])
            elif code == "G28":
                homing_limits = dict(limits)
        self.assertIsNotNone(homing_limits)
        for state in (homing_limits, limits):
            self.assertEqual(state["VELOCITY"], self.printer["max_velocity_mm_s"])
            self.assertEqual(state["ACCEL"], self.printer["max_accel_mm_s2"])
            self.assertEqual(state["ACCEL_TO_DECEL"], self.printer["max_accel_to_decel_mm_s2"])
        # Use the pinned vendor Move implementation, rather than assuming
        # an F word can override a lower persistent toolhead velocity cap.
        tree = ast.parse((ROOT / "reference/ke-startup/toolhead.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Move")
        namespace = {"math": math}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "vendor_toolhead", "exec"), namespace)
        toolhead = SimpleNamespace(max_velocity=homing_limits["VELOCITY"],
                                   max_accel=homing_limits["ACCEL"],
                                   max_accel_to_decel=homing_limits["ACCEL_TO_DECEL"],
                                   junction_deviation=.01)
        move = namespace["Move"](toolhead, [0, 0, 20, 0], [100, 0, 20, 0], 30.)
        self.assertEqual(math.sqrt(move.max_cruise_v2), 30.)

    def test_auto_home_precedes_slow_separate_z_and_music_limits(self):
        text = self.render()
        before, music = text.split("; MELODY_BEGIN", 1)
        self.assertNotIn("Z_HOP", text)
        self.assertEqual(before.splitlines().count("G28"), 1)
        self.assertNotIn("SET_VELOCITY_LIMIT VELOCITY=3 ", text)
        self.assertIn("SET_VELOCITY_LIMIT VELOCITY=500 ACCEL=8000 ACCEL_TO_DECEL=2500", before)
        self.assertIn("G1 Z20.0000000 F180.000000", before)
        self.assertLess(before.index("VELOCITY=500"), before.index("\nG28\n"))
        self.assertLess(before.index("\nG28\n"), before.index("G1 Z20.0000000"))
        self.assertLess(before.index("\nG28\n"), before.index("M204 S100"))
        self.assertLess(before.index("G1 Z20.0000000"), before.rindex("VELOCITY=500"))
        self.assertLess(before.rindex("VELOCITY=500"), before.index("M204 S3000"))
        report = self.validate(text)
        self.assertEqual(report["startup_mode"], MODE)
        self.assertEqual(report["z_isolation"]["explicit_z_moves"], 1)
        self.assertEqual(report["z_isolation"]["music_z_moves"], 0)
        self.assertEqual(report["z_isolation"]["xy_homing_commands"], 1)
        self.assertTrue(report["startup"]["force_move_override_required_for_all_z_slow"])
        self.assertFalse(report["startup"]["compiled_probe_speed_and_heating_verified"])
        for line in music.split("; MELODY_END", 1)[0].splitlines():
            code = line.split(";", 1)[0].strip()
            self.assertFalse(code.startswith(("G28", "SET_VELOCITY_LIMIT")))
            self.assertFalse(any(word.startswith("Z") for word in code.split()[1:]))

    def test_rejects_changed_startup_rates_and_z_outside_startup(self):
        text = self.render()
        normal_limits = "SET_VELOCITY_LIMIT VELOCITY=500 ACCEL=8000 ACCEL_TO_DECEL=2500 SQUARE_CORNER_VELOCITY=5"
        changes = {
            "slow_homing_cap": text.replace("VELOCITY=500 ACCEL=8000", "VELOCITY=3 ACCEL=100", 1),
            "missing_prehome_restore": text.replace(normal_limits + "\n", "", 1),
            "missing_final_restore": text.rsplit(normal_limits + "\n", 1)[0] + text.rsplit(normal_limits + "\n", 1)[1],
            "music_acceleration_on_z": text.replace("M204 S100\nG1 Z20", "M204 S3000\nG1 Z20", 1),
            "fast_z_feed": text.replace("Z20.0000000 F180.000000", "Z20.0000000 F1800.000000", 1),
            "mixed_z_xy": text.replace("G1 Z20.0000000", "G1 X110 Z20.0000000", 1),
            "missing_home": text.replace("\nG28\n", "\n", 1),
            "unsupported_hop_argument": text.replace("\nG28\n", "\nG28 X Y Z_HOP=0\n", 1),
            "restore_before_raise": text.replace("G1 Z20.0000000 F180.000000", "SET_VELOCITY_LIMIT VELOCITY=500\nG1 Z20.0000000 F180.000000", 1),
            "music_z": text.replace("; MELODY_BEGIN", "; MELODY_BEGIN\nG1 Z21 F180", 1),
            "end_z": text.replace("; MELODY_END", "; MELODY_END\nG1 Z21 F180", 1),
            "fake_home": text.replace("\nG28\n", "\nSET_KINEMATIC_POSITION X0 Y0 Z0\n", 1),
            "force_move": text.replace("\nG28\n", "\nFORCE_MOVE STEPPER=stepper_z DISTANCE=5 VELOCITY=20\nG28\n", 1),
        }
        for name, changed in changes.items():
            with self.subTest(mutation=name), self.assertRaises(ValueError):
                self.validate(changed)

    def test_prepared_start_remains_available_and_auto_is_model_specific(self):
        text = self.render("prepared_no_z")
        self.assertNotIn("\nG28\n", text)
        self.assertNotIn("\nG1 Z", text)
        self.assertNotIn("SET_VELOCITY_LIMIT", text)
        self.validate(text, "prepared_no_z")
        with self.assertRaises(ValueError):
            self.render(printer=dict(self.printer, id="unverified_other_printer"))
        with self.assertRaises(ValueError):
            self.render(mode="unrecognized_startup")


if __name__ == "__main__":
    unittest.main()
