"""Check emitted K2 Pro motion, native XY macro branches and reference timing.

No MCU, motor protection binary, Creality planner binary or printer is run.
Native endstop triggers are emulated in the macro replay.
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

import jinja2

from convert_midi_k2pro import FINISH_LIMITS, PROFILE, REFERENCE, music_limits, reference_manifest
from convert_poly_midi_u1 import PolyProfile, simulate
from validate_u1_gcode import load_planner, require


def sections(text: str) -> dict[str, str]:
    return dict(re.findall(r"^\[([^\]]+)\][^\n]*\n(.*?)(?=^\[|\Z)", text, re.M | re.S))


def number(body: str, name: str) -> float:
    return float(re.search(r"^" + re.escape(name) + r"\s*[:=]\s*([-+\d.]+)", body, re.M).group(1))


def replay_xy_home(*, z_homed: bool, z_position: float, xy_homed: bool = False) -> dict:
    config = sections((REFERENCE / "sensorless.cfg").read_text(encoding="utf-8"))
    macros = {name.removeprefix("gcode_macro "): body.split("gcode:", 1)[1]
              for name, body in config.items() if name.startswith("gcode_macro ")}
    homed = set("z" if z_homed else "") | (set("xy") if xy_homed else set())
    ready = SimpleNamespace(x_ready=int(xy_homed), y_ready=int(xy_homed), z_ready=int(z_homed),
                            xy_moved=int(xy_homed), z_moved=int(z_homed), safe_z=3)
    position = SimpleNamespace(x=135.0, y=135.0, z=z_position)
    toolhead = SimpleNamespace(homed_axes="".join(sorted(homed)), position=position, max_accel=300.0)
    printer = {
        "gcode_macro xyz_ready": ready,
        "gcode_macro PRINTER_PARAM": SimpleNamespace(z_safe_g28=3.0, max_x_position=300.0,
                                                     max_y_position=302.0, max_z_position=300.0),
        "toolhead": toolhead,
        "print_stats": SimpleNamespace(z_pos=z_position, power_loss=0),
        "configfile": SimpleNamespace(settings={"stepper_x": SimpleNamespace(position_max=302.0)}),
    }
    environment = jinja2.Environment(variable_start_string="{", variable_end_string="}")
    absolute, endstop_axes, z_commands = True, [], []

    def run_template(body: str, params=None):
        rendered = environment.from_string(body).render(printer=printer, params=params or {}, action_respond_info=lambda *_: "")
        execute(rendered)

    def execute(text: str):
        nonlocal absolute
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].split(";", 1)[0].strip()
            if not line:
                continue
            command, *args = line.split()
            if command in macros:
                run_template(macros[command])
            elif command == "SET_GCODE_VARIABLE":
                values = dict(arg.split("=", 1) for arg in args)
                require(values["MACRO"] == "xyz_ready", "Unexpected macro state")
                setattr(ready, values["VARIABLE"], int(values["VALUE"]))
            elif command == "G28":
                # Nested G28 in the stock homing override invokes native
                # homing. Emulate the selected endstop and retain Z.
                require(args in (["X"], ["Y"]), "Unexpected Z homing branch")
                axis = args[0].lower()
                endstop_axes.append(axis)
                setattr(position, axis, 302.0 if axis == "x" else -6.5)
                homed.add(axis)
                toolhead.homed_axes = "".join(sorted(homed))
            elif command in {"G90", "G91"}:
                absolute = command == "G90"
            elif command in {"G0", "G1"}:
                values = {a[0].upper(): float(a[1:]) for a in args}
                for axis in "XYZ":
                    if axis in values:
                        if axis == "Z":
                            z_commands.append(line)
                        old = getattr(position, axis.lower())
                        setattr(position, axis.lower(), values[axis] if absolute else old + values[axis])
            elif command == "FORCE_MOVE":
                values = dict(arg.split("=", 1) for arg in args)
                if values["STEPPER"].startswith("stepper_z"):
                    z_commands.append(line)
                else:
                    require(values["STEPPER"] == "stepper_y", "Unexpected stock motor move")
            elif command == "M204":
                toolhead.max_accel = float(args[0][1:])
            else:
                require(command in {"BED_MESH_CLEAR", "BED_MESH_PROFILE", "MOTOR_STALL_MODE",
                                    "MOTOR_CHECK_PROTECTION_AFTER_HOME", "G4"}, "Unexpected native macro command: " + command)

    run_template(config["homing_override"].split("gcode:", 1)[1], {"X": "0", "Y": "0"})
    require(set(endstop_axes) == {"x", "y"}, "Native macro omitted an XY endstop")
    return {"z_initially_homed": z_homed, "z_initial_reference_mm": z_position,
            "xy_initially_homed": xy_homed, "native_xy_endstop_order": endstop_axes,
            "z_commands_in_rendered_stock_macros": z_commands,
            "hardware": "endstop triggers emulated; native motor protection binary not executed"}


def kinematics():
    config = sections((REFERENCE / "printer.cfg").read_text(encoding="utf-8"))
    require(config["printer"].splitlines()[0].strip() == "kinematics: corexy", "Wrong kinematics")
    for axis in "xy":
        require(number(config["stepper_" + axis], "rotation_distance") == 40, "Wrong pulley geometry")
        require(number(config["stepper_" + axis], "microsteps") == 16, "Wrong microstep profile")
    tree = ast.parse((REFERENCE / "corexy.py").read_text(encoding="utf-8"))
    namespace = {"math": math}
    definition = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CoreXYKinematics"]
    exec(compile(ast.Module(body=definition, type_ignores=[]), "K2/corexy.py", "exec"), namespace)
    kin = object.__new__(namespace["CoreXYKinematics"])
    kin.limits = [(number(config["stepper_" + a], "position_min"), number(config["stepper_" + a], "position_max")) for a in "xyz"]
    return kin


def validate(path: Path, section: dict, source_notes: list, planner: dict, profile: PolyProfile = PROFILE) -> dict:
    require(0 < profile.max_speed <= 180 and 0 < profile.acceleration <= 7000, "Unsafe profile")
    require(profile.cadence_per_mm in (5.0, 80.0), "Uncalibrated cadence model")
    limits = music_limits(profile)
    text = path.read_text(encoding="ascii")
    before, rest = text.split("; MELODY_BEGIN\n")
    music, after = rest.split("; MELODY_END\n")
    code = lambda block: [line.split(";", 1)[0].strip() for line in block.splitlines() if line.split(";", 1)[0].strip()]
    prefix, suffix = code(before), code(after)
    require(prefix.count("G28 X Y") == 1, "Missing real XY homing")
    home = prefix.index("G28 X Y")
    require("BED_MESH_CLEAR" in prefix[:home] and "BED_MESH_CLEAR" in prefix[home + 1:], "Mesh must clear before and after home")
    require(prefix[-2:] == [limits, "G4 P1000"], "Wrong music limits or setup ordering")
    require(suffix == ["M400", "M204 S300", "G1 X135.0000000 Y135.0000000 F1800", "M400",
                       FINISH_LIMITS, "RESTORE_GCODE_STATE NAME=K2PRO_MIDI MOVE=0", "TURN_OFF_HEATERS"], "Unsafe finish")
    allowed = {"TURN_OFF_HEATERS", "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE", "G21", "G90", "M220", "M204",
               "BED_MESH_CLEAR", "G28", "M400", "G1", "G4", "SET_VELOCITY_LIMIT"}
    for line in code(text):
        command, *args = line.split()
        require(command in allowed, "Unexpected command: " + command)
        if command in {"G0", "G1"}:
            require({arg[0] for arg in args} == {"X", "Y", "F"}, "Z, extrusion or malformed move")
        if command == "G28":
            require(line == "G28 X Y", "Unexpected homing request")
    require(prefix[:7] == ["TURN_OFF_HEATERS", "SAVE_GCODE_STATE NAME=K2PRO_MIDI", "G21", "G90", "M220 S100",
                            "M204 S300", "BED_MESH_CLEAR"], "Missing cold normalized startup")
    require(prefix[home + 1:] == ["M400", "BED_MESH_CLEAR", "G90", "M204 S300",
                                  "G1 X135.0000000 Y135.0000000 F1800", "M400", limits, "G4 P1000"], "Unexpected setup motion")
    kin = kinematics()
    position = [135.0, 135.0, 20.0, 0.0]
    actual, targets, event_ids = [], [], []
    frames = {f["index"]: f for f in section["frames"]}
    frame = None
    for raw in music.splitlines():
        if raw.startswith("; EVENT "):
            frame = int(raw.split()[2])
            require(frame in frames, "Unknown frame")
            event_ids.append(frame)
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        command, *args = line.split()
        if command == "G4":
            require(len(args) == 1 and args[0].startswith("P"), "Malformed rest")
            duration = float(args[0][1:]) / 1000.0
            require(0 < duration < 5, "Bad rest")
            actual.append({"kind": "rest", "duration": duration})
            continue
        require(command == "G1" and len(args) == 3, "Music interrupted by setup")
        values = {arg[0]: float(arg[1:]) for arg in args}
        require(set(values) == {"X", "Y", "F"}, "Music has Z or extrusion")
        require(all(math.isfinite(v) for v in values.values()), "Nonfinite move")
        require(0 < values["F"] <= profile.max_speed * 60, "XY exceeds selected speed")
        end = [values["X"], values["Y"], 20.0, 0.0]
        require(all(55 <= v <= 215 for v in end[:2]), "Outside central music area")
        require(all(abs(end[i] - position[i]) > 0.001 for i in (0, 1)), "Both XY axes must participate")
        move = planner["Move"](SimpleNamespace(max_accel=profile.acceleration, max_velocity=profile.max_speed,
                   max_accel_to_decel=profile.acceleration / 2, junction_deviation=1,
                   print_file_line=None), position, end, values["F"] / 60)
        kin.check_move(move)
        actual.append({"kind": "move", "x": end[0], "y": end[1], "speed": values["F"] / 60})
        targets.append(frames[frame])
        position = end
    require(event_ids == list(frames), "Source onsets changed")
    require(len(actual) == len(section["instructions"]), "Extra stops or missing motion")
    rests = 0.0
    for emitted, planned in zip(actual, section["instructions"]):
        require(emitted["kind"] == planned["kind"], "Changed articulation")
        for key in ("x", "y", "speed") if emitted["kind"] == "move" else ("duration",):
            require(abs(emitted[key] - planned[key]) < 1e-6, "Changed route or timing")
        rests += emitted.get("duration", 0)
    moves = simulate(actual, planner, profile)
    require(len(moves) == len(targets), "Reference model dropped a move")
    max_cents = 0.0
    emitted_moves = [i for i in actual if i["kind"] == "move"]
    for move, frame, emitted in zip(moves, targets, emitted_moves):
        source = [source_notes[i]["pitch"] for i in frame["selected_source_ids"]]
        lead = max(source)
        bass = min(source) if len(source) > 1 else lead - 12
        if lead == bass:
            bass -= 12
        hz = sorted(440 * 2 ** ((n - 69) / 12) for n in (lead, bass))
        dx, dy = move.axes_d[:2]
        motor_hz = sorted(abs(d) / move.move_d * move.cruise_v * profile.cadence_per_mm for d in (dx + dy, dx - dy))
        max_cents = max(max_cents, *(abs(1200 * math.log2(a / b)) for a, b in zip(motor_hz, hz)))
        require(abs(move.cruise_v - emitted["speed"]) < 1e-5, "Note cannot reach intended cruise speed")
    require(max_cents < 0.001, f"Original melody/bass cadence not reached: {max_cents:.6f} cents")
    duration = rests + sum(m.accel_t + m.cruise_t + m.decel_t for m in moves)
    require(abs(duration - section["duration_s"]) < 0.002, "Reference-model timing changed")
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "xy_moves": len(moves), "continuous_boundaries": sum(m.start_v > 0.001 for m in moves),
            "explicit_z_moves": 0, "heating_or_extrusion_commands": 0,
            "stock_kinematic_bounds_check": "passed", "reference_model_music_s": duration,
            "max_cadence_model_error_cents": max_cents, "cadence_model_per_mm": profile.cadence_per_mm,
            "xy_acceleration_mm_s2": profile.acceleration,
            "xy_speed_range_mm_s": [min(m.cruise_v for m in moves), max(m.cruise_v for m in moves)],
            "native_creality_motion_planner_executed": False, "physical_printer_tested": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--planner", type=Path, required=True)
    args = parser.parse_args()
    reference_manifest()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    planner = load_planner(args.planner)
    profile = PolyProfile(**report["profile"])
    results = {label: validate(args.report.parent / report[label]["file"], report[label], report["source_notes"], planner, profile)
               for label in ("full", "test")}
    homing = [replay_xy_home(z_homed=True, z_position=z, xy_homed=xy) for z in (20.0, 275.0) for xy in (False, True)]
    require(all(not h["z_commands_in_rendered_stock_macros"] for h in homing), "Prepared startup contains Z movement")
    negative = replay_xy_home(z_homed=False, z_position=20.0)
    require(bool(negative["z_commands_in_rendered_stock_macros"]), "Missing-Z-reference control was not reproduced")
    results["native_macro_replay_prepared"] = homing
    results["unprepared_Z_negative_control"] = negative
    report["validation"] = results
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
