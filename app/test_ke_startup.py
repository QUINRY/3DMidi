"""Source replay for KE slow startup and its optional Z FORCE_MOVE wrapper."""
from __future__ import annotations

import ast
import configparser
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import jinja2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ke_startup import KE_AUTO_STARTUP, KE_ID, startup_commands, startup_report

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "reference/ke-startup"


def config_macro(path, section):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(path, encoding="utf-8")
    return config[section]["gcode"]


def render_macro(text, **context):
    environment = jinja2.Environment(block_start_string="{%", block_end_string="%}",
                                    variable_start_string="{", variable_end_string="}",
                                    undefined=jinja2.StrictUndefined)
    rendered = environment.from_string(text).render(**context)
    return [line.split(";", 1)[0].strip() for line in rendered.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def parameters(line):
    return dict(word.split("=", 1) for word in line.split()[1:])


class KeStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wrapper = config_macro(EVIDENCE / "midi_ke_slow_z.cfg", "gcode_macro FORCE_MOVE")
        cls.profile = {"id": KE_ID, "startup": KE_AUTO_STARTUP, "has_bed_mesh": True,
                       "max_velocity_mm_s": 500, "max_accel_mm_s2": 8000,
                       "max_accel_to_decel_mm_s2": 2500, "square_corner_velocity_mm_s": 5}

    def test_standalone_order_and_separate_slow_z(self):
        commands = startup_commands(self.profile)
        self.assertEqual(commands[0], "SET_VELOCITY_LIMIT VELOCITY=500 ACCEL=8000 ACCEL_TO_DECEL=2500 SQUARE_CORNER_VELOCITY=5")
        self.assertFalse(any("VELOCITY=3 " in line for line in commands))
        self.assertEqual(commands.count("G28"), 1)
        self.assertLess(commands.index("G28"), commands.index("G1 Z20.0000000 F180.000000"))
        self.assertLess(commands.index("TURN_OFF_HEATERS"), commands.index("G1 Z20.0000000 F180.000000"))
        self.assertLess(commands.index("BED_MESH_CLEAR"), commands.index("G1 Z20.0000000 F180.000000"))
        self.assertLess(commands.index("G28"), commands.index("M204 S100"))
        self.assertEqual(commands[commands.index("G1 Z20.0000000 F180.000000") - 1], "M204 S100")
        self.assertEqual([line for line in commands if line.startswith("G1")], ["G1 Z20.0000000 F180.000000"])
        self.assertTrue(commands[-1].startswith("SET_VELOCITY_LIMIT VELOCITY=500 ACCEL=8000 ACCEL_TO_DECEL=2500"))
        for forbidden in ("Z_HOP", "SET_KINEMATIC_POSITION", "FORCE_MOVE", "M84", "M18"):
            self.assertNotIn(forbidden, "\n".join(commands))

    def test_prepared_or_other_printer_has_no_automatic_sequence(self):
        self.assertEqual(startup_commands({**self.profile, "startup": "prepared_no_z"}), [])
        self.assertEqual(startup_commands({**self.profile, "id": "snapmaker_u1"}), [])

    def test_report_does_not_claim_unverified_stock_homing_is_fully_slow(self):
        report = startup_report(self.profile)
        self.assertTrue(report["force_move_override_required_for_all_z_slow"])
        self.assertTrue(report["stock_force_move_bypasses_toolhead_limits"])
        self.assertFalse(report["wrapper_installed_verified"])
        self.assertFalse(report["compiled_probe_speed_and_heating_verified"])
        self.assertTrue(report["homing_uses_normal_profile_limits"])
        self.assertTrue(report["normal_profile_limits_restored_at_finish"])
        self.assertFalse(report["global_velocity_lowered_for_clearance"])
        self.assertEqual(report["homing_toolhead_velocity_limit_mm_s"], 500)
        self.assertEqual(report["clearance_move_mm_s"], 3)
        self.assertFalse(report["z_during_music"])

    def test_actual_stock_fresh_home_hop_is_capped_by_wrapper(self):
        macro = config_macro(EVIDENCE / "sensorless.cfg", "gcode_macro _IF_MOVE_X")
        state = {"x_moved": 0, "y_moved": 0, "safe_z": 5}
        stock = render_macro(macro, printer={"gcode_macro xyz_ready": state})
        force = next(line for line in stock if line.startswith("FORCE_MOVE "))
        source = parameters(force)
        self.assertEqual(source, {"STEPPER": "stepper_z", "DISTANCE": "5", "VELOCITY": "20"})
        changed = render_macro(self.wrapper, params=source, rawparams=force.split(" ", 1)[1])
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].split()[0], "FORCE_MOVE_BASE")
        actual = parameters(changed[0])
        self.assertEqual(actual["DISTANCE"], source["DISTANCE"])
        self.assertEqual(float(actual["VELOCITY"]), 3)
        self.assertEqual(float(actual["ACCEL"]), 100)

    def test_low_requested_z_speed_and_accel_remain_low(self):
        params = {"STEPPER": "stepper_z", "DISTANCE": "-2", "VELOCITY": "0.5", "ACCEL": "20"}
        actual = parameters(render_macro(self.wrapper, params=params, rawparams="unused")[0])
        self.assertEqual(float(actual["VELOCITY"]), .5)
        self.assertEqual(float(actual["ACCEL"]), 20)
        self.assertEqual(actual["DISTANCE"], "-2")

    def test_other_stepper_commands_are_forwarded_unchanged(self):
        raw = "STEPPER=stepper_y DISTANCE=4 VELOCITY=20 ACCEL=300"
        actual = render_macro(self.wrapper, params=parameters("FORCE_MOVE " + raw), rawparams=raw)
        self.assertEqual(actual, ["FORCE_MOVE_BASE " + raw])

    def test_force_hop_gets_acceleration_when_stock_omits_or_zeroes_it(self):
        for accel in (None, "0"):
            params = {"STEPPER": "stepper_z", "DISTANCE": "5", "VELOCITY": "20"}
            if accel is not None:
                params["ACCEL"] = accel
            actual = parameters(render_macro(self.wrapper, params=params, rawparams="unused")[0])
            self.assertEqual(float(actual["ACCEL"]), 100)

    def test_actual_vendor_move_preserves_normal_homing_and_z_only_wrapper_is_separate(self):
        tree = ast.parse((EVIDENCE / "toolhead.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Move")
        namespace = {"math": math}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "vendor_toolhead", "exec"), namespace)
        toolhead = SimpleNamespace(max_velocity=500, max_accel=8000, max_accel_to_decel=2500, junction_deviation=.01)
        move = namespace["Move"](toolhead, [0, 0, 20, 0], [100, 0, 20, 0], 30)
        self.assertEqual(math.sqrt(move.max_cruise_v2), 30)
        self.assertEqual(move.accel, 8000)
        clearance = namespace["Move"](SimpleNamespace(**{**vars(toolhead), "max_accel": 100}),
                                       [110, 110, 0, 0], [110, 110, 20, 0], 3)
        self.assertEqual(math.sqrt(clearance.max_cruise_v2), 3)
        self.assertEqual(clearance.accel, 100)
        tree = ast.parse((EVIDENCE / "force_move.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "calc_move_time")
        namespace = {"math": math}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "vendor_force_move", "exec"), namespace)
        self.assertEqual(namespace["calc_move_time"](5, 20, 0)[-1], 20)
        capped = namespace["calc_move_time"](5, 3, 100)
        self.assertEqual(capped[-1], 3)
        self.assertGreater(capped[1], 0)


if __name__ == "__main__":
    unittest.main()
