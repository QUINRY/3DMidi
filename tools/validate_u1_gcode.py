"""Independently parse the generated file and simulate its melody in U1's planner.

Only the upstream Move/LookAheadQueue AST definitions are evaluated, in a
temporary offline module. No printer or MCU object is constructed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace
from check_z_isolation import check_z_isolation


REFERENCE_SHA256 = "f28887bb85dcfd1ac530b4381bc3bf0b6103af247027870ab1a98024038f5188"
ALLOWED = {"TURN_OFF_HEATERS", "G90", "G28", "SAVE_GCODE_STATE", "M220", "M204", "G1", "G4", "M400", "RESTORE_GCODE_STATE", "BED_MESH_CLEAR"}
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_planner(path: Path) -> dict:
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == REFERENCE_SHA256, "Unexpected reference planner SHA256")
    tree = ast.parse(data.decode("utf-8"))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in {"Move", "LookAheadQueue"}
        or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LOOKAHEAD_FLUSH_TIME" for t in node.targets)
    ]
    require(len(selected) == 3, "Reference planner definitions missing")
    namespace = {"math": math}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def validate(path: Path, expected: dict, planner: dict) -> dict:
    xy_mode = expected.get("motion_mode") == "xy_octaves"
    start_position = expected.get("start_position_mm", [55.0, 135.0, 20.0])
    acceleration = expected.get("acceleration_mm_s2", 3000.0)
    max_speed = expected.get("max_toolhead_speed_mm_s", 100.0)
    max_motor_speed = expected.get("max_motor_speed_mm_s", 100.0)
    cruise_ratio = expected.get("assumed_minimum_cruise_ratio", 0.5)
    require(0 < acceleration <= 20000, "Acceleration exceeds stock U1 limit")
    require(0 < max_speed <= 500 and 0 < max_motor_speed <= 500, "Speed exceeds stock U1 limit")
    require(0 <= cruise_ratio < 1, "Invalid minimum cruise ratio")
    parsed_moves = []
    toolhead = SimpleNamespace(
        max_accel=acceleration,
        max_velocity=500.0,
        max_accel_to_decel=acceleration * (1.0 - cruise_ratio),
        junction_deviation=8.0 ** 2 * (math.sqrt(2.0) - 1.0) / acceleration,
        print_file_line=None,
        is_calibrating_flow=False,
        extruder=SimpleNamespace(calc_junction=lambda *_: float("inf")),
        _process_moves=parsed_moves.extend,
    )
    queue = planner["LookAheadQueue"](toolhead)
    position = [None, None, None, 0.0]
    melody = False
    melody_finished = False
    homed = saved = restored = False
    absolute = speed_normalized = accel_set = False
    current_accel = None
    dwell = 0.0
    note_count = 0
    buffered = []
    first_melody = last_melody = None
    supported_parameters = {
        "TURN_OFF_HEATERS": set(), "G90": set(), "G28": set(),
        "SAVE_GCODE_STATE": {"NAME=U1_MIDI"}, "M220": {"S100"},
        "M204": {f"S{acceleration:.0f}"}, "RESTORE_GCODE_STATE": {"NAME=U1_MIDI", "MOVE=0"},
        "M400": set(), "BED_MESH_CLEAR": set(),
    }
    for line_number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        if raw == "; MELODY_BEGIN":
            require(not melody and not melody_finished, "Duplicate melody begin marker")
            require(position == [*start_position, 0.0], "Incorrect starting position")
            require(homed and saved and absolute and speed_normalized and accel_set, "Incomplete setup")
            require(current_accel == acceleration, "Incorrect melody acceleration")
            melody = True
            first_melody = line_number
        elif raw == "; MELODY_END":
            require(melody, "Unmatched melody end marker")
            queue.flush()
            melody = False
            melody_finished = True
            last_melody = line_number
        elif raw.startswith("; NOTE "):
            require(melody, "Note outside melody region")
            note_count += 1
        code = raw.split(";", 1)[0].strip()
        if not code:
            continue
        fields = code.split()
        cmd, args = fields[0], fields[1:]
        require(cmd in ALLOWED, f"Disallowed command at line {line_number}: {cmd}")
        if cmd == "M204":
            require(args in [["S300"], [f"S{acceleration:.0f}"]], f"Unexpected acceleration: {code}")
        elif cmd not in {"G1", "G4"}:
            require(len(set(args)) == len(args) and set(args) == supported_parameters[cmd], f"Unexpected parameters: {code}")
        if melody:
            require(cmd in {"G1", "G4", "M400"}, "Unexpected setup command during melody")
        if restored:
            require(cmd == "TURN_OFF_HEATERS", "Command after state restoration")
        if cmd == "G90":
            absolute = True
        elif cmd == "G28":
            require(absolute and not saved, "Unexpected homing order")
            homed = True
        elif cmd == "SAVE_GCODE_STATE":
            require(homed and not saved, "Incorrect state save order")
            saved = True
        elif cmd == "RESTORE_GCODE_STATE":
            require(saved and melody_finished, "Missing saved state or melody end")
            restored = True
        elif cmd == "M220":
            require(saved, "Speed factor not saved")
            speed_normalized = True
        elif cmd == "M204":
            require(saved, "Acceleration not saved")
            accel_set = True
            current_accel = float(args[0][1:])
        elif cmd == "BED_MESH_CLEAR":
            require(homed and current_accel == 300 and not melody, "Unexpected mesh clear")
        elif cmd == "G1":
            require(homed and saved and absolute and speed_normalized and accel_set, "Motion before setup")
            require(all(re.fullmatch(r"[XYZF]" + NUMBER, arg) for arg in args), "Malformed motion or extrusion")
            require(len({a[0] for a in args}) == len(args), "Duplicate motion parameter")
            values = {arg[0]: float(arg[1:]) for arg in args}
            require(all(math.isfinite(v) for v in values.values()), "Nonfinite motion")
            require("F" in values and 0 < values["F"] <= max_speed * 60.0, "Invalid feedrate")
            y_low, y_high = (55.0, 215.0) if xy_mode else (135.0, 135.0)
            for axis, index, low, high in [("X", 0, 55.0, 215.0), ("Y", 1, y_low, y_high), ("Z", 2, 20.0, 20.0)]:
                if axis in values:
                    require(low <= values[axis] <= high, f"{axis} outside central area")
            end = list(position)
            for axis, index in [("X", 0), ("Y", 1), ("Z", 2)]:
                if axis in values:
                    end[index] = values[axis]
            if melody:
                require(set(values) == {"X", "Y", "F"}, "Melody must specify XY and feedrate only")
                require(end[2] == position[2] == 20.0, "Melody changes Z")
                if xy_mode:
                    require(abs(end[0] - position[0]) > 0.001 and abs(end[1] - position[1]) > 0.001,
                            "Each XY melody stroke must move both axes")
                else:
                    require(end[1] == position[1] == 135.0, "X-only melody changes Y")
                move = planner["Move"](toolhead, position, end, values["F"] / 60.0)
                require(move.move_d > 0, "Zero-length melody move")
                queue.add_move(move)
                buffered.append((line_number, values["F"] / 60.0))
            position = end
        elif cmd == "G4":
            require(len(args) == 1 and re.fullmatch("P" + NUMBER, args[0]), "Malformed dwell")
            delay = float(args[0][1:]) / 1000.0
            require(0.0 <= delay <= 10.0, "Invalid dwell")
            if melody:
                queue.flush()
                dwell += delay
        elif cmd == "M400" and melody:
            queue.flush()
    require(first_melody is not None and last_melody is not None, "Missing melody markers")
    require(restored and position == [135.0, 135.0, 20.0, 0.0], "Incomplete cleanup")
    require(note_count == expected["note_count"], "MIDI note count changed")
    require(len(parsed_moves) == len(expected["strokes"]) == len(buffered), "Stroke count changed")
    timings = []
    max_pitch_error_cents = 0.0
    max_stroke_error = 0.0
    min_cruise_fraction = 1.0
    x_travel = y_travel = 0.0
    for move, planned, (line, speed) in zip(parsed_moves, expected["strokes"], buffered):
        require(abs(move.start_v) < 1e-8 and abs(move.end_v) < 1e-8, f"Nonzero boundary velocity at {line}")
        require(abs(move.cruise_v - speed) < 1e-6, f"Planner cannot reach target speed at {line}")
        elapsed = move.accel_t + move.cruise_t + move.decel_t
        error = abs(elapsed - planned["duration_s"])
        max_stroke_error = max(max_stroke_error, error)
        require(error < 0.00001, f"Stroke timing mismatch at {line}")
        # Independently invert the emitted CoreXY movement. In XY mode
        # the two motors must produce the melody and its lower octave;
        # in the previous X-only format both produced the same cadence.
        dx, dy = move.axes_d[:2]
        x_travel += abs(dx)
        y_travel += abs(dy)
        target_hz = 440.0 * 2.0 ** ((planned["target_pitch"] - 69) / 12.0)
        expected_frequencies = [target_hz / 2.0, target_hz] if xy_mode else [target_hz, target_hz]
        actual_frequencies = []
        for motor_distance in [dx + dy, dx - dy]:
            motor_speed = abs(motor_distance) / move.move_d * move.cruise_v
            require(motor_speed <= max_motor_speed + 1e-4, f"Motor speed limit exceeded at {line}")
            model_hz = abs(motor_distance) / move.move_d * move.cruise_v * 200.0 / 40.0 / expected["cadence_scale"]
            require(model_hz > 0, f"A CoreXY motor is stationary at {line}")
            actual_frequencies.append(model_hz)
        for model_hz, desired_hz in zip(sorted(actual_frequencies), expected_frequencies):
            cents = abs(1200.0 * math.log2(model_hz / desired_hz))
            max_pitch_error_cents = max(max_pitch_error_cents, cents)
            require(cents < 0.001, f"Frequency mapping error at {line}")
        min_cruise_fraction = min(min_cruise_fraction, move.cruise_t / elapsed)
        timings.append(elapsed)
    if xy_mode:
        require(x_travel > 10.0 and y_travel > 10.0, "Melody does not use both axes")
    total = sum(timings) + dwell
    require(abs(total - expected["melody_duration_s"]) < 0.001, "Total melody timing changed")
    if expected.get("z_isolated"):
        check_z_isolation(path)
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "note_count": note_count,
        "simulated_strokes": len(parsed_moves),
        "simulated_melody_duration_s": total,
        "total_timing_error_ms": (total - expected["melody_duration_s"]) * 1000.0,
        "max_stroke_timing_error_us": max_stroke_error * 1000000.0,
        "max_cadence_model_error_cents": max_pitch_error_cents,
        "minimum_cruise_time_fraction": min_cruise_fraction,
        "motion_mode": expected.get("motion_mode", "x_unison"),
        "motion_profile": expected.get("motion_profile", "normal"),
        "acceleration_mm_s2": acceleration,
        "max_toolhead_speed_mm_s": max(m.cruise_v for m in parsed_moves),
        "total_melody_x_travel_mm": x_travel,
        "total_melody_y_travel_mm": y_travel,
        "bounded_motion_and_command_allowlist": "passed",
        "no_extrusion_or_heating": "passed",
        "planner_source_sha256": REFERENCE_SHA256,
        "physical_printer_test": "not performed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--planner", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    planner = load_planner(args.planner)
    full_path = args.report.with_suffix(".gcode")
    test_path = full_path.with_name(full_path.stem + "_test.gcode")
    results = {"full": validate(full_path, report["full"], planner), "test": validate(test_path, report["test"], planner)}
    report["validation"] = results
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
