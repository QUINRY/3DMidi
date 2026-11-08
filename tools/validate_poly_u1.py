"""Validate actual two-voice G-code with the official U1 motion planner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

from check_z_isolation import check_z_isolation
from validate_u1_gcode import load_planner, require


ALLOWED = {"TURN_OFF_HEATERS", "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE", "G90", "G28", "M220", "M204", "G1", "M400", "G4", "BED_MESH_CLEAR"}
NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"


def validate(path: Path, section: dict, source_notes: list, planner: dict) -> dict:
    xy_home = section.get("startup_mode") in {"xy_home", "xy_home_zero_hop"}
    prepared_start = section.get("startup_mode") == "prepared_no_z" or xy_home
    profile = section.get("profile", {})
    acceleration = profile.get("acceleration", 15000.0)
    max_speed = profile.get("max_speed", 350.0)
    max_motor_speed = profile.get("max_motor_speed", 450.0)
    require(0 < acceleration <= 20000 and 0 < max_speed <= 500 and 0 < max_motor_speed <= 500, "Invalid profile limits")
    z_check = check_z_isolation(path, prepared_start, xy_home)
    actual_moves, parsed = [], []
    toolhead = SimpleNamespace(
        max_accel=acceleration, max_velocity=500.0, max_accel_to_decel=acceleration * 0.5,
        junction_deviation=8.0 ** 2 * (math.sqrt(2.0) - 1.0) / acceleration,
        print_file_line=None, is_calibrating_flow=False,
        extruder=SimpleNamespace(calc_junction=lambda *_: float("inf")),
        _process_moves=actual_moves.extend,
    )
    queue = planner["LookAheadQueue"](toolhead)
    # Z=20 is a simulation reference only. A prepared-start file never
    # sets or measures the real Z height; the operator supplies clearance.
    position = [None, None, 20.0 if prepared_start else None, 0.0]
    in_music = completed = saved = restored = homed = absolute = normalized = mesh_clear = False
    accel = None
    homed = prepared_start and not xy_home
    events = []
    music_started = False
    for line_number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        if raw == "; MELODY_BEGIN":
            require(not music_started and position == [135.0, 135.0, 20.0, 0.0], "Incorrect melody setup")
            require(saved and homed and absolute and normalized and mesh_clear and accel == acceleration, "Missing isolated setup")
            in_music = music_started = True
        elif raw == "; MELODY_END":
            require(in_music, "Unexpected melody end")
            queue.flush()
            in_music = False
            completed = True
        elif raw.startswith("; EVENT "):
            require(in_music, "Event outside music")
            events.append(int(raw.split()[2]))
        code = raw.split(";", 1)[0].strip()
        if not code:
            continue
        command, *args = code.split()
        require(command in ALLOWED, f"Unsupported command at line {line_number}")
        require(not restored or command == "TURN_OFF_HEATERS", "Unexpected command after restore")
        if in_music:
            require(command in {"G1", "G4"}, "Music contains a setup/flush command")
        if command == "SAVE_GCODE_STATE":
            require(args == ["NAME=U1_MIDI"] and not saved and (prepared_start or not homed), "Invalid save")
            saved = True
        elif command == "RESTORE_GCODE_STATE":
            require(completed and args == ["NAME=U1_MIDI", "MOVE=0"], "Restore would cause movement")
            restored = True
        elif command == "G90":
            require(not args, "Invalid coordinate mode")
            absolute = True
        elif command == "M220":
            require(saved and args == ["S100"], "Invalid feed override")
            normalized = True
        elif command == "M204":
            require(saved and args in [["S300"], [f"S{acceleration:.0f}"]], "Unexpected acceleration")
            accel = float(args[0][1:])
        elif command == "G28":
            require(saved and absolute and normalized and accel == 300.0 and not homed and not music_started, "Homing under fast profile")
            if xy_home:
                require(args == ["X", "Y"], "Only standard native G28 X Y homing is allowed")
            else:
                require(not prepared_start and not args, "Unexpected automatic homing")
            homed = True
        elif command == "BED_MESH_CLEAR":
            require(saved and (homed or xy_home) and not music_started and accel == 300.0 and not args, "Invalid mesh clear")
            mesh_clear = homed
        elif command in {"TURN_OFF_HEATERS", "M400"}:
            require(not args, "Unexpected command argument")
        elif command == "G1":
            require(homed and saved and absolute and normalized, "Move before setup")
            require(all(re.fullmatch("[XYZF]" + NUM, a) for a in args), "Malformed move or extrusion")
            require(len(set(a[0] for a in args)) == len(args), "Duplicate move parameter")
            values = {a[0]: float(a[1:]) for a in args}
            require("F" in values and 0 < values["F"] <= max_speed * 60.0, "Feed limit exceeded")
            require(all(math.isfinite(v) for v in values.values()), "Nonfinite move")
            end = list(position)
            for axis, idx in [("X", 0), ("Y", 1), ("Z", 2)]:
                if axis in values:
                    require((55.0 <= values[axis] <= 215.0) if idx < 2 else values[axis] == 20.0, "Position outside bounds")
                    end[idx] = values[axis]
            if in_music:
                require(set(values) == {"X", "Y", "F"} and end[2] == 20.0, "Music contains Z or extrusion")
                require(abs(end[0] - position[0]) > 0.001 and abs(end[1] - position[1]) > 0.001, "Music must use both XY axes")
                move = planner["Move"](toolhead, position, end, values["F"] / 60.0)
                queue.add_move(move)
                parsed.append({"kind": "move", "line": line_number, "end": end, "speed": values["F"] / 60.0})
            elif "Z" in values:
                require(not prepared_start and set(values) == {"Z", "F"} and accel == 300.0 and values["F"] == 300.0 and not music_started, "Unsafe Z setup")
            else:
                setup_feed = 1800.0 if prepared_start else 3600.0
                require(set(values) == {"X", "Y", "F"} and accel == 300.0 and values["F"] == setup_feed, "Unexpected setup/cleanup move")
            position = end
        elif command == "G4":
            require(len(args) == 1 and re.fullmatch("P" + NUM, args[0]), "Invalid wait")
            delay = float(args[0][1:]) / 1000.0
            require(0 <= delay <= 10, "Invalid wait duration")
            if in_music:
                queue.flush()
                parsed.append({"kind": "rest", "duration": delay})
            else:
                require(not completed and delay == 1.0, "Unexpected nonmusical wait")
    require(completed and restored and position == [135.0, 135.0, 20.0, 0.0], "Incomplete cleanup")
    require(events == [f["index"] for f in section["frames"]], "Missing musical events")
    expected = section["instructions"]
    require(len(parsed) == len(expected), "Extra wait or omitted motion")
    movement_targets = []
    rest_total = 0.0
    for actual, wanted in zip(parsed, expected):
        require(actual["kind"] == wanted["kind"], "Unexpected stop between notes")
        if wanted["kind"] == "rest":
            require(abs(actual["duration"] - wanted["duration"]) < 1e-8, "Musical rest changed")
            rest_total += actual["duration"]
        else:
            require(abs(actual["end"][0] - wanted["x"]) < 1e-6 and abs(actual["end"][1] - wanted["y"]) < 1e-6, "Changed trajectory")
            require(abs(actual["speed"] - wanted["speed"]) < 1e-6, "Changed feedrate")
            movement_targets.append(wanted)
    require(len(actual_moves) == len(movement_targets), "Planner lost a move")
    max_cents = max_timing = 0.0
    continuous = 0
    frame_lookup = {f["index"]: f for f in section["frames"]}
    for move, wanted in zip(actual_moves, movement_targets):
        frame = frame_lookup[wanted["frame"]]
        source = [source_notes[i]["pitch"] for i in frame["selected_source_ids"]]
        require(sorted(n % 12 for n in wanted["targets"]) == sorted(n % 12 for n in (source if len(source) > 1 else source * 2)), "Target loses source pitch class")
        if profile.get("faithful_register"):
            desired_register = [max(source), min(source) if len(source) > 1 else source[0] - 12]
            if desired_register[0] == desired_register[1]:
                desired_register[1] -= 12
            require(wanted["targets"] == desired_register, "Original melody/bass register changed")
        require(abs(move.cruise_v - wanted["speed"]) < 1e-6, "Short event cannot reach musical speed")
        dx, dy = move.axes_d[:2]
        speeds = sorted(abs(d) / move.move_d * move.cruise_v for d in [dx + dy, dx - dy])
        require(0 < speeds[0] and speeds[-1] <= max_motor_speed + 1e-5, "Motor speed limit exceeded")
        wanted_hz = sorted(440.0 * 2 ** ((n - 69) / 12.0) for n in wanted["targets"])
        for hz, target in zip([v * 5.0 for v in speeds], wanted_hz):
            cents = abs(1200 * math.log2(hz / target))
            max_cents = max(max_cents, cents)
            require(cents < 0.001, "CoreXY frequency mapping changed")
        timing = abs(move.accel_t + move.cruise_t + move.decel_t - wanted["duration"])
        max_timing = max(max_timing, timing)
        require(timing < 0.00001, "Musical interval timing changed")
        continuous += move.start_v > 0.001
    total = rest_total + sum(m.accel_t + m.cruise_t + m.decel_t for m in actual_moves)
    require(abs(total - section["duration_s"]) < 0.002, "Overall MIDI timing changed")
    return {
        "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_onset_groups": len(section["frames"]), "simulated_moves": len(actual_moves),
        "continuous_move_boundaries": continuous, "musical_rests": sum(p["kind"] == "rest" for p in parsed),
        "simulated_music_duration_s": total, "total_timing_error_ms": (total - section["duration_s"]) * 1000,
        "max_piece_timing_error_us": max_timing * 1e6, "max_cadence_model_error_cents": max_cents,
        "xy_speed_range_mm_s": [min(m.cruise_v for m in actual_moves), max(m.cruise_v for m in actual_moves)],
        "x_range_mm": [min(min(m.start_pos[0], m.end_pos[0]) for m in actual_moves), max(max(m.start_pos[0], m.end_pos[0]) for m in actual_moves)],
        "y_range_mm": [min(min(m.start_pos[1], m.end_pos[1]) for m in actual_moves), max(max(m.start_pos[1], m.end_pos[1]) for m in actual_moves)],
        "z_isolation": z_check, "active_mesh_cleared_before_music": mesh_clear,
        "motion_profile": profile.get("name", "fast"), "xy_acceleration_mm_s2": acceleration,
        "original_melody_register_checked": profile.get("faithful_register", False),
        "no_heat_or_extrusion": "passed", "physical_printer_test": "not performed",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", type=Path)
    p.add_argument("--planner", type=Path, required=True)
    args = p.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    planner = load_planner(args.planner)
    results = {label: validate(args.report.parent / report[label]["file"], report[label], report["source_notes"], planner) for label in ["full", "test"]}
    report["validation"] = results
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
