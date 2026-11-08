"""Offline regression checks for generic XY export and its independent validator."""
from __future__ import annotations

import hashlib
import re
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app")]

from convert_poly_midi_u1 import PolyProfile, plan
from motion_export import render_generic, validate_generic
from validate_u1_gcode import load_planner


class GenericMotionExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = load_planner(ROOT / "app/assets/u1_toolhead.py")
        base = PolyProfile("test", 7000, 180, 240, 1, False)
        cls.profiles = {
            "corexy_equal": base,
            "corexy_unequal": replace(base, cadence_y_per_mm=200 / 60),
            "cartesian_equal": replace(base, kinematics="cartesian"),
            "cartesian_unequal": replace(base, kinematics="cartesian", cadence_y_per_mm=200 / 60),
        }
        cls.cases = {}
        for name, profile in cls.profiles.items():
            printer = {
                "id": name, "name": name, "kinematics": profile.kinematics,
                "max_velocity_mm_s": 500, "max_accel_mm_s2": 20000,
                "music_max_velocity_mm_s": 360, "music_max_accel_mm_s2": 12000,
                "x": {"min": 0, "max": 300}, "y": {"min": 0, "max": 300},
                "has_bed_mesh": True,
            }
            frames = [
                {"index": 0, "start": 0.0, "end": 0.7, "target_pitches": [60, 48]},
                {"index": 1, "start": 0.9, "end": 1.7, "target_pitches": [62, 50]},
            ]
            instructions, _ = plan(frames, 2.0, cls.planner, profile)
            text = render_generic("regression.mid", frames, instructions, 2.0, profile, printer, 0)
            cls.cases[name] = (profile, printer, frames, instructions, text)

    def validate(self, case, text=None, instructions=None, frames=None):
        profile, printer, case_frames, case_instructions, original = case
        return validate_generic(
            original if text is None else text,
            case_instructions if instructions is None else instructions,
            case_frames if frames is None else frames,
            2.0, profile, printer, self.planner,
        )

    def test_four_kinematics_and_cadence_combinations(self):
        for name, case in self.cases.items():
            with self.subTest(profile=name):
                report = self.validate(case)
                self.assertEqual(report["sha256"], hashlib.sha256(case[-1].encode("ascii")).hexdigest())
                self.assertEqual(report["simulated_moves"], 2)
                self.assertEqual(report["musical_rests"], 2)
                self.assertLessEqual(abs(report["total_timing_error_ms"]), 1.0)
                self.assertLessEqual(report["max_cadence_model_error_cents"], 0.01)
                self.assertEqual(report["z_isolation"]["explicit_z_moves"], 0)
                self.assertFalse(report["z_isolation"]["clearance_checked_by_file"])
                self.assertEqual(report["physical_printer_test"], "not performed")
                self.assertEqual(report["reference_planner_assessment"]["vendor_firmware_equivalence"], "not verified")

    def test_rejects_sixteen_unsafe_command_mutations(self):
        # Four original safety mutations across every supported cadence mapping.
        for name, case in self.cases.items():
            text = case[-1]
            mutations = {
                "home": text.replace("G90", "G28"),
                "feed_override": text.replace("M220 S100", "M220 S200"),
                "moving_restore": text.replace("MOVE=0", "MOVE=1"),
                "z_move": text.replace("; MELODY_BEGIN", "; MELODY_BEGIN\nG1 Z20 F300"),
            }
            for mutation, changed in mutations.items():
                with self.subTest(profile=name, mutation=mutation):
                    with self.assertRaises(ValueError):
                        self.validate(case, changed)

    def test_rejects_changed_geometry_feed_and_missing_notes(self):
        for name, case in self.cases.items():
            text = case[-1]
            head, body = text.split("; MELODY_BEGIN", 1)
            changes = {
                "coordinate": re.sub(r"(G1 X)([-+0-9.]+)", lambda m: m[1] + f"{float(m[2]) + 0.01:.7f}", body, count=1),
                "feed": re.sub(r"( F)([-+0-9.]+)", lambda m: m[1] + f"{float(m[2]) * 0.9:.6f}", body, count=1),
                "missing_move": re.sub(r"\nG1 [^\n]+", "", body, count=1),
                "missing_event": re.sub(r"\n; EVENT \d+", "", body, count=1),
            }
            for mutation, changed_body in changes.items():
                with self.subTest(profile=name, mutation=mutation):
                    with self.assertRaises(ValueError):
                        self.validate(case, head + "; MELODY_BEGIN" + changed_body)

    def test_bounds_are_checked_even_when_the_plan_matches_the_bad_endpoint(self):
        for name, case in self.cases.items():
            profile, printer, frames, instructions, _ = case
            for coordinate in (-1.0, 54.0, 216.0, 301.0):
                with self.subTest(profile=name, x=coordinate):
                    bad = [dict(item) for item in instructions]
                    next(item for item in bad if item["kind"] == "move")["x"] = coordinate
                    text = render_generic("bounds.mid", frames, bad, 2.0, profile, printer, 0)
                    with self.assertRaisesRegex(ValueError, "bounds"):
                        self.validate(case, text, bad)

    def test_solved_moves_can_expand_past_the_route_seed_within_physical_bounds(self):
        for name, case in self.cases.items():
            profile, printer, frames, instructions, _ = case
            narrow = replace(profile, route_bounds=(134.9, 135.1, 134.9, 135.1))
            text = render_generic("expanded.mid", frames, instructions, 2.0, narrow, printer, 0)
            with self.subTest(profile=name):
                report = validate_generic(text, instructions, frames, 2.0, narrow, printer, self.planner)
                self.assertEqual(report["route_seed_bounds_mm"], list(narrow.route_bounds))
                self.assertEqual(report["validated_physical_bounds_mm"], list(narrow.physical_bounds))

    def test_target_pitch_changes_are_detected_independently_of_the_plan(self):
        for name, case in self.cases.items():
            profile, printer, frames, instructions, _ = case
            bad_frames = [dict(frame, target_pitches=list(frame["target_pitches"])) for frame in frames]
            bad_frames[0]["target_pitches"] = [61, 49]
            bad_instructions = [dict(item) for item in instructions]
            for item in bad_instructions:
                if item.get("frame") == 0:
                    item["targets"] = [61, 49]
            text = render_generic("pitch.mid", bad_frames, bad_instructions, 2.0, profile, printer, 0)
            with self.subTest(profile=name):
                with self.assertRaisesRegex(ValueError, "frequencies"):
                    self.validate(case, text, bad_instructions, bad_frames)

    def test_mesh_clear_is_optional_and_names_cannot_inject_commands(self):
        profile, printer, frames, instructions, _ = self.cases["corexy_equal"]
        printer = dict(printer, has_bed_mesh=False, name="Printer\nG28")
        text = render_generic("melodi\nG1 Z10.mid", frames, instructions, 2.0, profile, printer, 0)
        self.assertNotIn("\nBED_MESH_CLEAR\n", text)
        report = validate_generic(text, instructions, frames, 2.0, profile, printer, self.planner)
        self.assertFalse(report["active_mesh_cleared_before_music"])

    def test_setup_respects_low_imported_factory_limits(self):
        profile = replace(
            self.profiles["cartesian_equal"], acceleration=200,
            max_speed=20, max_motor_speed=30, firmware_max_velocity=20,
        )
        printer = dict(self.cases["cartesian_equal"][1], max_velocity_mm_s=20,
                       max_accel_mm_s2=200, music_max_velocity_mm_s=20, music_max_accel_mm_s2=200)
        frames = [
            {"index": 0, "start": 0.0, "end": 0.7, "target_pitches": [36, 24]},
            {"index": 1, "start": 0.9, "end": 1.7, "target_pitches": [38, 26]},
        ]
        instructions, _ = plan(frames, 2.0, self.planner, profile)
        text = render_generic("slow.mid", frames, instructions, 2.0, profile, printer, 0)
        self.assertIn("M204 S200.000000", text)
        self.assertIn("F1200.000000", text)
        validate_generic(text, instructions, frames, 2.0, profile, printer, self.planner)

    def test_acceleration_above_printer_limit_is_rejected(self):
        case = self.cases["corexy_equal"]
        profile, printer, frames, instructions, _ = case
        with self.assertRaises(ValueError):
            render_generic("invalid.mid", frames, instructions, 2.0,
                           replace(profile, acceleration=12001), printer, 0)


if __name__ == "__main__":
    unittest.main()

